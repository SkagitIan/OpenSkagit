import json
import logging
import subprocess
import sys
from pathlib import Path
from threading import Thread

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.db import close_old_connections
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .constants import QUALIFICATION_STATUS_REJECTED, SOURCE_SUBMISSION_STATUS_INSPECTING
from .forms import (
    GISDiscoveredLayerReviewForm,
    GISManifestFilterForm,
    GISManifestPromotionForm,
    GISSourceSubmissionForm,
)
from .models import GISDiscoveredLayer, GISLayerManifest, GISSourceSubmission
from .services.discover import inspect_submission as run_submission_inspection
from .services.manifest import (
    auto_promote_discovered_layer,
    bulk_approve_submission_layers,
    evaluate_layer_for_auto_approval,
    fetch_manifest_map_preview,
    fetch_manifest_sample_data,
    promote_layer_to_manifest,
)

GIS_META_DESCRIPTION = (
    "Internal OpenSkagit GIS source discovery, qualification, and manifest management workflow."
)
logger = logging.getLogger(__name__)


@staff_member_required
@require_http_methods(["GET", "POST"])
def submission_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = GISSourceSubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save()
            _queue_submission_inspection(submission)
            messages.success(request, "Submission created. Inspection started in background.")
            return redirect("gis:submission-detail", submission_id=submission.pk)
        messages.error(request, "Please correct the form errors and try again.")
    else:
        form = GISSourceSubmissionForm()

    submissions = GISSourceSubmission.objects.order_by("-submitted_at")[:100]
    manifest_entries = (
        GISLayerManifest.objects.select_related("source_submission", "discovered_layer")
        .order_by("-updated_at", "key")[:100]
    )

    context = {
        "submissions": submissions,
        "manifest_entries": manifest_entries,
        "form": form,
    }
    context.update(_page_meta("GIS Source Submissions"))
    return render(request, "gis/submission_list.html", context)


@staff_member_required
@require_http_methods(["GET", "POST"])
def submission_new(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = GISSourceSubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save()
            _queue_submission_inspection(submission)
            messages.success(request, "Submission created. Inspection started in background.")
            return redirect("gis:submission-detail", submission_id=submission.pk)
    else:
        form = GISSourceSubmissionForm()

    context = {"form": form}
    context.update(_page_meta("New GIS Submission"))
    return render(request, "gis/submission_form.html", context)


@staff_member_required
@require_POST
def submission_run_inspection(request: HttpRequest, submission_id: int) -> HttpResponse:
    submission = get_object_or_404(GISSourceSubmission, pk=submission_id)
    _queue_submission_inspection(submission)
    messages.success(request, "Inspection started in background.")
    if _is_htmx(request):
        context = {"submission": submission}
        context.update(_build_submission_layer_context(submission))
        return render(request, "gis/partials/submission_layers_panel.html", context)
    return redirect("gis:submission-detail", submission_id=submission.pk)


@staff_member_required
@require_http_methods(["GET"])
def submission_layers_panel(request: HttpRequest, submission_id: int) -> HttpResponse:
    submission = get_object_or_404(GISSourceSubmission, pk=submission_id)
    context = {"submission": submission}
    context.update(_build_submission_layer_context(submission))
    return render(request, "gis/partials/submission_layers_panel.html", context)


@staff_member_required
@require_POST
def submission_approve_all(request: HttpRequest, submission_id: int) -> HttpResponse:
    submission = get_object_or_404(GISSourceSubmission, pk=submission_id)
    result = bulk_approve_submission_layers(submission)

    approved_count = int(result.get("approved_count", 0))
    skipped_count = int(result.get("skipped_count", 0))
    skipped = result.get("skipped", [])

    if approved_count:
        messages.success(request, f"Added {approved_count} layer(s) to the manifest.")
    else:
        messages.warning(request, "No layers could be added from this submission.")

    if skipped_count:
        preview = []
        for item in skipped[:5]:
            layer_name = item.get("layer_name") or f"layer_{item.get('layer_id')}"
            reasons = item.get("reasons") or []
            preview.append(f"{layer_name}: {', '.join(str(reason) for reason in reasons)}")
        suffix = " ..." if skipped_count > 5 else ""
        messages.info(request, f"Skipped {skipped_count} layer(s): {'; '.join(preview)}{suffix}")

    if _is_htmx(request):
        context = {"submission": submission}
        context.update(_build_submission_layer_context(submission))
        return render(request, "gis/partials/submission_layers_panel.html", context)

    return redirect("gis:submission-detail", submission_id=submission.pk)


@staff_member_required
@require_POST
def submission_add_layer(request: HttpRequest, submission_id: int, layer_id: int) -> HttpResponse:
    layer = get_object_or_404(GISDiscoveredLayer, pk=layer_id, source_submission_id=submission_id)
    manifest_entry, reasons = auto_promote_discovered_layer(layer)
    if manifest_entry is not None:
        messages.success(request, f"Added layer '{manifest_entry.label}' to manifest.")
    else:
        messages.warning(
            request,
            f"Layer not added: {', '.join(str(reason) for reason in reasons) if reasons else 'unknown reason'}",
        )

    if _is_htmx(request):
        submission = layer.source_submission
        context = {"submission": submission}
        context.update(_build_submission_layer_context(submission))
        return render(request, "gis/partials/submission_layers_panel.html", context)

    return redirect("gis:submission-detail", submission_id=submission_id)


@staff_member_required
@require_http_methods(["GET"])
def submission_detail(request: HttpRequest, submission_id: int) -> HttpResponse:
    submission = get_object_or_404(GISSourceSubmission, pk=submission_id)
    context = {"submission": submission}
    context.update(_build_submission_layer_context(submission))
    context.update(_page_meta(f"GIS Submission #{submission.pk}"))
    return render(request, "gis/submission_detail.html", context)


@staff_member_required
@require_http_methods(["GET", "POST"])
def discovered_layer_review(request: HttpRequest, layer_id: int) -> HttpResponse:
    layer = get_object_or_404(GISDiscoveredLayer.objects.select_related("source_submission"), pk=layer_id)

    if request.method == "POST":
        action = request.POST.get("action", "save")
        review_form = GISDiscoveredLayerReviewForm(request.POST, instance=layer)
        promotion_form = GISManifestPromotionForm(request.POST, discovered_layer=layer)

        if action == "save":
            if review_form.is_valid():
                review_form.save()
                messages.success(request, "Layer review fields saved.")
                return redirect("gis:layer-review", layer_id=layer.pk)
        elif action == "reject":
            if review_form.is_valid():
                reviewed_layer = review_form.save(commit=False)
                reviewed_layer.qualification_status = QUALIFICATION_STATUS_REJECTED
                reviewed_layer.save()
                messages.success(request, "Layer marked rejected.")
                return redirect("gis:layer-review", layer_id=layer.pk)
        elif action == "approve":
            review_ok = review_form.is_valid()
            promotion_ok = promotion_form.is_valid()
            if review_ok and promotion_ok:
                reviewed_layer = review_form.save()
                manifest_entry = promote_layer_to_manifest(
                    discovered_layer=reviewed_layer,
                    key=promotion_form.cleaned_data["key"],
                    label=promotion_form.cleaned_data["label"],
                    category=promotion_form.cleaned_data["category"],
                    default_fields=promotion_form.cleaned_data["default_fields"],
                    canonical_for_category=promotion_form.cleaned_data["canonical_for_category"],
                    notes=promotion_form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Layer approved and promoted to manifest.")
                return redirect("gis:manifest-detail", manifest_id=manifest_entry.pk)
        else:
            messages.error(request, "Unknown action.")
    else:
        review_form = GISDiscoveredLayerReviewForm(instance=layer)
        promotion_form = GISManifestPromotionForm(discovered_layer=layer)

    qualification = layer.qualification_results_json or {}

    context = {
        "layer": layer,
        "review_form": review_form,
        "promotion_form": promotion_form,
        "metadata_json_pretty": _pretty_json(layer.metadata_json),
        "qualification_json_pretty": _pretty_json(qualification),
        "fields_json_pretty": _pretty_json(layer.fields_json),
        "capabilities_json_pretty": _pretty_json(layer.capabilities_json),
    }
    context.update(_page_meta(f"GIS Layer Review #{layer.pk}"))
    return render(request, "gis/discovered_layer_review.html", context)


@staff_member_required
@require_http_methods(["GET"])
def manifest_list(request: HttpRequest) -> HttpResponse:
    context = _build_manifest_list_context(request.GET or None)
    context.update(_page_meta("GIS Manifest Registry"))
    if _is_htmx(request):
        return render(request, "gis/partials/manifest_list_panel.html", context)
    return render(request, "gis/manifest_list.html", context)


@staff_member_required
@require_http_methods(["GET"])
def manifest_map_modal(request: HttpRequest, manifest_id: int) -> HttpResponse:
    entry = get_object_or_404(GISLayerManifest, pk=manifest_id)
    map_preview = fetch_manifest_map_preview(entry, max_features=200)
    map_payload = {
        "geojson": map_preview.get("geojson") or {"type": "FeatureCollection", "features": []},
        "bounds": map_preview.get("bounds"),
    }
    context = {
        "entry": entry,
        "map_preview": map_preview,
        "map_payload": map_payload,
    }
    return render(request, "gis/partials/manifest_map_modal.html", context)


@staff_member_required
@require_http_methods(["GET"])
def manifest_map_modal_clear(request: HttpRequest) -> HttpResponse:
    return HttpResponse("")


@staff_member_required
@require_POST
def manifest_test(request: HttpRequest, manifest_id: int) -> HttpResponse:
    entry = get_object_or_404(GISLayerManifest, pk=manifest_id)
    sample_result = fetch_manifest_sample_data(entry, sample_size=3)
    if sample_result.get("ok"):
        messages.success(
            request,
            f"Test ok for '{entry.key}': {sample_result.get('record_count', 0)} sample record(s) returned.",
        )
    else:
        messages.warning(request, f"Test failed for '{entry.key}'.")
    if _is_htmx(request):
        context = _build_manifest_list_context(request.POST or None)
        return render(request, "gis/partials/manifest_list_panel.html", context)
    return redirect("gis:manifest-list")


@staff_member_required
@require_POST
def manifest_delete(request: HttpRequest, manifest_id: int) -> HttpResponse:
    entry = get_object_or_404(GISLayerManifest, pk=manifest_id)
    key = entry.key
    entry.delete()
    messages.success(request, f"Deleted manifest entry '{key}'.")
    if _is_htmx(request):
        context = _build_manifest_list_context(request.POST or None)
        return render(request, "gis/partials/manifest_list_panel.html", context)
    return redirect("gis:manifest-list")


@staff_member_required
@require_http_methods(["GET", "POST"])
def manifest_detail(request: HttpRequest, manifest_id: int) -> HttpResponse:
    entry = get_object_or_404(
        GISLayerManifest.objects.select_related("source_submission", "discovered_layer"),
        pk=manifest_id,
    )
    sample_result = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower() or "sample"
        next_path = _safe_next_path(request.POST.get("next"))

        if action == "delete":
            key = entry.key
            entry.delete()
            messages.success(request, f"Deleted manifest entry '{key}'.")
            return redirect(next_path or "gis:manifest-list")

        sample_size = 3 if action == "test" else 5
        sample_result = fetch_manifest_sample_data(entry, sample_size=sample_size)
        if sample_result.get("ok"):
            if action == "test":
                messages.success(
                    request,
                    f"Test ok for '{entry.key}': {sample_result.get('record_count', 0)} sample record(s) returned.",
                )
            else:
                messages.success(request, f"Loaded {sample_result.get('record_count', 0)} sample record(s).")
        else:
            if action == "test":
                messages.warning(request, f"Test failed for '{entry.key}'.")
            else:
                messages.warning(request, "Unable to load sample data for this manifest item.")

        if action == "test":
            return redirect(next_path or "gis:manifest-list")

    context = {
        "entry": entry,
        "default_fields_json_pretty": _pretty_json(entry.default_fields_json),
        "allowed_fields_json_pretty": _pretty_json(entry.allowed_fields_sample_json),
        "sample_result": sample_result,
        "sample_result_json_pretty": _pretty_json(sample_result) if sample_result is not None else "",
    }
    context.update(_page_meta(f"GIS Manifest {entry.key}"))
    return render(
        request,
        "gis/manifest_detail.html",
        context,
    )


def _pretty_json(value: object) -> str:
    try:
        if value is None:
            value = {}
        return json.dumps(value, indent=2, sort_keys=True)
    except TypeError:
        return json.dumps(str(value))


def _page_meta(title: str) -> dict[str, str]:
    return {
        "page_title": f"{title} · OpenSkagit",
        "meta_description": GIS_META_DESCRIPTION,
        "meta_robots": "noindex,nofollow",
        "og_url": "",
        "canonical_url": "",
        "og_description": GIS_META_DESCRIPTION,
        "twitter_description": GIS_META_DESCRIPTION,
    }


def _safe_next_path(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate.startswith("/"):
        return ""
    if candidate.startswith("//"):
        return ""
    return candidate


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _build_submission_layer_context(submission: GISSourceSubmission) -> dict[str, object]:
    discovered_layers = list(submission.discovered_layers.order_by("layer_name", "layer_id", "layer_url"))
    layer_urls = [layer.layer_url for layer in discovered_layers if layer.layer_url]
    manifest_by_layer_url = {
        entry.layer_url: entry
        for entry in GISLayerManifest.objects.filter(layer_url__in=layer_urls).only("id", "key", "label", "layer_url")
    }

    layer_rows = []
    for layer in discovered_layers:
        qualification = layer.qualification_results_json or {}
        metadata_section = qualification.get("metadata") or {}
        auto_approvable, auto_reasons = evaluate_layer_for_auto_approval(layer)
        layer_rows.append(
            {
                "obj": layer,
                "metadata_ok": bool(metadata_section.get("metadata_fetch_ok")),
                "auto_approvable": auto_approvable,
                "auto_reasons": auto_reasons,
                "manifest_entry": manifest_by_layer_url.get(layer.layer_url),
            }
        )

    auto_approvable_count = sum(1 for row in layer_rows if row["auto_approvable"])
    already_in_manifest_count = sum(1 for row in layer_rows if row["manifest_entry"] is not None)
    raw_summary = submission.raw_summary_json if isinstance(submission.raw_summary_json, dict) else {}
    progress = raw_summary.get("progress") if isinstance(raw_summary.get("progress"), dict) else {}
    return {
        "layer_rows": layer_rows,
        "auto_approvable_count": auto_approvable_count,
        "already_in_manifest_count": already_in_manifest_count,
        "inspection_progress": progress,
    }


def _build_manifest_list_context(raw_params) -> dict[str, object]:
    form = GISManifestFilterForm(raw_params or None)
    queryset = GISLayerManifest.objects.select_related("source_submission", "discovered_layer").order_by("category", "key")

    if form.is_valid():
        category = form.cleaned_data.get("category")
        source_org = form.cleaned_data.get("source_org")
        usability = form.cleaned_data.get("usability")
        status = form.cleaned_data.get("status")

        if category:
            queryset = queryset.filter(category=category)
        if source_org:
            queryset = queryset.filter(source_org__icontains=source_org)
        if usability:
            queryset = queryset.filter(usability=usability)
        if status:
            queryset = queryset.filter(status=status)

    return {"filter_form": form, "entries": queryset[:500]}


def _queue_submission_inspection(submission: GISSourceSubmission) -> None:
    submission.status = SOURCE_SUBMISSION_STATUS_INSPECTING
    submission.error_text = ""
    submission.save(update_fields=["status", "error_text"])
    if _start_submission_inspection_process(submission.pk):
        return
    Thread(target=_run_submission_inspection_background, args=(submission.pk,), daemon=True).start()


def _run_submission_inspection_background(submission_id: int) -> None:
    close_old_connections()
    try:
        submission = GISSourceSubmission.objects.get(pk=submission_id)
    except GISSourceSubmission.DoesNotExist:
        close_old_connections()
        return

    try:
        run_submission_inspection(submission)
    except Exception:
        logger.exception("Background GIS inspection failed for submission %s", submission_id)
    finally:
        close_old_connections()


def _start_submission_inspection_process(submission_id: int) -> bool:
    base_dir = Path(settings.BASE_DIR)
    manage_py = base_dir / "manage.py"
    cmd = [sys.executable, str(manage_py), "inspect_gis_submission", str(submission_id)]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        logger.exception("Unable to spawn inspect_gis_submission process for submission %s", submission_id)
        return False
