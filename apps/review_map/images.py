"""Bounded server-side image loading with no source URLs in browser state."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import threading
import time
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000


class ImageUnavailable(ValueError):
    """An image cannot be safely downloaded or decoded."""


def allowed_url(url: str, hosts: tuple[str, ...] = ("staticflickr.com",)) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and any(host == base or host.endswith("." + base) for base in hosts)
        )
    except ValueError:
        return False


def make_thumbnail(body: bytes) -> bytes:
    if len(body) > MAX_BYTES:
        raise ImageUnavailable("Image unavailable.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as original:
                if original.width * original.height > MAX_PIXELS:
                    raise ImageUnavailable("Image unavailable.")
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((640, 480))
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=82, method=4)
        return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ImageUnavailable("Image unavailable.") from None


class Thumbnails:
    def __init__(self, directory: Path, *, max_entries: int = 1024, ttl: int = 86_400):
        self.directory = directory
        self.max_entries = max_entries
        self.ttl = ttl
        self._cache_lock = threading.Lock()
        self._download_slots = threading.BoundedSemaphore(2)
        directory.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> bytes:
        if not allowed_url(url):
            raise ImageUnavailable("Image unavailable.")
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / (key + ".webp")
        with self._cache_lock:
            try:
                if time.time() - path.stat().st_mtime < self.ttl:
                    data = path.read_bytes()
                    if len(data) <= MAX_BYTES:
                        return data
            except OSError:
                pass
        with self._download_slots:
            body = self._download(url)
        thumbnail = make_thumbnail(body)
        temporary = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
        with self._cache_lock:
            try:
                temporary.write_bytes(thumbnail)
                temporary.chmod(0o600)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            entries = sorted(self.directory.glob("*.webp"), key=lambda p: p.stat().st_mtime)
            for expired in entries[: max(0, len(entries) - self.max_entries)]:
                expired.unlink(missing_ok=True)
        return thumbnail

    @staticmethod
    def _download(url: str) -> bytes:
        try:
            for _ in range(3):
                if not allowed_url(url):
                    break
                with requests.get(
                    url,
                    stream=True,
                    timeout=(4, 12),
                    allow_redirects=False,
                    headers={"User-Agent": "ReviewMap/1.0"},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers.get("Location", ""))
                        continue
                    if response.status_code != 200:
                        break
                    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                        break
                    chunks, size = [], 0
                    for chunk in response.iter_content(64 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ImageUnavailable("Image unavailable.")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except requests.RequestException:
            pass
        raise ImageUnavailable("Image unavailable.")


def image_response(photo, token: str, thumbnails: Thumbnails) -> dict:
    for url in dict.fromkeys([photo.image_url, photo.fallback_url]):
        if not url:
            continue
        try:
            image = thumbnails.get(url)
            return {
                "token": token,
                "image": "data:image/webp;base64," + base64.b64encode(image).decode("ascii"),
            }
        except ImageUnavailable:
            continue
    return {"token": token, "unavailable": True}
