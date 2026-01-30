"""Checkpoint utilities for the restaurant report pipeline."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Optional, Type

from django.db import transaction

from schemas.io import dump_model, load_model
from schemas.models import SchemaBase

from agent.models import RestaurantReportCheckpoint, RestaurantReportJob


def _serialize_payload(model: SchemaBase) -> str:
    """Convert a schema model to a deterministic JSON string."""

    base = dump_model(model)
    return json.dumps(base, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _checksum(payload: str) -> str:
    """SHA256 checksum for payload integrity checks."""

    return sha256(payload.encode("utf-8")).hexdigest()


def save_checkpoint(job: RestaurantReportJob, step: str, payload: SchemaBase) -> RestaurantReportCheckpoint:
    """Persist a schema payload under the job/step key."""

    payload_str = _serialize_payload(payload)
    payload_hash = _checksum(payload_str)

    with transaction.atomic():
        checkpoint, _ = RestaurantReportCheckpoint.objects.update_or_create(
            job=job,
            step=step,
            defaults={
                "payload": payload_str,
                "schema_version": payload.schema_version,
                "checksum": payload_hash,
            },
        )
    return checkpoint


def get_checkpoint(job: RestaurantReportJob, step: str, schema_cls: Type[SchemaBase]) -> Optional[SchemaBase]:
    """Retrieve and validate a persisted checkpoint."""

    checkpoint = (
        RestaurantReportCheckpoint.objects.filter(job=job, step=step)
        .order_by("-created_at")
        .first()
    )

    if not checkpoint:
        return None

    version_field = getattr(schema_cls, "model_fields", None)
    if version_field and "schema_version" in version_field:
        expected_version = version_field["schema_version"].default
    else:
        expected_version = schema_cls.__fields__["schema_version"].default  # type: ignore[attr-defined]

    if checkpoint.schema_version != expected_version:
        return None

    return load_model(schema_cls, json.loads(checkpoint.payload))


def checkpoint_exists(job: RestaurantReportJob, step: str) -> bool:
    """Return True when at least one checkpoint exists for the step."""

    return RestaurantReportCheckpoint.objects.filter(job=job, step=step).exists()
