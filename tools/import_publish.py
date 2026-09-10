"""One atomic publication transaction, consuming already-validated insertion chunks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from tools.candidate_rows import Candidate, _optional_text, _required_text
from tools.candidate_spool import CandidateChunk
from tools.common import AdminError


@dataclass(frozen=True, slots=True)
class ImportSpec:
    campaign_code: str
    internal_name: str
    reviewer_name: str
    target_taxon_key: str | None
    target_scientific_name: str
    source_provider: str | None
    status: str
    batch_prefix: str
    batch_size: int


def import_spec(
    *,
    campaign_code: str,
    internal_name: str,
    reviewer_name: str,
    batch_prefix: str,
    target_scientific_name: str,
    batch_size: int = 1000,
    status: str = "draft",
    target_taxon_key: str | None = None,
    source_provider: str | None = None,
) -> ImportSpec:
    if not 1 <= batch_size <= 1000:
        raise AdminError("Batch size must be between 1 and 1000.")
    if status not in {"draft", "open"}:
        raise AdminError("Imported campaigns must be draft or open.")
    return ImportSpec(
        campaign_code=_required_text(campaign_code, "campaign code", 80),
        internal_name=_required_text(internal_name, "internal name", 500),
        reviewer_name=_required_text(reviewer_name, "reviewer name", 120),
        target_taxon_key=_optional_text(target_taxon_key, 200),
        target_scientific_name=_required_text(
            target_scientific_name, "target scientific name", 500
        ),
        source_provider=_optional_text(source_provider, 120),
        status=status,
        batch_prefix=_required_text(batch_prefix, "batch prefix", 60),
        batch_size=batch_size,
    )


_ITEM_COLUMNS = (
    "batch_id, position, image_id, source_provider, source_record_id, display_url, image_url, "
    "source_page_url, flickr_search_term, source_labels, pipeline_metadata"
)
_INSERT_ITEMS = (
    f"insert into public.review_items ({_ITEM_COLUMNS}) values ({', '.join(['%s'] * 11)})"
)
_COPY_ITEMS = f"copy public.review_items ({_ITEM_COLUMNS}) from stdin"


def item_values(batch_id: object, position: int, candidate: Candidate) -> tuple[object, ...]:
    return (
        batch_id,
        position,
        candidate.image_id,
        candidate.source_provider,
        candidate.source_record_id,
        candidate.display_url,
        candidate.image_url,
        candidate.source_page_url,
        candidate.flickr_search_term,
        Jsonb(candidate.source_labels) if candidate.source_labels is not None else None,
        Jsonb(candidate.pipeline_metadata) if candidate.pipeline_metadata is not None else None,
    )


def publish_candidates(
    spec: ImportSpec,
    chunks: Iterable[CandidateChunk],
    dsn: str,
    *,
    expected_batches: int,
    expected_items: int,
    method: str = "pipeline",
    connect: Callable[[str], psycopg.Connection[Any]] | None = None,
) -> tuple[int, int, int]:
    if method not in {"pipeline", "copy"}:
        raise AdminError("Unknown candidate insertion method.")
    batch_count = item_count = batch_items = 0
    batch_id = None
    with (connect or psycopg.connect)(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """insert into public.review_campaigns (
                internal_name, reviewer_name, campaign_code, target_taxon_key,
                target_scientific_name, source_provider, status
            ) values (%s, %s, %s, %s, %s, %s, %s::public.campaign_status) returning id""",
            (
                spec.internal_name,
                spec.reviewer_name,
                spec.campaign_code,
                spec.target_taxon_key,
                spec.target_scientific_name,
                spec.source_provider,
                spec.status,
            ),
        )
        campaign = cursor.fetchone()
        if campaign is None:
            raise AdminError("Campaign insert did not return an ID.")
        for chunk in chunks:
            if not chunk.candidates:
                raise AdminError("An insertion chunk must not be empty.")
            if chunk.batch_position != batch_count:
                if chunk.batch_position != batch_count + 1 or (
                    batch_count and batch_items != spec.batch_size
                ):
                    raise AdminError("Candidate batch order changed after validation.")
                code = f"{spec.batch_prefix}-{chunk.batch_position:03d}"
                cursor.execute(
                    """insert into public.review_batches (
                        campaign_id, batch_code, reviewer_name, position, status, opened_at
                    ) values (%s, %s, %s, %s, %s::public.batch_status,
                        case when %s = 'open' then now() else null end) returning id""",
                    (
                        campaign[0],
                        code,
                        f"Batch {code}",
                        chunk.batch_position,
                        spec.status,
                        spec.status,
                    ),
                )
                batch = cursor.fetchone()
                if batch is None:
                    raise AdminError("Batch insert did not return an ID.")
                batch_id, batch_count, batch_items = batch[0], chunk.batch_position, 0
            if (
                chunk.first_position != batch_items + 1
                or batch_items + len(chunk.candidates) > spec.batch_size
            ):
                raise AdminError("Candidate item order changed after validation.")
            values = (
                item_values(batch_id, position, candidate)
                for position, candidate in enumerate(chunk.candidates, chunk.first_position)
            )
            if method == "copy":
                with cursor.copy(_COPY_ITEMS) as writer:
                    for row in values:
                        writer.write_row(row)
            else:
                cursor.executemany(_INSERT_ITEMS, values)
            batch_items += len(chunk.candidates)
            item_count += len(chunk.candidates)
        if (batch_count, item_count) != (expected_batches, expected_items):
            raise AdminError("Candidate counts changed after validation.")
    return (1, batch_count, item_count)
