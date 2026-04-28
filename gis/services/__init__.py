"""GIS inspection services."""

from .discover import inspect_submission
from .manifest import (
    auto_promote_discovered_layer,
    bulk_approve_submission_layers,
    evaluate_layer_for_auto_approval,
    fetch_manifest_sample_data,
    promote_layer_to_manifest,
)

__all__ = [
    "inspect_submission",
    "promote_layer_to_manifest",
    "auto_promote_discovered_layer",
    "evaluate_layer_for_auto_approval",
    "bulk_approve_submission_layers",
    "fetch_manifest_sample_data",
]
