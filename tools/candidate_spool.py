"""Disk-backed validation/order staging; no database credentials or network access."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.candidate_rows import Candidate, candidate_from_row
from tools.common import AdminError

SHUFFLE_ALGORITHM = "sha256-v1"
MAX_ROW_BYTES = 16 * 1024 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
_CANDIDATE_FIELDS = tuple(field.name for field in fields(Candidate))


@dataclass(frozen=True, slots=True)
class CandidateChunk:
    batch_position: int
    first_position: int
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True, slots=True)
class ValidatedCandidates:
    connection: sqlite3.Connection
    item_count: int
    batch_size: int
    shuffled: bool

    @property
    def batch_count(self) -> int:
        return (self.item_count + self.batch_size - 1) // self.batch_size

    @property
    def order(self) -> str:
        return "shuffle_key, ordinal" if self.shuffled else "ordinal"

    def chunks(self) -> Iterator[CandidateChunk]:
        """Byte-limited insertion chunks never change logical batch/item positions."""
        pending: list[Candidate] = []
        pending_bytes = 0
        batch_position = first_position = 1
        with closing(
            self.connection.execute(f"select payload from candidates order by {self.order}")
        ) as cursor:
            for index, (payload,) in enumerate(cursor):
                batch, position = divmod(index, self.batch_size)
                if pending and (
                    batch + 1 != batch_position or pending_bytes + len(payload) > MAX_CHUNK_BYTES
                ):
                    yield CandidateChunk(batch_position, first_position, tuple(pending))
                    pending.clear()
                    pending_bytes = 0
                if not pending:
                    batch_position, first_position = batch + 1, position + 1
                pending.append(Candidate(**json.loads(payload)))
                pending_bytes += len(payload)
            if pending:
                yield CandidateChunk(batch_position, first_position, tuple(pending))


@contextmanager
def validate_candidates(
    rows: Iterable[dict[str, object]],
    *,
    batch_size: int = 1000,
    shuffle_seed: int | None = None,
    temporary_parent: Path | None = None,
) -> Iterator[ValidatedCandidates]:
    """Validate once before publication; remove the private spool on every exit.

    Seed 0 is a real seed. The versioned SHA-256 order is global, independent of
    chunk boundaries and Python/Polars PRNG versions, not the legacy Polars order.
    A hash collision is resolved by original ordinal. Unshuffled rows retain input order.
    """
    if not 1 <= batch_size <= 1000:
        raise AdminError("Batch size must be between 1 and 1000.")
    with TemporaryDirectory(prefix=".veritaxa-import-", dir=temporary_parent) as temporary:
        with closing(sqlite3.connect(Path(temporary) / "validated.sqlite")) as connection:
            connection.execute("pragma cache_size = -4096")
            connection.execute("pragma temp_store = FILE")
            connection.execute("pragma mmap_size = 0")
            connection.execute(
                "create table candidates (ordinal integer primary key, image_id text not null, "
                "shuffle_key blob, payload blob not null)"
            )
            if shuffle_seed is not None:
                # Maintain the thin index incrementally; avoid a bulk index-build sort.
                connection.execute(
                    "create index shuffled_candidates on candidates(shuffle_key, ordinal)"
                )
            item_count = 0
            with closing(connection.cursor()) as insert_cursor:
                for index, row in enumerate(rows):
                    try:
                        candidate = candidate_from_row(row)
                        payload = json.dumps(
                            {name: getattr(candidate, name) for name in _CANDIDATE_FIELDS},
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    except (TypeError, ValueError, OverflowError) as error:
                        raise AdminError(
                            "Candidate metadata must be finite, JSON-compatible values."
                        ) from error
                    if len(payload) > MAX_ROW_BYTES:
                        raise AdminError("Normalized candidate exceeds the 16 MiB limit.")
                    shuffle_key = (
                        hashlib.sha256(
                            f"veritaxa-shuffle-{SHUFFLE_ALGORITHM}:{shuffle_seed}:{index}".encode(
                                "ascii"
                            )
                        ).digest()
                        if shuffle_seed is not None
                        else None
                    )
                    insert_cursor.execute(
                        "insert into candidates values (?, ?, ?, ?)",
                        (index, candidate.image_id, shuffle_key, payload),
                    )
                    item_count += 1
                    del row, candidate, payload
            validated = ValidatedCandidates(
                connection, item_count, batch_size, shuffle_seed is not None
            )
            # Validate final logical batches after global shuffle without decoding bulky payloads.
            seen: set[str] = set()
            with closing(
                connection.execute(f"select image_id from candidates order by {validated.order}")
            ) as cursor:
                for index, (image_id,) in enumerate(cursor):
                    if index % batch_size == 0:
                        seen.clear()
                    if image_id in seen:
                        raise AdminError("Duplicate image IDs are not allowed within a batch.")
                    seen.add(image_id)
            seen.clear()
            connection.commit()
            connection.execute("pragma query_only = true")
            yield validated
