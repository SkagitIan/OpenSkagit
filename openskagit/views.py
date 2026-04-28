import base64
import copy
import csv
import datetime as dt
import functools
import json
import logging
import math
import os
import operator
import re
import statistics
import subprocess
import sys
import time
import uuid
from urllib.parse import urlencode
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from types import SimpleNamespace
import numpy as np
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.humanize.templatetags.humanize import intcomma
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from django.core import signing
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db import close_old_connections, connection
from django.db.models import Avg, Count, Max, Min, OuterRef, Q, Subquery, Case, When, FloatField, F, Value, Sum
from django.db.models.functions import Upper
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseGone, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.forms import inlineformset_factory
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from django.utils.formats import date_format
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_POST, require_http_methods
import httpx
try:
    import replicate
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    replicate = None


logger = logging.getLogger(__name__)

from . import activity_feed, adjustment_engine, appeals, cma, llm
from .neighborhood import get_neighborhood_snapshot
from .forms import (
    ContactSubmissionForm,
    StaffImageGeneratorForm,
    WeeklyBriefingSectionForm,
    WeeklyBriefingTemplateForm,
)
from .models import (
    CmaAnalysis,
    CmaComparableSelection,
    ContactSubmission,
    DorNaicsRecord,
    ExperimentRun,
    MasterParcel,
    NeighborhoodGeom,
    NeighborhoodMetrics,
    NeighborhoodTrend,
    Parcel,
    ParcelHistory,
    StaffImageGenerationJob,
    ParcelWaterfacts,
    Sales,
    SalesSearch,
    TaxingDistrictLevy,
    WeeklyBriefingSection,
    WeeklyBriefingSubscriber,
    WeeklyBriefingTemplate,
    WeeklyBriefingSendLog,
)
from planning.dossier import (
    PLANNING_DOSSIER_FIELDS,
    PLANNING_DOSSIER_WATER_FIELDS,
    build_planning_dossier_sections,
)
from openskagit.models import ParcelPlanningFacts
from .services.sedro_woolley_crawl import load_sw_dashboard_context
from .services.adjustment_support import build_adjustment_support_v1
from .services.comp_adjustment_quality import compute_adjustment_quality_metrics
from .services.sales_comps import diagnose_no_comp_path
from .services.sedro_woolley_map import load_sedro_woolley_zoning_feature_collection
from .services.sedro_woolley_portal import (
    empty_sedro_woolley_portal_context,
    load_sedro_woolley_portal_context,
)
from .services.tax_foreclosure_report import (
    TAX_STATUS_CONFIRMED_DELINQUENT,
    TAX_STATUS_NOT_DELINQUENT,
    TAX_STATUS_VERIFY_ERROR,
    run_tax_foreclosure_scan_and_verify,
)
from .valuation_areas import resolve_market_group
# from gastronet.flavor_signals import extract_flavor_signals  # Disabled: flavor cards not rendered on homepage
from gastronet.models import MenuItem, Restaurant, Review, SkagitDishIdea
from openskagit.regression_stats import load_regression_run, list_regression_runs
from .newsletter import preview_briefing_context, send_weekly_briefing

# Import predictor/interaction configs from the regression command.
try:
    from openskagit.management.commands import regression_masterparcel as regression_cmd

    PREDICTOR_PROFILES = regression_cmd.PREDICTOR_PROFILES
    INTERACTION_BUNDLES = regression_cmd.INTERACTION_BUNDLES
    REGRESSION_MODES = regression_cmd.REGRESSION_MODES
    CORE_PREDICTORS = regression_cmd.CORE_PREDICTORS
    CANDIDATE_PREDICTORS = regression_cmd.CANDIDATE_PREDICTORS
    INTERACTIONS = regression_cmd.INTERACTIONS
    TIER_INTERACTION_VARS = regression_cmd.TIER_INTERACTION_VARS
except Exception:
    # Safe fallback if import has side effects or fails.
    PREDICTOR_PROFILES = {"baseline": {}}
    INTERACTION_BUNDLES = {"standard": []}
    REGRESSION_MODES = {"sfr": "Single-family residential"}
    CORE_PREDICTORS = []
    CANDIDATE_PREDICTORS = []
    INTERACTIONS = {}
    TIER_INTERACTION_VARS = []


MCP_CUSTOM_GPT_URL = "https://chatgpt.com/g/g-6957dfe303648191ace4ab760c8c027a-skagitgpt"
FAVICON_PATH = Path(settings.BASE_DIR) / "static" / "favicon.svg"



@require_http_methods(["GET", "HEAD"])
def sitemap_xml(request):
    """
    Serve the pre-generated sitemap.xml so search engines can crawl portal endpoints.
    """
    sitemap_path = Path(settings.BASE_DIR) / "sitemap.xml"
    if not sitemap_path.exists():
        raise Http404("sitemap.xml not found.")
    return FileResponse(sitemap_path.open("rb"), content_type="application/xml")


@require_http_methods(["GET", "HEAD"])
def robots_txt(request):
    robots_lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap-xml'))}",
    ]
    return HttpResponse("\n".join(robots_lines) + "\n", content_type="text/plain; charset=utf-8")


@require_http_methods(["GET", "HEAD"])
def favicon_ico(request):
    if not FAVICON_PATH.exists():
        raise Http404("favicon not found.")
    return FileResponse(FAVICON_PATH.open("rb"), content_type="image/svg+xml")


DOR_LOCATION_LABEL_OVERRIDES = {
    2900: "Unincorporated Skagit County",
    2901: "Anacortes",
    2902: "Burlington",
    2903: "Concrete",
    2904: "Hamilton",
    2905: "La Conner",
    2906: "Lyman",
    2907: "Mount Vernon",
    2908: "Sedro-Woolley",
    2929: "Skagit County PTBA",
    2999: "Skagit County Total",
}

FLAVOR_IDENTITY_PATH = Path(settings.BASE_DIR) / "data" / "skagit_flavor_identity_v1.json"

CREATIVE_BIAS_BANDS = [
    {
        "label": "Classic Skagit",
        "max": 35,
        "prompt": "Keep dishes rooted in comfort-first carriers, gentle herb notes, and zero risky components.",
        "ui_helper": "Comfort-first, heritage carriers, no risks.",
    },
    {
        "label": "Balanced Familiar",
        "max": 70,
        "prompt": "Allow subtle herb, citrus, or textural lifts while the base stays recognizably Skagit.",
        "ui_helper": "Familiar core with a single bright accent.",
    },
    {
        "label": "Creative Push",
        "max": 100,
        "prompt": "Introduce a noticeable—but still approachable—twist via sauce, technique, or ingredient swap.",
        "ui_helper": "Invite a gentle twist with clear Skagit grounding.",
    },
]


@functools.lru_cache(maxsize=1)
def _load_skagit_flavor_identity_artifact() -> Dict[str, Any]:
    """Load the static Skagit flavor identity JSON artifact."""

    try:
        with FLAVOR_IDENTITY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        logger.error("Flavor identity artifact missing at %s", FLAVOR_IDENTITY_PATH)
    except json.JSONDecodeError:
        logger.exception("Flavor identity artifact could not be parsed as JSON")
    return {}


def _get_skagit_flavor_identity() -> Tuple[Dict[str, Any], str]:
    artifact = _load_skagit_flavor_identity_artifact()
    version = str(artifact.get("version") or "v1")
    payload = artifact.get("skagit_flavor_identity_v1")
    if not isinstance(payload, dict):
        return {}, version
    return payload, version


def _creative_band_for_value(value: int) -> Dict[str, Any]:
    clamped = max(0, min(100, int(value)))
    for band in CREATIVE_BIAS_BANDS:
        if clamped <= band["max"]:
            return band
    return CREATIVE_BIAS_BANDS[-1]


def _serialize_dish_entry(entry: SkagitDishIdea) -> Dict[str, Any]:
    payload = entry.payload if isinstance(entry.payload, dict) else {}
    label_source = entry.direction or payload.get("creative_profile") or payload.get("direction")
    if isinstance(label_source, str) and label_source.strip():
        label = label_source if " " in label_source else label_source.replace("-", " ").title()
    else:
        label = "Skagit Dish"
    return {
        "id": str(entry.id),
        "dish_name": payload.get("dish_name"),
        "description": payload.get("description"),
        "why_it_fits_skagit": payload.get("why_it_fits_skagit") or [],
        "ingredients": payload.get("ingredients") or [],
        "confidence_notes": payload.get("confidence_notes") or {},
        "direction": entry.direction,
        "direction_label": label,
        "direction_reported": payload.get("direction"),
        "generated_at": entry.created_at,
        "image_url": entry.image.url if entry.image else None,
    }


def _generate_and_store_dish_image(entry: SkagitDishIdea, prompt: Optional[str]) -> None:
    token = getattr(settings, "REPLICATE_API_KEY", None)
    if not token or not prompt or replicate is None:
        entry.image_prompt = prompt or ""
        entry.save(update_fields=["image_prompt"])
        return
    try:
        client = replicate.Client(api_token=token)
    except Exception:
        logger.warning("Unable to initialize Replicate client.")
        entry.image_prompt = prompt
        entry.save(update_fields=["image_prompt"])
        return

    try:
        output = client.run(
            "prunaai/flux-fast",
            input={
                "prompt": prompt,
                "num_outputs": 1,
                "width": 960,
                "height": 720,
            },
        )
    except Exception as exc:
        logger.warning("Replicate generation failed: %s", exc)
        entry.image_prompt = prompt
        entry.save(update_fields=["image_prompt"])
        return

    file_bytes = None
    ext = "png"
    first = output[0] if isinstance(output, (list, tuple)) and output else output
    if hasattr(first, "read"):
        try:
            file_bytes = first.read()
        except Exception:
            file_bytes = None
        name = getattr(first, "name", "")
        if isinstance(name, str) and "." in name:
            ext = name.split(".")[-1]
    elif isinstance(first, bytes):
        file_bytes = first
    elif isinstance(first, str):
        logger.warning("Replicate returned URL output; skipping download in restricted environment.")

    entry.image_prompt = prompt
    if file_bytes:
        filename = f"skagit_dishes/{entry.id}.{ext}"
        entry.image.save(filename, ContentFile(file_bytes), save=False)
        entry.save(update_fields=["image", "image_prompt"])
    else:
        entry.save(update_fields=["image_prompt"])


def _resolve_modal_image_function(
    modal_module: Any,
    app_name: str,
    function_name: str,
    client: Any,
    environment_name: Optional[str] = None,
) -> Any:
    errors: List[str] = []
    function_cls = getattr(modal_module, "Function", None)
    if function_cls is not None:
        for resolver_name in ("from_name", "lookup"):
            resolver = getattr(function_cls, resolver_name, None)
            if not callable(resolver):
                continue
            try:
                resolver_kwargs: Dict[str, Any] = {}
                if client is not None:
                    resolver_kwargs["client"] = client
                if environment_name:
                    resolver_kwargs["environment_name"] = environment_name

                if resolver_kwargs:
                    try:
                        return resolver(app_name, function_name, **resolver_kwargs)
                    except TypeError:
                        pass

                if environment_name:
                    try:
                        return resolver(app_name, function_name, environment_name=environment_name)
                    except TypeError:
                        pass

                return resolver(app_name, function_name)
            except Exception as exc:
                errors.append(f"{resolver_name}: {exc}")

    if client is not None:
        for resolver_name in ("lookup_function", "get_function"):
            resolver = getattr(client, resolver_name, None)
            if not callable(resolver):
                continue
            try:
                return resolver(app_name, function_name)
            except Exception as exc:
                errors.append(f"client.{resolver_name}: {exc}")

    detail = "; ".join(errors[:3])
    if detail:
        raise RuntimeError(
            f"Unable to resolve Modal function '{function_name}' in app '{app_name}'. {detail}"
        )
    raise RuntimeError(f"Unable to resolve Modal function '{function_name}' in app '{app_name}'.")


def _invoke_modal_image_function(
    modal_function: Any,
    *,
    prompt: str,
    init_image_payload: Optional[Any],
    steps: int,
    guidance_scale: float,
    width: int,
    height: int,
    seed: int,
) -> Any:
    remote = getattr(modal_function, "remote", None)
    if not callable(remote):
        raise RuntimeError("Modal function handle does not expose a callable .remote() method.")

    params = {
        "steps": steps,
        "guidance_scale": guidance_scale,
        "width": width,
        "height": height,
        "seed": seed,
    }
    call_variants = [
        {"prompt": prompt, "init_image_bytes": init_image_payload, **params},
        {"prompt": prompt, "init_image_bytes": init_image_payload, "params": params},
        {"prompt": prompt, "image_bytes": init_image_payload, **params},
    ]

    last_type_error: Optional[TypeError] = None
    for kwargs in call_variants:
        try:
            return remote(**kwargs)
        except TypeError as exc:
            last_type_error = exc
            continue

    raise RuntimeError(
        "Modal function signature mismatch. Expected prompt, optional init image bytes, and generation params."
    ) from last_type_error


def _coerce_modal_image_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, memoryview):
        return payload.tobytes()
    if isinstance(payload, (list, tuple)) and payload:
        return _coerce_modal_image_bytes(payload[0])
    if isinstance(payload, str):
        try:
            return base64.b64decode(payload, validate=True)
        except Exception as exc:
            raise RuntimeError("Modal returned a string payload that is not valid base64 image data.") from exc
    if isinstance(payload, dict):
        for key in ("image_bytes", "png_bytes", "result_bytes", "image_base64", "image"):
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, (bytes, bytearray, memoryview)):
                return bytes(value)
            if isinstance(value, str):
                try:
                    return base64.b64decode(value, validate=True)
                except Exception as exc:
                    raise RuntimeError(f"Modal returned invalid base64 data in '{key}'.") from exc
    raise RuntimeError("Modal function did not return generated image bytes.")


def _generate_image_via_modal(
    *,
    prompt: str,
    init_image_bytes: Optional[bytes],
    steps: int,
    guidance_scale: float,
    width: int,
    height: int,
    seed: int,
) -> bytes:
    try:
        import modal
    except ModuleNotFoundError as exc:
        raise RuntimeError("Modal client not installed. Add `modal` to dependencies and install it.") from exc

    modal_app_name = (getattr(settings, "MODAL_IMAGE_APP_NAME", "") or "flux-generator").strip()
    modal_function_name = (getattr(settings, "MODAL_IMAGE_FUNCTION_NAME", "") or "generate_image").strip()
    modal_class_name = (getattr(settings, "MODAL_IMAGE_CLASS_NAME", "") or "FluxGenerator").strip()
    init_image_encoding = (getattr(settings, "MODAL_IMAGE_INIT_IMAGE_ENCODING", "bytes") or "bytes").strip().lower()
    modal_environment_name = (
        getattr(settings, "MODAL_IMAGE_ENVIRONMENT_NAME", "") or os.getenv("MODAL_ENVIRONMENT", "")
    ).strip() or None
    modal_retry_count = max(0, int(getattr(settings, "MODAL_IMAGE_REMOTE_RETRY_COUNT", 1)))
    modal_retry_delay_seconds = max(
        0.0, float(getattr(settings, "MODAL_IMAGE_REMOTE_RETRY_DELAY_SECONDS", 1.5))
    )

    init_image_payload: Optional[Any] = init_image_bytes
    if init_image_bytes and init_image_encoding == "base64":
        init_image_payload = base64.b64encode(init_image_bytes).decode("ascii")

    def _is_retryable_modal_error(exc: Exception) -> bool:
        text = str(exc).lower()
        retry_tokens = (
            "deadline exceeded",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "unavailable",
            "connection reset",
            "internal error",
        )
        return any(token in text for token in retry_tokens)

    def _invoke_with_retry(modal_target: Any) -> Any:
        attempts = modal_retry_count + 1
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return _invoke_modal_image_function(
                    modal_target,
                    prompt=prompt,
                    init_image_payload=init_image_payload,
                    steps=steps,
                    guidance_scale=guidance_scale,
                    width=width,
                    height=height,
                    seed=seed,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts or not _is_retryable_modal_error(exc):
                    raise
                logger.warning(
                    "Retrying Modal image call after transient error (%s/%s): %s",
                    attempt,
                    attempts,
                    exc,
                )
                time.sleep(modal_retry_delay_seconds)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Modal image generation failed without an exception.")

    payload: Any = None
    class_lookup_error: Optional[Exception] = None

    # Primary path: deployed Modal app exposes class method FluxGenerator.generate_image.
    if modal_class_name:
        cls_cls = getattr(modal, "Cls", None)
        if cls_cls:
            try:
                cls_kwargs: Dict[str, Any] = {}
                if modal_environment_name:
                    cls_kwargs["environment_name"] = modal_environment_name
                modal_cls = cls_cls.from_name(modal_app_name, modal_class_name, **cls_kwargs)
                modal_instance = modal_cls()
                modal_method = getattr(modal_instance, modal_function_name, None)
                if modal_method is None:
                    raise RuntimeError(
                        f"Class '{modal_class_name}' does not define method '{modal_function_name}'."
                    )
                payload = _invoke_with_retry(modal_method)
            except Exception as exc:
                class_lookup_error = exc
                # If class exists and call reached runtime, do not fall back to top-level function.
                # Function fallback is only useful when lookup/method wiring is missing.
                if "does not define method" not in str(exc).lower() and "lookup failed" not in str(exc).lower():
                    raise RuntimeError(f"Modal class method call failed: {exc}") from exc

    if payload is not None:
        return _coerce_modal_image_bytes(payload)

    function_error: Optional[Exception] = None
    try:
        modal_function = _resolve_modal_image_function(
            modal_module=modal,
            app_name=modal_app_name,
            function_name=modal_function_name,
            client=None,
            environment_name=modal_environment_name,
        )
        payload = _invoke_with_retry(modal_function)
    except Exception as exc:
        function_error = exc
        if class_lookup_error is not None:
            raise RuntimeError(
                "Modal lookup failed for both class and function targets. "
                f"Class error: {class_lookup_error}; Function error: {function_error}"
            ) from exc
        raise RuntimeError(f"Modal function call failed: {function_error}") from exc

    return _coerce_modal_image_bytes(payload)


_staff_image_job_workers = max(1, int(getattr(settings, "MODAL_IMAGE_JOB_MAX_WORKERS", 1)))
_staff_image_job_executor = ThreadPoolExecutor(max_workers=_staff_image_job_workers)
_staff_image_poll_db_workers = max(1, int(getattr(settings, "MODAL_IMAGE_POLL_DB_WORKERS", 2)))
_staff_image_poll_db_timeout_seconds = max(
    1.0, float(getattr(settings, "MODAL_IMAGE_POLL_DB_TIMEOUT_SECONDS", 5.0))
)
_staff_image_poll_db_executor = ThreadPoolExecutor(max_workers=_staff_image_poll_db_workers)


def _run_staff_image_poll_db_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Execute polling-related ORM calls in a background thread to avoid gevent/async-context
    interference with Django's async safety checks.
    """

    def _runner() -> Any:
        close_old_connections()
        previous_flag = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        try:
            return fn(*args, **kwargs)
        finally:
            if previous_flag is None:
                os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
            else:
                os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous_flag
            close_old_connections()

    future = _staff_image_poll_db_executor.submit(_runner)
    return future.result(timeout=_staff_image_poll_db_timeout_seconds)


def _set_staff_image_job_cancelled(job: StaffImageGenerationJob, detail: str) -> None:
    now = timezone.now()
    job.status = StaffImageGenerationJob.STATUS_CANCELLED
    job.cancel_requested = True
    job.status_detail = detail
    if not job.completed_at:
        job.completed_at = now
    job.save(update_fields=["status", "cancel_requested", "status_detail", "completed_at", "updated_at"])


def _run_staff_image_generation_job(job_id: uuid.UUID) -> None:
    close_old_connections()
    init_image_name = ""
    init_image_storage = None
    job: Optional[StaffImageGenerationJob] = None

    try:
        try:
            job = StaffImageGenerationJob.objects.get(id=job_id)
        except StaffImageGenerationJob.DoesNotExist:
            return

        if job.cancel_requested or job.status == StaffImageGenerationJob.STATUS_CANCELLED:
            _set_staff_image_job_cancelled(job, "Generation cancelled before start.")
            return

        now = timezone.now()
        job.status = StaffImageGenerationJob.STATUS_RUNNING
        job.status_detail = "Running generation on Modal."
        job.started_at = job.started_at or now
        job.error_message = ""
        job.save(update_fields=["status", "status_detail", "started_at", "error_message", "updated_at"])

        init_image_bytes: Optional[bytes] = None
        if job.init_image:
            init_image_name = job.init_image.name
            init_image_storage = job.init_image.storage
            with job.init_image.open("rb") as uploaded_file:
                init_image_bytes = uploaded_file.read()

        job.refresh_from_db(fields=["cancel_requested", "status"])
        if job.cancel_requested or job.status == StaffImageGenerationJob.STATUS_CANCELLED:
            _set_staff_image_job_cancelled(job, "Generation cancelled.")
            return

        generated_image_bytes = _generate_image_via_modal(
            prompt=job.prompt,
            init_image_bytes=init_image_bytes,
            steps=job.steps,
            guidance_scale=job.guidance_scale,
            width=job.width,
            height=job.height,
            seed=job.seed,
        )

        job.refresh_from_db(fields=["cancel_requested", "status"])
        if job.cancel_requested or job.status == StaffImageGenerationJob.STATUS_CANCELLED:
            _set_staff_image_job_cancelled(job, "Generation cancelled.")
            return

        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        unique_suffix = uuid.uuid4().hex[:8]
        relative_path = f"generated_images/generated_{timestamp}_{unique_suffix}.png"
        saved_path = default_storage.save(relative_path, ContentFile(generated_image_bytes))

        completed_at = timezone.now()
        job.status = StaffImageGenerationJob.STATUS_SUCCEEDED
        job.status_detail = "Image generated successfully."
        job.result_image_path = saved_path
        job.error_message = ""
        job.completed_at = completed_at
        job.save(
            update_fields=[
                "status",
                "status_detail",
                "result_image_path",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )
    except Exception as exc:
        logger.exception("Staff image generation job %s failed: %s", job_id, exc)
        if job is not None:
            job.refresh_from_db(fields=["cancel_requested", "status"])
            if job.cancel_requested or job.status == StaffImageGenerationJob.STATUS_CANCELLED:
                _set_staff_image_job_cancelled(job, "Generation cancelled.")
            else:
                job.status = StaffImageGenerationJob.STATUS_FAILED
                job.status_detail = "Generation failed."
                job.error_message = str(exc).strip()[:4000] or exc.__class__.__name__
                job.completed_at = timezone.now()
                job.save(update_fields=["status", "status_detail", "error_message", "completed_at", "updated_at"])
    finally:
        if init_image_name and init_image_storage is not None:
            try:
                init_image_storage.delete(init_image_name)
            except Exception:
                logger.warning("Failed to clean up temp init image %s for job %s", init_image_name, job_id)
        if job is not None and job.init_image:
            StaffImageGenerationJob.objects.filter(id=job.id).update(init_image="")
        close_old_connections()


def _enqueue_staff_image_generation_job(job_id: uuid.UUID) -> None:
    _staff_image_job_executor.submit(_run_staff_image_generation_job, job_id)


def _serialize_form_errors(form: StaffImageGeneratorForm) -> Dict[str, List[str]]:
    payload: Dict[str, List[str]] = {}
    for field_name, field_errors in form.errors.items():
        payload[field_name] = [str(error) for error in field_errors]
    return payload


def _serialize_staff_image_job(job: StaffImageGenerationJob) -> Dict[str, Any]:
    is_terminal = job.is_terminal
    status_payload = {
        "id": str(job.id),
        "status": job.status,
        "status_detail": job.status_detail,
        "error_message": job.error_message,
        "cancel_requested": job.cancel_requested,
        "is_terminal": is_terminal,
        "can_cancel": not is_terminal,
        "result_image_url": job.result_image_url,
        "result_image_path": job.result_image_path,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    return status_payload


def _build_staff_image_job_token(job: StaffImageGenerationJob) -> str:
    payload = {
        "job_id": str(job.id),
        "user_id": job.created_by_id,
    }
    return signing.dumps(payload, salt="staff-image-job")


def _resolve_staff_image_job_from_token(job_id: uuid.UUID, token: str) -> Optional[StaffImageGenerationJob]:
    if not token:
        return None
    try:
        payload = signing.loads(token, salt="staff-image-job", max_age=60 * 60 * 24)
    except signing.BadSignature:
        return None
    except signing.SignatureExpired:
        return None

    token_job_id = str(payload.get("job_id") or "")
    token_user_id = payload.get("user_id")
    if token_job_id != str(job_id):
        return None

    try:
        job = StaffImageGenerationJob.objects.get(id=job_id)
    except StaffImageGenerationJob.DoesNotExist:
        return None
    if token_user_id != job.created_by_id:
        return None
    return job


def _cancel_staff_image_job_by_token(job_id: uuid.UUID, token: str) -> Optional[StaffImageGenerationJob]:
    job = _resolve_staff_image_job_from_token(job_id=job_id, token=token)
    if job is None:
        return None
    if job.is_terminal:
        return job

    job.cancel_requested = True
    if job.status == StaffImageGenerationJob.STATUS_PENDING:
        _set_staff_image_job_cancelled(job, "Generation cancelled before worker start.")
    else:
        job.status_detail = "Cancellation requested."
        job.save(update_fields=["cancel_requested", "status_detail", "updated_at"])
    job.refresh_from_db()
    return job


def _primary_nav_links():
    return [
        {"href": "/votevector/", "label": "VoteVector"},
        {"href": "/#tools", "label": "Tools"},
        {"href": "/#enrichments", "label": "Enrichments"},
        {"href": "/#model", "label": "Model"},
        {"href": "/#ai", "label": "AI"},
        {"href": "/#cta-briefing", "label": "Briefing"},
        {"href": "/survey/", "label": "Survey"},
        {"href": "/partner/", "label": "Partner"},
        {"href": "/about/", "label": "About"},
        {"href": "/contact/", "label": "Contact"},
    ]


CMA_SESSION_KEY = "cma_state"
CMA_ALLOWED_SORT_FIELDS = {
    "distance",
    "sale_price",
    "sale_date",
    "adjusted_price",  # legacy alias; treated as sale_price
    "score",
}
CMA_ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}

CONDITION_SCORE_MAP = {
    "P": 1,
    "POOR": 1,
    "F": 2,
    "FAIR": 2,
    "A": 3,
    "AVERAGE": 3,
    "G": 4,
    "GOOD": 4,
    "VG": 5,
    "VERY GOOD": 5,
    "E": 6,
    "EXCELLENT": 6,
}

QUALITY_LABEL_SCORE_MAP = {
    "low": 1,
    "fair": 2,
    "average": 3,
    "good": 4,
    "very good": 5,
    "excellent": 6,
}

QUALITY_WEIGHTS = {
    "MSL": 1,
    "MSF": 2,
    "MSA": 3,
    "MSG": 4,
    "MSVG": 5,
    "MSE": 6,
}

ADJUSTMENT_LABELS = [
    ("area", "Living area"),
    ("lot", "Lot size"),
    ("age", "Age"),
    ("quality", "Quality"),
    ("condition", "Condition"),
    ("garage", "Garage"),
    ("basement", "Basement"),
    ("view", "View"),
    ("time", "Time trend"),
]

SALES_SEARCH_ALLOWED_YEARS = {1, 3, 5, 10}
SALES_SEARCH_DEFAULT_YEARS = 3
SALES_SEARCH_DEFAULT_PAGE_SIZE = 50
SALES_SEARCH_MAX_PAGE_SIZE = 100
SALES_SEARCH_EXPORT_LIMIT = 5000
SALES_SEARCH_SORT_OPTIONS = [
    ("recent", "Sale date"),
    ("sale_price", "Sale price"),
    ("price_per_sqft", "Price per sqft"),
    ("price_per_acre", "Price per acre"),
    ("ratio", "Sale-to-market ratio"),
    ("living_area", "Living area"),
    ("lot_size", "Lot size"),
]

ADJUSTMENT_TOOLTIP_METADATA = {
    "area": {"unit": "sq ft", "decimals": 0},
    "lot": {"unit": "acres", "decimals": 2},
    "age": {"unit": "years", "decimals": 1},
    "quality": {"unit": "pts", "decimals": 1},
    "condition": {"unit": "pts", "decimals": 1},
    "garage": {"unit": None, "decimals": 0},
    "basement": {"unit": None, "decimals": 0},
    "view": {"unit": None, "decimals": 0},
    "time": {"unit": "months", "decimals": 1},
}

ADJUSTMENT_STORYBOARD_CONFIG = {
    "size": {
        "label": "Size adjustments",
        "components": ("area", "lot"),
        "formula": "subject_pred_price × (exp(coef × Δlog(size)) - 1)",
    },
    "quality": {
        "label": "Quality adjustments",
        "components": ("quality",),
        "formula": "subject_pred_price × (exp(coef × Δquality_score) - 1)",
    },
    "condition": {
        "label": "Condition adjustments",
        "components": ("condition",),
        "formula": "subject_pred_price × (exp(coef × Δcondition_score) - 1)",
    },
    "time": {
        "label": "Time adjustments",
        "components": ("time",),
        "formula": "sale_price × (exp(beta_t × Δmonths) - 1)",
    },
    "location": {
        "label": "Location adjustments",
        "components": ("view",),
        "formula": "subject_pred_price × (exp(coef × Δview_flag) - 1)",
    },
}

# Static descriptions of the predictors rendered on the methodology page.
FEATURE_EXPLANATIONS = [
    {
        "term": "log_area",
        "simple": "Living area",
        "explanation": (
            "We take the natural log of finished square footage so the model reads size as a percent change. "
            "It keeps very large homes from overpowering the fit while still rewarding extra space."
        ),
        "example": "Adding 400 sq ft to a 1,600 sq ft home does less than adding the same space to an 800 sq ft cottage.",
    },
    {
        "term": "log_age",
        "simple": "Effective age",
        "explanation": (
            "Older homes often sell at a discount, but the impact tapers as properties age. "
            "Using the logged age captures that quick drop-off after the first few decades."
        ),
        "example": "A house built in 1995 typically sees a much smaller age adjustment than one built in 1925.",
    },
    {
        "term": "quality_score",
        "simple": "Build quality",
        "explanation": (
            "Quality scores summarize materials, finishes, and workmanship. "
            "Higher scores usually translate to higher values even after controlling for size."
        ),
        "example": "Upgrading from builder grade cabinets to custom woodwork increases the quality score and value.",
    },
    {
        "term": "condition_score",
        "simple": "Condition",
        "explanation": (
            "Condition measures upkeep and recent renovations. "
            "Well-maintained homes sell closer to market benchmarks than deferred-maintenance properties."
        ),
        "example": "A roof replacement or systems update boosts the condition score and reduces downward adjustments.",
    },
    {
        "term": "t",
        "simple": "Time trend",
        "explanation": (
            "Monthly time steps keep the regression synced with market movement. "
            "They also prevent stale sales from skewing a hot market up or down."
        ),
        "example": "If the market rises 1% per month, the model applies that appreciation to earlier comparable sales.",
    },
    {
        "term": "land_share",
        "simple": "Land share",
        "explanation": (
            "This feature captures how much of the total value sits in the land component. "
            "It helps explain valuation bias between view lots and interior lots with similar homes."
        ),
        "example": "Waterfront parcels with modest structures have high land shares, so the model keeps them on-ratio.",
    },
    {
        "term": "has_garage",
        "simple": "Garage amenity",
        "explanation": (
            "Simple indicator variables such as garages, basements, or views still matter. "
            "They make sure basic amenities stay valued even in a model dominated by continuous variables."
        ),
        "example": "All else equal, attached two-car garages typically add several percentage points to value.",
    },
    {
        "term": "area_time",
        "simple": "Size × time interaction",
        "explanation": (
            "Interactions let us test if certain home types appreciate differently. "
            "Here we watch whether larger homes move faster or slower than the market average."
        ),
        "example": "During fast run-ups, large new construction may lead appreciation relative to small starter homes.",
    },
]

NEIGHBORHOOD_VALID_SALES_START = dt.date(2024, 5, 1)
NEIGHBORHOOD_VALID_SALES_END = dt.date(2025, 4, 30)
NEIGHBORHOOD_RESIDENTIAL_CODES = {
    "110",
    "111",
    "112",
    "113",
    "120",
    "130",
    "140",
    "180",
    "181",
    "182",
    "190",
    "910",
    "911",
    "912",
}
NEIGHBORHOOD_MIN_PRB_SAMPLES = 12
NEIGHBORHOOD_MIN_PRB_INSIDE_WINDOW = max(6, NEIGHBORHOOD_MIN_PRB_SAMPLES // 2)

ADJUSTMENT_STORYBOARD_ORDER = ["size", "quality", "condition", "time", "location"]

PARCEL_HISTORY_LIMIT = 24

APPEAL_COMPARABLE_SORT_FIELDS = {
    "similarity",
    "sale_price",
    "sale_date",
    "distance",
    "bedrooms",
    "bathrooms",
    "sqft",
    "year_built",
    "price_per_sqft",
}
APPEAL_COMPARABLE_SORT_OPTIONS: List[Dict[str, str]] = [
    {"value": "similarity", "label": "Similarity"},
    {"value": "sale_price", "label": "Sale Price"},
    {"value": "sale_date", "label": "Sale Date"},
    {"value": "distance", "label": "Distance"},
    {"value": "bedrooms", "label": "Beds"},
    {"value": "bathrooms", "label": "Baths"},
    {"value": "sqft", "label": "Sq Ft"},
    {"value": "year_built", "label": "Built"},
    {"value": "price_per_sqft", "label": "$/Sq Ft"},
]
APPEAL_COMPARABLE_SORT_DEFAULT_DIR = {
    "similarity": "desc",
    "sale_price": "desc",
    "sale_date": "desc",
    "distance": "asc",
    "bedrooms": "desc",
    "bathrooms": "desc",
    "sqft": "desc",
    "year_built": "desc",
    "price_per_sqft": "desc",
}
APPEAL_COMP_SESSION_KEY = "appeal_comp_state"
APPEAL_SAVED_COMP_LIMIT = 8
APPEAL_WORKSPACE_SORT_FIELDS = APPEAL_COMPARABLE_SORT_FIELDS | {"saved_order"}
APPEAL_WORKSPACE_SORT_OPTIONS: List[Dict[str, str]] = [
    {"value": "saved_order", "label": "Saved Order"},
    *APPEAL_COMPARABLE_SORT_OPTIONS,
]
APPEAL_WORKSPACE_SORT_DEFAULT_DIR = {
    **APPEAL_COMPARABLE_SORT_DEFAULT_DIR,
    "saved_order": "asc",
}
APPEAL_WORKSPACE_VIEWS = {"board", "map"}


def _normalize_parcel_token(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", "", str(value).strip()).upper()


def _normalize_saved_order(
    raw_saved_order: Any,
    *,
    allowed_ids: Optional[Set[str]] = None,
) -> List[str]:
    order: List[str] = []
    seen: Set[str] = set()
    if not isinstance(raw_saved_order, list):
        return order

    normalized_allowed = (
        {_normalize_parcel_token(parcel_id) for parcel_id in allowed_ids if _normalize_parcel_token(parcel_id)}
        if allowed_ids is not None
        else None
    )
    for value in raw_saved_order:
        parcel_id = _normalize_parcel_token(value)
        if not parcel_id or parcel_id in seen:
            continue
        if normalized_allowed is not None and parcel_id not in normalized_allowed:
            continue
        seen.add(parcel_id)
        order.append(parcel_id)
        if len(order) >= APPEAL_SAVED_COMP_LIMIT:
            break
    return order


def _get_appeal_comp_root_state(request) -> Dict[str, Any]:
    state = request.session.get(APPEAL_COMP_SESSION_KEY)
    if not isinstance(state, dict):
        state = {}
        request.session[APPEAL_COMP_SESSION_KEY] = state
        request.session.modified = True
    return state


def _get_appeal_comp_parcel_state(request, parcel_number: str) -> Dict[str, Any]:
    parcel_id = _normalize_parcel_token(parcel_number)
    state = _get_appeal_comp_root_state(request)
    parcel_state = state.get(parcel_id)
    if not isinstance(parcel_state, dict):
        parcel_state = {
            "pool": {},
            "pool_order": [],
            "saved_order": [],
            "updated_at": None,
        }
        state[parcel_id] = parcel_state
        request.session.modified = True
    return parcel_state


def _refresh_appeal_comp_pool(
    request,
    parcel_number: str,
    comps: Sequence[cma.ComparableResult],
) -> Dict[str, Any]:
    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool: Dict[str, Dict[str, Any]] = {}
    pool_order: List[str] = []
    for comp in comps:
        snapshot = getattr(comp, "snapshot", None)
        parcel_id = _normalize_parcel_token(getattr(snapshot, "parcel_number", None))
        if not parcel_id:
            continue
        pool[parcel_id] = appeals._comparable_payload(comp)
        pool_order.append(parcel_id)

    saved_order = _normalize_saved_order(parcel_state.get("saved_order"), allowed_ids=set(pool.keys()))
    parcel_state["pool"] = pool
    parcel_state["pool_order"] = pool_order
    parcel_state["saved_order"] = saved_order
    parcel_state["updated_at"] = timezone.now().isoformat()
    request.session.modified = True
    return parcel_state


def _cached_appeal_pool_comparables(
    request,
    parcel_number: str,
    *,
    display_limit: int,
) -> Optional[List[cma.ComparableResult]]:
    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool = parcel_state.get("pool")
    if not isinstance(pool, dict) or not pool:
        return None

    raw_order = parcel_state.get("pool_order")
    ordered_ids: List[str] = []
    seen: Set[str] = set()
    if isinstance(raw_order, list):
        for value in raw_order:
            parcel_id = _normalize_parcel_token(value)
            if not parcel_id or parcel_id in seen or parcel_id not in pool:
                continue
            seen.add(parcel_id)
            ordered_ids.append(parcel_id)
    for value in pool.keys():
        parcel_id = _normalize_parcel_token(value)
        if not parcel_id or parcel_id in seen:
            continue
        seen.add(parcel_id)
        ordered_ids.append(parcel_id)

    if len(ordered_ids) < display_limit:
        return None

    comps: List[cma.ComparableResult] = []
    for parcel_id in ordered_ids[:display_limit]:
        payload = pool.get(parcel_id)
        if not isinstance(payload, dict):
            return None
        try:
            comps.append(appeals._comparable_from_payload(payload))
        except Exception:
            logger.exception("Unable to hydrate cached comparable payload for parcel %s", parcel_id)
            return None
    return comps


def _get_appeal_saved_order(request, parcel_number: str) -> List[str]:
    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool = parcel_state.get("pool")
    allowed_ids = set(pool.keys()) if isinstance(pool, dict) else set()
    saved_order = _normalize_saved_order(parcel_state.get("saved_order"), allowed_ids=allowed_ids)
    if saved_order != parcel_state.get("saved_order"):
        parcel_state["saved_order"] = saved_order
        request.session.modified = True
    return saved_order


def _build_appeal_saved_rows(
    pool: Dict[str, Dict[str, Any]],
    saved_order: Sequence[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for parcel_id in saved_order:
        payload = pool.get(parcel_id) or {}
        snapshot = payload.get("snapshot") or {}
        sale_price = _safe_float_value(payload.get("sale_price"))
        sale_date_raw = payload.get("sale_date")
        sale_date: Optional[dt.date] = None
        if isinstance(sale_date_raw, dt.date):
            sale_date = sale_date_raw
        elif isinstance(sale_date_raw, str):
            try:
                sale_date = dt.date.fromisoformat(sale_date_raw)
            except ValueError:
                sale_date = None
        rows.append(
            {
                "parcel_number": parcel_id,
                "address": snapshot.get("address") or f"Parcel {parcel_id}",
                "sale_price": sale_price,
                "sale_date": sale_date,
            }
        )
    return rows


def _build_appeal_saved_tray_context(request, parcel_number: str) -> Dict[str, Any]:
    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool = parcel_state.get("pool")
    if not isinstance(pool, dict):
        pool = {}
        parcel_state["pool"] = pool
        request.session.modified = True
    saved_order = _get_appeal_saved_order(request, parcel_number)
    rows = _build_appeal_saved_rows(pool, saved_order)
    return {
        "parcel_number": parcel_number,
        "saved_rows": rows,
        "saved_count": len(rows),
        "saved_limit": APPEAL_SAVED_COMP_LIMIT,
        "saved_ids": [row["parcel_number"] for row in rows],
        "workspace_url": reverse("appeal-comp-workspace", args=[parcel_number]),
    }


def _render_appeal_saved_tray_html(request, parcel_number: str) -> str:
    return render_to_string(
        "openskagit/partials/appeal_saved_comp_tray.html",
        _build_appeal_saved_tray_context(request, parcel_number),
        request=request,
    )


def _centroid_lat_lon(geom) -> Tuple[Optional[float], Optional[float]]:
    """
    Derive a representative latitude/longitude pair from a parcel geometry.
    Fall back to the geometry's own x/y when no centroid is available.
    """
    if geom is None:
        return None, None
    centroid = getattr(geom, "centroid", None)
    if centroid is not None:
        return getattr(centroid, "y", None), getattr(centroid, "x", None)
    return getattr(geom, "y", None), getattr(geom, "x", None)


def _get_cma_root_state(request) -> Dict[str, Any]:
    state = request.session.get(CMA_SESSION_KEY)
    if not isinstance(state, dict):
        state = {}
        request.session[CMA_SESSION_KEY] = state
        request.session.modified = True
    return state


def _get_parcel_state(request, parcel_number: str) -> Dict[str, Any]:
    state = _get_cma_root_state(request)
    parcel_state = state.get(parcel_number)
    if not isinstance(parcel_state, dict):
        parcel_state = {
            "excluded": [],
            "sort_field": "score",
            "sort_direction": "desc",
        }
        state[parcel_number] = parcel_state
        request.session.modified = True
    return parcel_state


def _toggle_comparable_inclusion(request, parcel_number: str, comp_parcel: str) -> bool:
    parcel_state = _get_parcel_state(request, parcel_number)
    excluded = parcel_state.setdefault("excluded", [])
    if comp_parcel in excluded:
        excluded.remove(comp_parcel)
        request.session.modified = True
        return True
    excluded.append(comp_parcel)
    request.session.modified = True
    return False


def _current_sort(
    request, parcel_state: Dict[str, Any], requested_field: Optional[str], requested_direction: Optional[str]
):
    field = requested_field or parcel_state.get("sort_field") or "score"
    direction = requested_direction or parcel_state.get("sort_direction") or "desc"
    if field not in CMA_ALLOWED_SORT_FIELDS:
        field = "score"
    if direction not in CMA_ALLOWED_SORT_DIRECTIONS:
        direction = "desc"
    if parcel_state.get("sort_field") != field or parcel_state.get("sort_direction") != direction:
        parcel_state["sort_field"] = field
        parcel_state["sort_direction"] = direction
        request.session.modified = True
    return field, direction


def _parse_limit(raw_limit: Optional[str]) -> int:
    try:
        limit = int(raw_limit) if raw_limit is not None else cma.DEFAULT_COMPARABLE_LIMIT
    except (TypeError, ValueError):
        limit = cma.DEFAULT_COMPARABLE_LIMIT
    limit = max(6, limit)
    return min(limit, cma.MAX_COMPARABLE_LIMIT)


def _normalize_appeal_comp_sort(
    requested_field: Optional[str],
    requested_direction: Optional[str],
) -> Tuple[str, str]:
    field = str(requested_field or "similarity").strip().lower()
    if field not in APPEAL_COMPARABLE_SORT_FIELDS:
        field = "similarity"
    default_direction = APPEAL_COMPARABLE_SORT_DEFAULT_DIR.get(field, "desc")
    direction = str(requested_direction or default_direction).strip().lower()
    if direction not in {"asc", "desc"}:
        direction = default_direction
    return field, direction


def _normalize_workspace_comp_sort(
    requested_field: Optional[str],
    requested_direction: Optional[str],
) -> Tuple[str, str]:
    field = str(requested_field or "saved_order").strip().lower()
    if field not in APPEAL_WORKSPACE_SORT_FIELDS:
        field = "saved_order"
    default_direction = APPEAL_WORKSPACE_SORT_DEFAULT_DIR.get(field, "asc")
    direction = str(requested_direction or default_direction).strip().lower()
    if direction not in {"asc", "desc"}:
        direction = default_direction
    return field, direction


def _normalize_workspace_view(value: Optional[str]) -> str:
    view = str(value or "board").strip().lower()
    return view if view in APPEAL_WORKSPACE_VIEWS else "board"


def _parse_currency_value(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parcel_value_history(parcel_number: str, limit: int = PARCEL_HISTORY_LIMIT) -> List[Dict[str, Any]]:
    if not parcel_number:
        return []
    record = ParcelHistory.objects.only("rows").filter(parcel_number=parcel_number).first()
    if not record:
        return []
    raw_rows = record.rows or []
    entries: List[Dict[str, Any]] = []
    for row in raw_rows:
        year_text = row.get("VALUE YEAR") or row.get("TAX YEAR")
        try:
            year = int(year_text)
        except (TypeError, ValueError):
            continue
        value = None
        for key in ("MARKET TOTAL", "LAND MARKET", "ASSESSED TOTAL", "LAND ASSESSED"):
            value = _parse_currency_value(row.get(key))
            if value is not None:
                break
        if value is None:
            continue
        entries.append({"year": year, "value": value})
    if not entries:
        return []
    entries.sort(key=lambda item: item["year"])
    if len(entries) > limit:
        entries = entries[-limit:]
    return entries


def _safe_float_value(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_similarity(primary: Optional[float], secondary: Optional[float]) -> Optional[float]:
    if primary is None or secondary is None:
        return None
    if primary <= 0 or secondary <= 0:
        return None
    ratio = min(primary, secondary) / max(primary, secondary)
    return max(0.0, min(1.0, ratio))


def _match_text_score(subject_value: Any, comparable_value: Any) -> Optional[float]:
    if subject_value in (None, "", "null") or comparable_value in (None, "", "null"):
        return None
    subject_text = str(subject_value).strip().lower()
    comparable_text = str(comparable_value).strip().lower()
    if not subject_text or not comparable_text:
        return None
    return 1.0 if subject_text == comparable_text else 0.6


def _average_score(values: List[Optional[float]]) -> Optional[float]:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _percentage_score(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    percentage = round(value * 100)
    return max(0, min(100, percentage))


def _support_reason_labels(
    *,
    group_reasons: Sequence[str],
    quality_flags: Sequence[str],
    missing_bedrooms: bool,
    missing_bathrooms: bool,
    missing_living_area: bool,
    missing_year_built: bool,
) -> List[str]:
    reason_map = {
        "net_adjustment_above_primary_threshold": "Net adjustment exceeds primary threshold (>10%).",
        "gross_adjustment_above_primary_threshold": "Gross adjustment exceeds primary threshold (>15%).",
        "large_size_gap": "Large living-area gap versus subject.",
        "high_net_adjustment_pct": "High net adjustment (>=15% of sale price).",
        "high_gross_adjustment_pct": "High gross adjustment (>=25% of sale price).",
        "dominant_living_area_adjustment": "Living-area adjustment dominates total adjustment.",
        "dominant_age_adjustment": "Age adjustment dominates total adjustment.",
        "dominant_time_adjustment": "Time adjustment dominates total adjustment.",
        "dominant_lot_adjustment": "Lot-size adjustment dominates total adjustment.",
        "dominant_garage_adjustment": "Garage adjustment dominates total adjustment.",
    }

    labels: List[str] = []
    for reason in group_reasons or []:
        labels.append(reason_map.get(str(reason), str(reason).replace("_", " ")))
    for flag in quality_flags or []:
        labels.append(reason_map.get(str(flag), str(flag).replace("_", " ")))

    if missing_bedrooms:
        labels.append("Bedrooms missing from source data.")
    if missing_bathrooms:
        labels.append("Bathrooms missing from source data.")
    if missing_living_area:
        labels.append("Living area missing from source data.")
    if missing_year_built:
        labels.append("Year built missing from source data.")

    return list(dict.fromkeys(labels))


def _parse_iso_date_value(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _adjustment_support_valuation_date(
    subject: cma.PropertySnapshot,
    advanced_summary: Optional[Dict[str, Any]],
) -> dt.date:
    summary_date = _parse_iso_date_value(
        ((advanced_summary or {}).get("subject") or {}).get("valuation_date")
    )
    if summary_date:
        return summary_date
    metadata = _metadata_dict(subject)
    for key in ("valuation_date", "assessment_date"):
        candidate = metadata.get(key)
        if isinstance(candidate, dt.datetime):
            return candidate.date()
        if isinstance(candidate, dt.date):
            return candidate
    today = dt.date.today()
    return dt.date(today.year, 1, 1)


def _adjustment_support_subject_features(
    subject: cma.PropertySnapshot,
    valuation_date: dt.date,
) -> Dict[str, Optional[float]]:
    metadata = _metadata_dict(subject)
    gla = _safe_float_value(subject.living_area or metadata.get("calculated_square_footage"))

    year_raw = subject.effective_year_built or subject.year_built
    year_built: Optional[int] = None
    try:
        if year_raw is not None:
            year_built = int(float(year_raw))
    except (TypeError, ValueError):
        year_built = None

    effective_age = (
        float(max(valuation_date.year - year_built, 0))
        if year_built is not None and year_built > 0
        else None
    )

    garage_sqft = _safe_float_value(subject.garage_sqft)
    has_garage: Optional[float]
    if garage_sqft is not None:
        has_garage = 1.0 if garage_sqft > 0 else 0.0
    else:
        has_garage = 1.0 if bool(metadata.get("has_garage")) else 0.0

    acres = _safe_float_value(subject.acres or subject.lot_acres or metadata.get("lot_acres"))
    log_lot = math.log1p(acres) if acres is not None and acres >= 0 else None

    return {
        "gla": gla,
        "effective_age": effective_age,
        "has_garage": has_garage,
        "log_lot_acres": log_lot,
        "months_since_sale": 0.0,
    }


def _adjustment_support_comp_features(
    snapshot: Optional[cma.PropertySnapshot],
    sale_date: Optional[dt.date],
    valuation_date: dt.date,
) -> Dict[str, Optional[float]]:
    metadata = _metadata_dict(snapshot) if snapshot else {}
    living_area = getattr(snapshot, "living_area", None) if snapshot else None
    gla = _safe_float_value(living_area or metadata.get("calculated_square_footage"))

    year_raw = (
        getattr(snapshot, "effective_year_built", None)
        or getattr(snapshot, "year_built", None)
        or metadata.get("effective_year_built")
        or metadata.get("year_built")
    )
    year_built: Optional[int] = None
    try:
        if year_raw is not None:
            year_built = int(float(year_raw))
    except (TypeError, ValueError):
        year_built = None

    effective_age = (
        float(max(valuation_date.year - year_built, 0))
        if year_built is not None and year_built > 0
        else None
    )

    garage_sqft = _safe_float_value(getattr(snapshot, "garage_sqft", None) if snapshot else None)
    if garage_sqft is None:
        garage_sqft = _safe_float_value(
            metadata.get("garage_sqft")
            or metadata.get("final_garage_area")
            or metadata.get("total_garage_area")
        )
    has_garage = 1.0 if garage_sqft is not None and garage_sqft > 0 else 0.0

    acres = _safe_float_value(
        (getattr(snapshot, "acres", None) if snapshot else None)
        or (getattr(snapshot, "lot_acres", None) if snapshot else None)
        or metadata.get("lot_acres")
    )
    log_lot = math.log1p(acres) if acres is not None and acres >= 0 else None

    if isinstance(sale_date, dt.datetime):
        comp_sale_date = sale_date.date()
    else:
        comp_sale_date = sale_date
    months_since_sale = (
        max((valuation_date - comp_sale_date).days / 30.4375, 0.0)
        if isinstance(comp_sale_date, dt.date)
        else None
    )

    return {
        "gla": gla,
        "effective_age": effective_age,
        "has_garage": has_garage,
        "log_lot_acres": log_lot,
        "months_since_sale": months_since_sale,
    }


def _compute_comp_adjustment_payload(
    *,
    sale_price: Optional[float],
    subject_features: Dict[str, Optional[float]],
    comp_features: Dict[str, Optional[float]],
    coefficients: Dict[str, Any],
) -> Dict[str, Any]:
    if sale_price is None or sale_price <= 0:
        return {
            "available": False,
            "adjusted_price": None,
            "total_adjustment": None,
            "adjustment_by_key": {},
            "adjustments": [],
            "time_months_delta": None,
        }

    factor_map = [
        ("gla", "living_area", "Living Area", "sqft"),
        ("effective_age", "age", "Effective Age", "years"),
        ("has_garage", "garage", "Garage", ""),
        ("log_lot_acres", "lot", "Lot", ""),
        ("months_since_sale", "time", "Time", "months"),
    ]

    total_adjustment = 0.0
    adjustment_by_key: Dict[str, float] = {}
    adjustments: List[Dict[str, Any]] = []
    time_months_delta: Optional[float] = None

    for coeff_key, ui_key, label, unit in factor_map:
        beta = _safe_float_value(coefficients.get(coeff_key))
        subject_value = subject_features.get(coeff_key)
        comp_value = comp_features.get(coeff_key)
        if beta is None or subject_value is None or comp_value is None:
            continue
        delta = float(subject_value) - float(comp_value)
        amount = sale_price * (math.exp(beta * delta) - 1.0)
        if abs(amount) < 1.0:
            continue
        total_adjustment += amount
        adjustment_by_key[ui_key] = round(amount, 2)
        if ui_key == "time":
            time_months_delta = round(delta, 2)
        adjustments.append(
            {
                "key": ui_key,
                "label": label,
                "amount": round(amount, 2),
                "delta": round(delta, 2),
                "unit": unit,
            }
        )

    adjusted_price = sale_price + total_adjustment
    adjustments.sort(key=lambda item: abs(item["amount"]), reverse=True)

    return {
        "available": bool(adjustments),
        "adjusted_price": round(adjusted_price, 2) if adjustments else None,
        "total_adjustment": round(total_adjustment, 2) if adjustments else None,
        "adjustment_by_key": adjustment_by_key,
        "adjustments": adjustments,
        "time_months_delta": time_months_delta,
    }


def _adjustment_warning_explanation(warning: str) -> Optional[str]:
    if not warning:
        return None
    text = warning.strip()
    if "Initial model was unstable; retried with expanded time/geography context." in text:
        return (
            "The first model built from the tightest local sample was unstable, so the analysis widened "
            "the market context and re-fit before producing hints."
        )
    if text.startswith("Reduced variable set for stability:"):
        raw_vars = text.split(":", 1)[1].strip()
        variable_labels = {
            "gla": "living area",
            "effective_age": "effective age",
            "has_garage": "garage",
            "garage_spaces": "garage spaces",
            "months_since_sale": "time",
            "log_lot_size": "lot size",
            "lot_size": "lot size",
        }
        selected = []
        for token in [item.strip() for item in raw_vars.split(",") if item.strip()]:
            selected.append(variable_labels.get(token, token.replace("_", " ")))
        selected_text = ", ".join(selected) if selected else "the most stable variables"
        return (
            "Some variables were removed to reduce collinearity; this run kept "
            f"{selected_text} so coefficient signs and magnitudes stay defensible."
        )
    if "Coefficient stability check flagged substantial drift across split samples." in text:
        return (
            "Coefficients changed too much between earlier and later sales in the sample, which reduces "
            "confidence in raw adjustment precision."
        )
    if "Adjustment hints were suppressed because model quality/sanity checks did not pass." in text:
        return "The model did not meet minimum quality checks, so adjustments are hidden instead of forced."
    return None


def _decorate_adjustment_support_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    decorated = dict(summary or {})
    warnings_list = decorated.get("warnings") or []
    explanations = []
    for warning in warnings_list:
        explained = _adjustment_warning_explanation(str(warning))
        if explained:
            explanations.append(explained)
    decorated["warning_explanations"] = explanations
    trust_state = str(decorated.get("trust_state") or "").strip().lower()
    trust_labels = {"high": "High", "medium": "Medium", "low": "Low"}
    decorated["trust_state_label"] = trust_labels.get(trust_state, trust_state.title() if trust_state else "Unknown")
    return decorated


def _merge_request_params(request) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, value in request.GET.items():
        merged[key] = value
    if request.method == "POST":
        for key, value in request.POST.items():
            merged[key] = value
    return merged


def _metadata_dict(snapshot: cma.PropertySnapshot) -> Dict[str, Any]:
    metadata = snapshot.metadata
    if not isinstance(metadata, dict):
        return {}
    return metadata


def _quality_score(metadata: Dict[str, Any]) -> Optional[float]:
    improvements = metadata.get("improvements")
    if isinstance(improvements, dict):
        code = (improvements.get("quality_code") or "").strip().upper()
        if code:
            score = QUALITY_WEIGHTS.get(code)
            if score:
                return float(score)
        label = improvements.get("quality")
        if isinstance(label, str):
            score = QUALITY_LABEL_SCORE_MAP.get(label.strip().lower())
            if score:
                return float(score)
    raw = metadata.get("quality_score")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _condition_score(metadata: Dict[str, Any]) -> Optional[float]:
    improvements = metadata.get("improvements")
    code = None
    if isinstance(improvements, dict):
        code = improvements.get("condition_code")
    if not code:
        code = metadata.get("condition_code")
    if isinstance(code, str):
        normalized = code.strip().upper()
        score = CONDITION_SCORE_MAP.get(normalized)
        if score:
            return float(score)
    label = None
    if isinstance(improvements, dict):
        label = improvements.get("condition")
    if isinstance(label, str):
        score = CONDITION_SCORE_MAP.get(label.strip().upper())
        if score:
            return float(score)
    raw = metadata.get("condition_score")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _boolean_flag(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 0:
        return 1
    if numeric == 0:
        return 0
    return None


def _calculate_age(snapshot: cma.PropertySnapshot, reference_date: Optional[dt.date]) -> Optional[float]:
    year = snapshot.year_built or snapshot.effective_year_built
    if not year:
        return None
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return None
    if reference_date is None:
        reference_date = timezone.now().date()
    return max(reference_date.year - year_int, 0)


def _subject_predicted_price(subject: cma.PropertySnapshot, market_group: Optional[str]) -> Optional[float]:
    metadata = _metadata_dict(subject)
    candidate_keys = (
        "predicted_value",
        "subject_pred_price",
        "regression_predicted_value",
        "regression_market_value",
        "model_price",
    )
    for key in candidate_keys:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    if subject.assessed_value is not None:
        try:
            return float(subject.assessed_value)
        except (TypeError, ValueError):
            pass
    if subject.sale_price is not None:
        try:
            return float(subject.sale_price)
        except (TypeError, ValueError):
            pass
    if market_group:
        payload = _snapshot_adjustment_payload(subject, market_group=market_group)
        predicted = adjustment_engine.predict_price(payload, market_group=market_group)
        if predicted is not None:
            return predicted
    return None


def _subject_market_group(subject: cma.PropertySnapshot) -> Optional[str]:
    metadata = _metadata_dict(subject)
    candidates = (
        metadata.get("valuation_area"),
        metadata.get("market_group"),
        metadata.get("city_district"),
    )
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate).strip()
        if text:
            return text.upper()
    mapped = resolve_market_group(metadata.get("neighborhood_code"))
    if mapped:
        return mapped
    return None


def _has_basement(metadata: Dict[str, Any]) -> Optional[int]:
    if "has_basement" in metadata:
        return _boolean_flag(metadata.get("has_basement"))
    finished = metadata.get("finished_basement_sqft")
    unfinished = metadata.get("unfinished_basement_sqft")
    if finished not in (None, "", 0) or unfinished not in (None, "", 0):
        return 1
    return None


def _snapshot_adjustment_payload(
    snapshot: cma.PropertySnapshot,
    *,
    market_group: Optional[str] = None,
    include_sale_price: bool = False,
) -> Dict[str, Any]:
    metadata = _metadata_dict(snapshot)
    sale_date = snapshot.sale_date.isoformat() if snapshot.sale_date else None
    lot_acres_val: Optional[float] = None
    if snapshot.lot_acres is not None:
        try:
            lot_acres_val = float(snapshot.lot_acres)
        except (TypeError, ValueError):
            lot_acres_val = None
    if lot_acres_val is None:
        raw_lot = metadata.get("lot_acres")
        try:
            lot_acres_val = float(raw_lot) if raw_lot is not None else None
        except (TypeError, ValueError):
            lot_acres_val = None

    age_val = metadata.get("age")
    if age_val is None:
        age_val = _calculate_age(snapshot, snapshot.sale_date)

    has_garage_val = metadata.get("has_garage")
    if has_garage_val is None:
        has_garage_val = _boolean_flag(snapshot.garage_sqft)

    payload = {
        "GLA": float(snapshot.living_area) if snapshot.living_area is not None else None,
        "lot_acres": lot_acres_val,
        "age": age_val,
        "quality_score": _quality_score(metadata),
        "condition_score": _condition_score(metadata),
        "has_garage": has_garage_val,
        "has_basement": _has_basement(metadata),
        "is_view": _boolean_flag(metadata.get("has_view")),
        "sale_date": sale_date,
        "property_type": snapshot.property_type,
    }
    if market_group:
        payload["valuation_area"] = market_group
    if include_sale_price and snapshot.sale_price is not None:
        try:
            payload["sale_price"] = float(snapshot.sale_price)
        except (TypeError, ValueError):
            payload["sale_price"] = None
    return payload


def _comparable_adjustment_payload(comp: cma.ComparableResult) -> Optional[Dict[str, Any]]:
    snapshot = comp.snapshot
    base_payload = _snapshot_adjustment_payload(snapshot, include_sale_price=True)
    sale_price = base_payload.get("sale_price")
    if sale_price in (None, ""):
        return None
    base_payload["comp_id"] = snapshot.parcel_number
    return base_payload


def _format_measure_value(value: Any, decimals: int) -> Optional[str]:
    if value in (None, "", "null"):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    formatted = f"{numeric:,.{decimals}f}"
    if decimals == 0:
        formatted = formatted.split(".")[0]
    return formatted


def _signed_delta_text(delta: float, decimals: int) -> str:
    formatted = _format_measure_value(abs(delta), decimals)
    if formatted is None:
        formatted = f"{abs(delta):,.{decimals}f}"
        if decimals == 0:
            formatted = formatted.split(".")[0]
    if delta > 0:
        return f"+{formatted}"
    if delta < 0:
        return f"-{formatted}"
    return formatted


def _describe_numeric_delta(label: str, key: str, detail: Dict[str, Any]) -> str:
    config = ADJUSTMENT_TOOLTIP_METADATA.get(key, {})
    unit = config.get("unit")
    decimals = config.get("decimals", 0)
    delta = detail.get("delta")
    prefix = f"{label} difference"
    if delta is None:
        return f"{prefix} unavailable."
    if delta == 0:
        sentence = f"{prefix}: No difference detected."
    else:
        signed = _signed_delta_text(delta, decimals)
        direction = "Subject higher" if delta > 0 else "Comparable higher"
        sentence = (
            f"{prefix}: {signed}{f' {unit}' if unit else ''} ({direction})."
        )
    subject_value = _format_measure_value(detail.get("subject_value"), decimals)
    comp_value = _format_measure_value(detail.get("comp_value"), decimals)
    parts = []
    if subject_value:
        parts.append(f"Subject: {subject_value}{f' {unit}' if unit else ''}")
    if comp_value:
        parts.append(f"Comparable: {comp_value}{f' {unit}' if unit else ''}")
    if parts:
        sentence = f"{sentence} {'; '.join(parts)}"
    return sentence


def _describe_feature_delta(label: str, detail: Dict[str, Any]) -> str:
    subject_flag = detail.get("subject_value")
    comp_flag = detail.get("comp_value")
    if subject_flag is None and comp_flag is None:
        return f"{label} data unavailable."
    if subject_flag is not None and comp_flag is not None:
        subject_has = bool(subject_flag)
        comp_has = bool(comp_flag)
        if subject_has and not comp_has:
            return f"{label}: Subject has this feature while the comparable does not."
        if not subject_has and comp_has:
            return f"{label}: Comparable has this feature while the subject does not."
        if subject_has:
            return f"{label}: Both properties have this feature."
        return f"{label}: Neither property has this feature."
    if subject_flag is not None:
        return f"{label}: Subject {'has' if bool(subject_flag) else 'does not have'} this feature; comparable data missing."
    return f"{label}: Comparable {'has' if bool(comp_flag) else 'does not have'} this feature; subject data missing."


def _describe_time_delta(label: str, detail: Dict[str, Any]) -> str:
    prefix = f"{label} difference"
    stats = ADJUSTMENT_TOOLTIP_METADATA.get("time", {})
    decimals = stats.get("decimals", 1)
    unit = stats.get("unit", "months")
    delta = detail.get("delta")
    if delta is None:
        return f"{prefix} unavailable."
    signed = _signed_delta_text(delta, decimals)
    if delta > 0:
        direction = "Subject valuation date is later than the comparable sale."
    elif delta < 0:
        direction = "Subject valuation date is earlier than the comparable sale."
    else:
        direction = "Subject valuation date matches the comparable sale."
    sentence = f"{prefix}: {signed} {unit} ({direction})"
    subject_date = detail.get("subject_value")
    comp_date = detail.get("comp_value")
    dates = []
    if subject_date:
        dates.append(f"Subject: {subject_date}")
    if comp_date:
        dates.append(f"Comparable: {comp_date}")
    if dates:
        sentence = f"{sentence}. {'; '.join(dates)}"
    return sentence


def _adjustment_delta_description(
    key: str,
    label: str,
    detail: Optional[Dict[str, Any]],
) -> str:
    if not detail:
        return f"{label} difference unavailable."
    if key in {"garage", "basement", "view"}:
        return _describe_feature_delta(label, detail)
    if key == "time":
        return _describe_time_delta(label, detail)
    return _describe_numeric_delta(label, key, detail)


def _compute_adjustment_summary(
    subject: cma.PropertySnapshot,
    comparables: List[cma.ComparableResult],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    market_group = _subject_market_group(subject)
    if not market_group:
        return None, "Market/valuation group unavailable."
    subject_pred_price = _subject_predicted_price(subject, market_group)
    if subject_pred_price is None:
        return None, "Predicted subject price unavailable."
    comps_payload: List[Dict[str, Any]] = []
    for comp in comparables:
        payload = _comparable_adjustment_payload(comp)
        if payload:
            comps_payload.append(payload)
    if not comps_payload:
        return None, "Comparable sale pricing unavailable."
    subject_payload = _snapshot_adjustment_payload(subject, market_group=market_group)
    try:
        raw_payload = adjustment_engine.compute_adjustments(
            subject=subject_payload,
            comps=comps_payload,
            subject_pred_price=subject_pred_price,
            market_group=market_group,
        )
    except adjustment_engine.MissingCoefficientError as exc:
        return None, str(exc)
    except adjustment_engine.AdjustmentEngineError as exc:
        return None, str(exc)
    for comp in raw_payload.get("comparables", []):
        adjustments = comp.get("adjustments") or {}
        detail_list = []
        adjustment_details = comp.get("adjustment_details") or {}
        for key, label in ADJUSTMENT_LABELS:
            detail = adjustment_details.get(key)
            detail_list.append(
                {
                    "key": key,
                    "label": label,
                    "amount": adjustments.get(key, 0.0),
                    "delta_text": _adjustment_delta_description(key, label, detail),
                }
            )
        comp["adjustment_list"] = detail_list
    return raw_payload, None


def _load_neighborhood_sales_ratio_history(code: Optional[str], *, limit: int = 10) -> List[Dict[str, Any]]:
    if not code:
        return []
    normalized = str(code or "").strip()
    if not normalized:
        return []
    normalized_upper = normalized.upper()
    qs = (
        NeighborhoodMetrics.objects.filter(neighborhood_code__iexact=normalized_upper)
        .order_by("-year")
    )
    history = []
    for metric in qs[:limit]:
        history.append(
            {
                "year": metric.year,
                "sales_ratio": float(metric.sales_ratio) if metric.sales_ratio is not None else None,
                "median_ratio": float(metric.median_ratio) if metric.median_ratio is not None else None,
            }
        )
    return sorted(history, key=lambda item: item["year"])


def _normalize_hood_code(hood_id: Optional[str]) -> str:
    if not hood_id:
        return ""
    return str(hood_id).strip()


def _normalize_parcel_number(parcel: Optional[str]) -> str:
    if not parcel:
        return ""
    return str(parcel).strip()


def _collect_neighborhood_ratio_samples(hood_id: Optional[str]) -> List[Tuple[float, float]]:
    hood_code = _normalize_hood_code(hood_id)
    if not hood_code:
        return []
    normalized_hood = hood_code.upper()

    parcel_rows = list(
        MasterParcel.objects.filter(
            hood_code__iexact=normalized_hood,
            proptype__iexact="R",
            land_use_code__in=NEIGHBORHOOD_RESIDENTIAL_CODES,
            assessed_value__gt=0,
        ).values("parcel_number", "assessed_value")
    )
    if not parcel_rows:
        return []

    parcel_numbers = set()
    for entry in parcel_rows:
        raw_parcel = entry.get("parcel_number")
        if not raw_parcel:
            continue
        trimmed = _normalize_parcel_number(raw_parcel)
        if trimmed:
            parcel_numbers.add(trimmed)
        parcel_numbers.add(raw_parcel)
    parcel_numbers.discard("")
    if not parcel_numbers:
        return []

    sale_records = Sales.objects.filter(
        parcel_number__in=parcel_numbers,
        sale_type__iexact="VALID SALE",
        sale_price__gt=0,
        sale_date__range=(NEIGHBORHOOD_VALID_SALES_START, NEIGHBORHOOD_VALID_SALES_END),
    ).values_list("parcel_number", "sale_price")

    sales_map: Dict[str, List[float]] = {}
    for parcel, price in sale_records:
        cleaned = _normalize_parcel_number(parcel)
        if not cleaned or not price:
            continue
        sales_map.setdefault(cleaned, []).append(float(price))

    samples: List[Tuple[float, float]] = []
    for entry in parcel_rows:
        parcel = _normalize_parcel_number(entry.get("parcel_number"))
        if not parcel:
            continue
        assessed_value = entry.get("assessed_value")
        if assessed_value in (None, 0):
            continue
        for sale_price in sales_map.get(parcel, []):
            if sale_price <= 0:
                continue
            ratio = float(assessed_value) / sale_price
            if 0.25 <= ratio <= 2.5:
                samples.append((ratio, sale_price))
    return samples


def _estimate_prb_from_samples(samples: List[Tuple[float, float]]) -> Optional[float]:
    if len(samples) < NEIGHBORHOOD_MIN_PRB_SAMPLES:
        return None
    ratios = np.array([pair[0] for pair in samples], dtype=float)
    sale_prices = np.array([pair[1] for pair in samples], dtype=float)
    mask = np.isfinite(ratios) & np.isfinite(sale_prices) & (sale_prices > 0)
    if mask.sum() < NEIGHBORHOOD_MIN_PRB_SAMPLES:
        return None
    ratios = ratios[mask]
    sale_prices = sale_prices[mask]

    median_ratio = np.median(ratios)
    if median_ratio == 0:
        return None
    sale_median = np.median(sale_prices)
    if sale_median == 0:
        return None

    val_dev = np.log2(sale_prices / sale_median)
    y = (ratios / median_ratio) - 1.0

    q_low, q_high = np.percentile(sale_prices, [10, 90])
    window_mask = (sale_prices >= q_low) & (sale_prices <= q_high)
    if window_mask.sum() < NEIGHBORHOOD_MIN_PRB_INSIDE_WINDOW:
        return None

    X = np.vstack((np.ones(window_mask.sum()), val_dev[window_mask])).T
    y_window = y[window_mask]
    try:
        coef, *_ = np.linalg.lstsq(X, y_window, rcond=None)
    except Exception:
        return None

    if len(coef) < 2:
        return None
    prb_value = float(coef[1])
    if not np.isfinite(prb_value):
        return None
    return round(prb_value, 3)


def _load_neighborhood_fairness_data(hood_id: Optional[str]) -> Dict[str, Optional[float]]:
    fairness = {"cod": None, "prd": None, "sales_ratio": None, "prb": None}
    snapshot = get_neighborhood_snapshot(hood_id, year=2025)
    if not snapshot:
        snapshot = get_neighborhood_snapshot(hood_id)
    if snapshot:
        fairness["cod"] = snapshot.get("cod")
        fairness["prd"] = snapshot.get("prd")
        fairness["sales_ratio"] = snapshot.get("sales_ratio")
    fairness["prb"] = _estimate_prb_from_samples(_collect_neighborhood_ratio_samples(hood_id))
    return fairness


def _prepare_adjustment_storyboard(
    adjustment_payload: Dict[str, Any],
    subject: cma.PropertySnapshot,
    comparables: List[cma.ComparableResult],
) -> List[Dict[str, Any]]:
    story_items: List[Dict[str, Any]] = []
    market_group = _subject_market_group(subject)
    subject_payload = _snapshot_adjustment_payload(subject, market_group=market_group)
    comp_payloads: List[Dict[str, Any]] = []
    for comp in comparables:
        snapshot = getattr(comp, "snapshot", None)
        if not isinstance(snapshot, cma.PropertySnapshot):
            continue
        comp_payloads.append(_snapshot_adjustment_payload(snapshot))
    comp_count = len(comp_payloads)
    if comp_count == 0:
        return story_items

    def _average(field: str) -> Optional[float]:
        values = []
        for payload in comp_payloads:
            value = payload.get(field)
            if value in (None, "", "null"):
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not values:
            return None
        return sum(values) / len(values)

    def _format_sqft(value: Optional[float]) -> str:
        if value is None:
            return "data unavailable"
        try:
            rounded = int(round(value))
            return f"{rounded:,} sq ft"
        except Exception:
            return "data unavailable"

    def _format_acres(value: Optional[float]) -> str:
        if value is None:
            return "data unavailable"
        try:
            return f"{value:.2f} acres"
        except Exception:
            return "data unavailable"

    def _format_score(value: Optional[float]) -> str:
        if value is None:
            return "unreported"
        try:
            return f"{value:.1f}"
        except Exception:
            return "unreported"

    def _parse_date(value: Optional[str]) -> Optional[dt.date]:
        if not value:
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            try:
                return dt.date.fromisoformat(value.split("T")[0])
            except Exception:
                return None

    subject_area_text = _format_sqft(subject_payload.get("GLA"))
    subject_lot_text = _format_acres(subject_payload.get("lot_acres"))
    subject_quality_text = _format_score(subject_payload.get("quality_score"))
    subject_condition_text = _format_score(subject_payload.get("condition_score"))
    subject_view_flag = subject_payload.get("is_view")
    subject_view_text = (
        "has a view"
        if subject_view_flag == 1
        else "does not have a view"
        if subject_view_flag == 0
        else "view data unavailable"
    )

    comp_area_text = _format_sqft(_average("GLA"))
    comp_lot_text = _format_acres(_average("lot_acres"))
    comp_quality_text = _format_score(_average("quality_score"))
    comp_condition_text = _format_score(_average("condition_score"))

    view_flags = [payload.get("is_view") for payload in comp_payloads if payload.get("is_view") in (0, 1)]
    comp_view_percent = None
    if view_flags:
        comp_view_percent = (sum(view_flags) / len(view_flags)) * 100
    comp_view_text = (
        f"{round(comp_view_percent)}% of comparables" if comp_view_percent is not None else "view data unavailable"
    )

    subject_sale_date = _parse_date(subject_payload.get("sale_date"))
    if subject_sale_date:
        subject_date_text = subject_sale_date.strftime("%b %Y")
    else:
        subject_date_text = "valuation date"

    comp_sale_dates = sorted(
        [d for d in (_parse_date(payload.get("sale_date")) for payload in comp_payloads) if d is not None]
    )
    if comp_sale_dates:
        start = comp_sale_dates[0].strftime("%b %Y")
        end = comp_sale_dates[-1].strftime("%b %Y")
        sale_range_text = start if start == end else f"{start} – {end}"
    else:
        sale_range_text = "sale dates unavailable"

    detail_lines: Dict[str, List[str]] = {
        "size": [
            ADJUSTMENT_STORYBOARD_CONFIG["size"]["formula"],
            f"Source: Your home is {subject_area_text} on {subject_lot_text}; comparables average {comp_area_text} on {comp_lot_text}.",
        ],
        "quality": [
            ADJUSTMENT_STORYBOARD_CONFIG["quality"]["formula"],
            f"Source: Your quality score is {subject_quality_text} vs comparables averaging {comp_quality_text}.",
        ],
        "condition": [
            ADJUSTMENT_STORYBOARD_CONFIG["condition"]["formula"],
            f"Source: Your condition score is {subject_condition_text} vs comparables averaging {comp_condition_text}.",
        ],
        "time": [
            ADJUSTMENT_STORYBOARD_CONFIG["time"]["formula"],
            f"Source: Comps sold between {sale_range_text} trended to {subject_date_text}.",
        ],
        "location": [
            ADJUSTMENT_STORYBOARD_CONFIG["location"]["formula"],
            f"Source: Your property {subject_view_text}; {comp_view_text} reported the same view flag.",
        ],
    }

    for story_id in ADJUSTMENT_STORYBOARD_ORDER:
        config = ADJUSTMENT_STORYBOARD_CONFIG.get(story_id)
        if not config:
            continue
        amounts: List[float] = []
        for comp in adjustment_payload.get("comparables", []):
            total = 0.0
            for entry in comp.get("adjustment_list", []):
                if entry.get("key") in config["components"]:
                    amount = entry.get("amount")
                    if isinstance(amount, (int, float)):
                        total += float(amount)
            amounts.append(total)
        if not amounts:
            continue
        avg_amount = sum(amounts) / len(amounts)
        story_items.append(
            {
                "id": story_id,
                "label": config["label"],
                "amount": avg_amount,
                "details": detail_lines.get(story_id, []),
            }
        )
    return story_items


API_ENDPOINTS = [
    {
        "key": "parcel-detail",
        "name": "Parcel Detail",
        "method": "GET",
        "path": "/api/parcel/{parcel_number}/",
        "description": "Retrieve parcel details joined across assessor, land, improvements, and sales data.",
        "instructions": "Type in a parcel number when you need the full story for one property. The reply bundles values, building facts, land, and the five most recent verified sales so a teammate can speak to the parcel with confidence.",
        "use_case": "Show a rich fact sheet when someone clicks a parcel pin or a row in search results.",
        "parameters": [
            {
                "name": "parcel_number",
                "location": "path",
                "type": "string",
                "required": True,
                "description": "11-character parcel number such as P12345.",
            }
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/parcel/P12345/",
                "query": {},
            },
            indent=2,
        ),
        "sample": {
            "parcel_number": "P12345",
            "address": "101 Main St",
            "valuation": {"assessed": 475000, "market": 512000, "taxable": 460000},
            "structure": {"bedrooms": 3, "bathrooms": 2, "living_area_sqft": 1820, "year_built": 1997},
            "districts": {"city": "Mount Vernon", "school": "SD201", "fire": "F01"},
            "location": {"latitude": 48.42, "longitude": -122.31, "acres": 0.22},
            "land": {
                "total_acres": 0.22,
                "total_market_value": 120000,
                "segments": [{"land_type": "RESIDENTIAL", "market_value": 120000}],
            },
            "improvements": [{"improvement_id": 1, "description": "Single family residence", "improvement_value": 355000}],
            "sales": {
                "latest": {"sale_price": 450000, "sale_date": "2021-04-02"},
                "recent_valid": [{"sale_price": 450000, "sale_date": "2021-04-02"}],
                "total_records": 6,
            },
        },
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "sales-list",
        "name": "Sales Leaderboard",
        "method": "GET",
        "path": "/api/sales/",
        "description": "Return top valid sales with assessor, land, and improvement context. Override sort direction via `direction=asc|desc`.",
        "instructions": "Use this feed when you want to call out headline sales. Pick a sort option, tighten the filters (price, neighborhood, acreage), and the service will hand back the most noteworthy transfers first.",
        "use_case": "Populate a “Recent Movers” card on a dashboard or a report that highlights high-dollar closings.",
        "parameters": [
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Default 25, max 100."},
            {"name": "sort", "location": "query", "type": "string", "required": False, "description": "One of recent, sale_price, neighborhood, assessed_value, market_value, acres, year_built."},
            {"name": "direction", "location": "query", "type": "string", "required": False, "description": "asc or desc. Defaults to the sort's natural direction."},
            {"name": "neighborhood", "location": "query", "type": "string", "required": False, "description": "Exact neighborhood code filter."},
            {"name": "city", "location": "query", "type": "string", "required": False, "description": "City district filter."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Restrict to a single parcel number."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "Lower sale price bound."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "Upper sale price bound."},
            {"name": "start_date", "location": "query", "type": "ISO datetime", "required": False, "description": "Earliest sale_date to include."},
            {"name": "end_date", "location": "query", "type": "ISO datetime", "required": False, "description": "Latest sale_date to include."},
            {"name": "land_use_code", "location": "query", "type": "string", "required": False, "description": "Match a land use code."},
            {"name": "property_type", "location": "query", "type": "string", "required": False, "description": "Restrict to one assessor property type."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Lower acreage bound."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Upper acreage bound."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/sales/",
                "query": {
                    "sort": "sale_price",
                    "direction": "desc",
                    "limit": 5,
                    "min_sale_price": 450000,
                },
            },
            indent=2,
        ),
        "sample": {
            "count": 125,
            "limit": 10,
            "sort": {"field": "sale_price", "direction": "desc"},
            "results": [
                {
                    "parcel_number": "P67890",
                    "sale": {
                        "sale_id": 98765,
                        "account_number": "ACCT-12345",
                        "seller_name": "Doe Family Trust",
                        "buyer_name": "Skagit Holdings LLC",
                        "sale_price": 735000,
                        "sale_date": "2023-09-15T00:00:00",
                        "sale_type": "valid sale",
                        "recording_number": "2023-0901-1234",
                        "deed_type": "Warranty Deed",
                        "deed_date": "2023-09-10T00:00:00",
                        "revaluation_area": 12.0,
                        "excise_number": 456789.0,
                    },
                    "parcel": {
                        "address": "456 River Rd",
                        "neighborhood_code": "NE45",
                        "land_use_code": "11",
                        "property_type": "Single Family",
                        "city_district": "Mount Vernon",
                        "school_district": "SD201",
                        "fire_district": "F01",
                        "assessed_value": 690000,
                        "market_value": 710000,
                        "taxable_value": 685000,
                        "acres": 0.38,
                        "year_built": 2018,
                        "effective_year_built": 2019,
                        "bedrooms": 4,
                        "bathrooms": 3,
                        "living_area": 2650,
                    },
                    "land": {
                        "total_acres": 0.38,
                        "total_market_value": 210000,
                        "segments": [
                            {
                                "property_value_year": 2023,
                                "land_type": "RESIDENTIAL",
                                "size_acres": 0.38,
                                "size_square_feet": 16552,
                                "market_value": 210000,
                                "market_unit_price": 552000,
                                "land_segment_comment": "Cul-de-sac",
                            }
                        ],
                    },
                    "improvements": [
                        {
                            "improvement_id": 1,
                            "description": "Residence",
                            "building_style": "Two Story",
                            "condition_code": "Good",
                            "improvement_value": 500000,
                            "total_living_area": 2650,
                            "actual_year_built": 2018,
                            "effective_year_built": 2019,
                        }
                    ],
                }
            ],
        },
        "default_path_params": {},
        "default_querystring": "sort=sale_price&direction=desc&limit=10",
        "default_body": "",
    },
    {
        "key": "parcel-search",
        "name": "Parcel Search",
        "method": "GET",
        "path": "/api/search/",
        "description": "Filter parcels with pagination and value, year, sale price, and acreage constraints.",
        "instructions": "Lean on this search whenever someone is trying to browse for property. Mix-and-match address text, parcel IDs, pricing, acreage, and year built filters, then turn the page controls to keep scrolling.",
        "use_case": "Power the main search results grid or a “find similar homes” drawer with pagination.",
        "parameters": [
            {"name": "page", "location": "query", "type": "int", "required": False, "description": "1-based page index; defaults to 1."},
            {"name": "page_size", "location": "query", "type": "int", "required": False, "description": "Defaults to REST_FRAMEWORK PAGE_SIZE (25) and max 250."},
            {"name": "address", "location": "query", "type": "string", "required": False, "description": "Case-insensitive contains search."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Exact parcel number."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "Minimum assessed value."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "Maximum assessed value."},
            {"name": "district", "location": "query", "type": "string", "required": False, "description": "City district filter."},
            {"name": "min_year", "location": "query", "type": "int", "required": False, "description": "Oldest acceptable year_built."},
            {"name": "max_year", "location": "query", "type": "int", "required": False, "description": "Newest acceptable year_built."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Minimum acreage filter."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Maximum acreage filter."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "Minimum last sale price (if a sale exists)."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "Maximum last sale price (if a sale exists)."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/search/",
                "query": {
                    "address": "Main St",
                    "min_value": 350000,
                    "max_value": 750000,
                    "page": 1,
                    "page_size": 25,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "address=Main St&min_value=300000&max_value=700000",
        "default_body": "",
    },
    {
        "key": "parcel-summary",
        "name": "Parcel Summary",
        "method": "GET",
        "path": "/api/summary/",
        "description": "Aggregate parcel metrics suitable for dashboards and reporting.",
        "instructions": "Reach for this rollup when you want quick talking points: pick a grouping (city, school, fire, neighborhood, levy) and let the service total or average the values.",
        "use_case": "Build KPI cards like “Average assessed value by city” or “Top 10 neighborhoods by acreage value.”",
        "parameters": [
            {"name": "group_by", "location": "query", "type": "string", "required": True, "description": "Required. One of city_district, school_district, fire_district, neighborhood_code, levy_code."},
            {"name": "metric", "location": "query", "type": "string", "required": True, "description": "Required. One of avg_assessed_value, avg_market_value, total_assessed_value, parcel_count."},
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Number of rows to return (default 50, max 200)."},
            {"name": "address", "location": "query", "type": "string", "required": False, "description": "Optional filter identical to /api/search."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Optional filter identical to /api/search."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "district", "location": "query", "type": "string", "required": False, "description": "See /api/search filters."},
            {"name": "min_year", "location": "query", "type": "int", "required": False, "description": "See /api/search filters."},
            {"name": "max_year", "location": "query", "type": "int", "required": False, "description": "See /api/search filters."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/summary/",
                "query": {
                    "group_by": "city_district",
                    "metric": "avg_assessed_value",
                    "limit": 10,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "group_by=city_district&metric=avg_assessed_value",
        "default_body": "",
    },
    {
        "key": "semantic-search",
        "name": "Semantic Search",
        "method": "POST",
        "path": "/api/semantic_search/",
        "description": "Vector similarity search against parcel embeddings using MiniLM and pgvector.",
        "instructions": "Let teammates describe the dream property in plain language (for example “farmhouse with mountain view and 5 acres”). The service scores every embedding and returns the closest matches, or a reasonable fallback list if vectors are offline.",
        "use_case": "Offer a natural-language search box that surfaces “homes like this” suggestions.",
        "parameters": [
            {"name": "query", "location": "body", "type": "string", "required": True, "description": "Natural language description to embed."},
            {"name": "limit", "location": "body", "type": "int", "required": False, "description": "Max matches to return (default 10, max 50)."},
        ],
        "request_example": json.dumps(
            {
                "method": "POST",
                "url": "/api/semantic_search/",
                "body": {
                    "query": "modern farmhouse with a big lot and room for a shop",
                    "limit": 8,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "",
        "default_body": json.dumps({"query": "modern farmhouse with large lot"}, indent=2),
    },
    {
        "key": "parcel-nearby",
        "name": "Nearby Parcels",
        "method": "GET",
        "path": "/api/nearby/",
        "description": "Find nearby parcels using PostGIS ST_DWithin with optional acreage and value filters.",
        "instructions": "Drop a pin (lat/lon) and a comfortable walking radius to see which parcels surround that point. Layer on assessed value or acreage limits to keep the list manageable.",
        "use_case": "Drive a “near me” sidebar when exploring a parcel on the map.",
        "parameters": [
            {"name": "lat", "location": "query", "type": "number", "required": True, "description": "Latitude of the search center."},
            {"name": "lon", "location": "query", "type": "number", "required": True, "description": "Longitude of the search center."},
            {"name": "radius", "location": "query", "type": "number", "required": False, "description": "Radius in meters (defaults to 1000). Alias: radius_meters."},
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Max results (default 50, max 200)."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "Minimum assessed value."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "Maximum assessed value."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Minimum acreage."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Maximum acreage."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/nearby/",
                "query": {
                    "lat": 48.45,
                    "lon": -122.33,
                    "radius": 1500,
                    "min_value": 300000,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "lat=48.45&lon=-122.33&radius=2000",
        "default_body": "",
    },
    {
        "key": "neighborhood-stats",
        "name": "Neighborhood Stats",
        "method": "GET",
        "path": "/api/neighborhood_stats/{neighborhood_code}/",
        "description": "Return the latest snapshot for a neighborhood code (alias: /api/neighborhoods/{code}/).",
        "instructions": "Whenever a teammate wants quick neighborhood talking points, give them this snapshot. Provide the code (like NE045) and optionally the assessment year to pull the figures they care about.",
        "use_case": "Show a context card above parcel details describing the neighborhood’s average value and change rates.",
        "parameters": [
            {"name": "neighborhood_code", "location": "path", "type": "string", "required": True, "description": "Neighborhood code, e.g. NE045."},
            {"name": "year", "location": "query", "type": "int", "required": False, "description": "Optional assessment year override."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/neighborhood_stats/NE045/",
                "query": {
                    "year": 2024,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"neighborhood_code": "NE045"},
        "default_querystring": "year=2024",
        "default_body": "",
    },
    {
        "key": "appeal-analysis",
        "name": "Appeal Analysis",
        "method": "GET",
        "path": "/api/appeal_analysis/{parcel_number}/",
        "description": "Return a heuristic appeal likelihood rating for a parcel.",
        "instructions": "Before inviting someone to file an appeal, run this health check. It returns a 0–100 score, a friendly rating, and why we think that rating fits so staff can offer helpful guidance.",
        "use_case": "Gate the “Start appeal” CTA with a quick recommendation and talking points.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Parcel to analyze."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeal_analysis/P12345/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "appeal-search",
        "name": "Appeal Parcel Search",
        "method": "GET",
        "path": "/api/appeals/search/",
        "description": "Citizen-facing parcel/address search limited to residential property in the latest roll year.",
        "instructions": "Use this friendly search box as residents type their parcel or street. Once three characters have been entered, we return matching residential parcels from the active roll year.",
        "use_case": "Power the auto-complete field at the top of the appeal intake wizard.",
        "parameters": [
            {"name": "q", "location": "query", "type": "string", "required": True, "description": "Parcel number or address fragment (min length 3)."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/search/",
                "query": {
                    "q": "101 Main",
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "q=101 Main St",
        "default_body": "",
    },
    {
        "key": "appeal-subject",
        "name": "Appeal Subject Snapshot",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/subject/",
        "description": "Roll-aware property snapshot plus neighborhood context for the appeal wizard.",
        "instructions": "After the resident picks their parcel, call this endpoint to fill the sidebar with their valuation, home facts, and neighborhood averages. It keeps everyone aligned on the same baseline data.",
        "use_case": "Pre-fill the appeal form with the subject parcel’s assessor facts.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Appeal subject parcel."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/subject/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "appeal-comparables",
        "name": "Appeal Comparables",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/comparables/",
        "description": "Fetch cached comparable sales, appeal score, and soft-stop messages for a parcel.",
        "instructions": "Surface this data when a resident or staff member wants to review comps. You can ask for more comps by increasing the `count` value, and the response also shares why we think an appeal will or won’t succeed.",
        "use_case": "Fill the “Comparable Sales” tab in the appeal flow with ready-to-read cards.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Parcel requesting comparable set."},
            {"name": "count", "location": "query", "type": "int", "required": False, "description": "Target number of comparables. Defaults to the INITIAL_COMPARABLE_LIMIT and maxes at EXTENDED_COMPARABLE_LIMIT."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/comparables/",
                "query": {
                    "count": 7,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "count=7",
        "default_body": "",
    },
    {
        "key": "appeal-improvements",
        "name": "Comparable Improvements",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/comparables/{comp_parcel}/improvements/",
        "description": "Return improvement rollup details for a selected comparable parcel.",
        "instructions": "When someone expands a comparable card they usually want to see the nuts and bolts (square footage, style, year built). This endpoint hands those details back for the comparable you pass in.",
        "use_case": "Reveal the structure breakdown for a selected comp without loading the entire dataset again.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Appeal subject parcel."},
            {"name": "comp_parcel", "location": "path", "type": "string", "required": True, "description": "Comparable parcel id whose improvements are requested."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/comparables/P54321/improvements/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345", "comp_parcel": "P54321"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "youtube-meeting-jobs",
        "name": "YouTube Meeting Jobs",
        "method": "POST",
        "path": "/api/meetings/youtube/jobs/",
        "description": "Queue council meeting extraction from a YouTube URL. Returns a pollable job id immediately.",
        "instructions": "Staff-only endpoint for long-running meeting extraction. Submit the YouTube URL and poll the returned status URL until completion.",
        "use_case": "Drive asynchronous meeting intelligence pipelines and UI polling workflows.",
        "parameters": [
            {"name": "youtube_url", "location": "body", "type": "string", "required": True, "description": "YouTube watch URL, share URL, or video id."},
            {"name": "force", "location": "body", "type": "bool", "required": False, "description": "Force reprocessing even if a successful result already exists."},
            {"name": "meeting_context", "location": "body", "type": "object", "required": False, "description": "Optional context keys such as body_name and roll_call_hint."},
        ],
        "request_example": json.dumps(
            {
                "method": "POST",
                "url": "/api/meetings/youtube/jobs/",
                "body": {
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "force": False,
                    "meeting_context": {
                        "body_name": "Sedro-Woolley City Council",
                        "roll_call_hint": "Roll call happens in first 2-5 minutes",
                    },
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "",
        "default_body": json.dumps(
            {
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "force": False,
                "meeting_context": {
                    "body_name": "Sedro-Woolley City Council",
                    "roll_call_hint": "Roll call happens in first 2-5 minutes",
                },
            },
            indent=2,
        ),
    },
    {
        "key": "youtube-meeting-job-detail",
        "name": "YouTube Meeting Job Detail",
        "method": "GET",
        "path": "/api/meetings/youtube/jobs/{job_id}/",
        "description": "Poll one YouTube meeting analysis job for status, progress, and structured result JSON.",
        "instructions": "Use this after queueing a job. Poll until status is succeeded or failed.",
        "use_case": "Drive async progress UI and render extracted meeting details once completed.",
        "parameters": [
            {"name": "job_id", "location": "path", "type": "uuid", "required": True, "description": "Job UUID returned from the queue endpoint."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/meetings/youtube/jobs/11111111-1111-1111-1111-111111111111/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"job_id": "11111111-1111-1111-1111-111111111111"},
        "default_querystring": "",
        "default_body": "",
    },
]


API_PRESETS = [
    {
        "label": "Top 10 Recent Sales",
        "description": "Newest valid sales with parcel context.",
        "endpoint": "sales-list",
        "query": "limit=10&sort=recent",
        "body": "",
    },
    {
        "label": "City District Summary",
        "description": "Average assessed value grouped by district.",
        "endpoint": "parcel-summary",
        "query": "group_by=city_district&metric=avg_assessed_value",
        "body": "",
    },
    {
        "label": "High Value Residential Search",
        "description": "Parcels assessed between $700k and $1.2M mentioning 'St'.",
        "endpoint": "parcel-search",
        "query": "address=St&min_value=700000&max_value=1200000&page_size=25",
        "body": "",
    },
    {
        "label": "Burlington 2km Radius",
        "description": "Nearby parcels within 2km of downtown Burlington.",
        "endpoint": "parcel-nearby",
        "query": "lat=48.4736&lon=-122.3301&radius=2000",
        "body": "",
    },
    {
        "label": "Farmhouse Semantic",
        "description": "Semantic search for modern farmhouse with acreage.",
        "endpoint": "semantic-search",
        "query": "",
        "body": json.dumps({"query": "modern farmhouse with acreage and views"}, indent=2),
    },
]


TOP_SALES_LIMIT = 25
TOP_SALES_BASE_SQL = """
    SELECT
        s.parcel_number,
        s.sale_price,
        s.sale_date,
        s.buyer_name,
        s.seller_name,
        s.sale_type,
        s.recording_number,
        s.deed_type,
        s.excise_number,
        a.address,
        a.assessed_value,
        a.total_market_value,
        a.taxable_value,
        a.acres,
        a.bedrooms,
        a.bathrooms,
        a.living_area,
        a.year_built,
        a.eff_year_built
    FROM sales s
    JOIN assessor a ON a.parcel_number = s.parcel_number
    WHERE LOWER(TRIM(s.sale_type)) = 'valid sale'
      AND s.sale_price IS NOT NULL
      AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
"""


def _clean_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_measure(value: Any, suffix: str, *, decimals: int = 1, include_space: bool = True) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    num_float = float(number)
    if math.isclose(num_float, round(num_float), rel_tol=0, abs_tol=1e-4):
        display = str(int(round(num_float)))
    else:
        display = f"{num_float:.{decimals}f}".rstrip("0").rstrip(".")
    spacer = " " if include_space else ""
    return f"{display}{spacer}{suffix}"


def _format_living_area(value: Any) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    return f"{intcomma(int(round(number)))} sq ft"


def _format_sale_date(value: Any) -> str:
    if not value:
        return "Date pending"
    try:
        return f"Closed {date_format(value, 'M j, Y')}"
    except Exception:  # pragma: no cover - defensive
        return "Date pending"


def _format_identifier(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    number = _clean_decimal(value)
    if number is None:
        return str(value)
    if number == number.to_integral():
        return str(int(number))
    return str(number.normalize())


def _delta_metadata(sale_price: Optional[Decimal], assessed_value: Optional[Decimal]) -> Dict[str, Any]:
    if sale_price is None or assessed_value in (None, 0, Decimal("0")):
        return {"display": "—", "class": "text-slate-400", "value": None}
    try:
        diff = (sale_price - assessed_value) / assessed_value * Decimal("100")
    except (InvalidOperation, ZeroDivisionError):
        return {"display": "—", "class": "text-slate-400", "value": None}
    diff_float = float(diff)
    display = f"{diff_float:+.1f}%"
    if diff_float > 0:
        css = "text-emerald-600"
    elif diff_float < 0:
        css = "text-rose-600"
    else:
        css = "text-slate-500"
    return {"display": display, "class": css, "value": diff_float}


def _is_htmx(request) -> bool:
    return str(request.headers.get("HX-Request", "")).lower() == "true"


def _safe_median(values: Sequence[Any]) -> Optional[float]:
    filtered = [float(v) for v in values if v is not None]
    if not filtered:
        return None
    filtered.sort()
    mid = len(filtered) // 2
    if len(filtered) % 2:
        return filtered[mid]
    return (filtered[mid - 1] + filtered[mid]) / 2.0


def _safe_iqr(values: Sequence[Any]) -> Optional[float]:
    filtered = [float(v) for v in values if v is not None]
    n = len(filtered)
    if n < 4:
        return None
    filtered.sort()
    mid = n // 2
    if n % 2 == 0:
        lower = filtered[:mid]
        upper = filtered[mid:]
    else:
        lower = filtered[:mid]
        upper = filtered[mid + 1 :]
    q1 = _safe_median(lower)
    q3 = _safe_median(upper)
    if q1 is None or q3 is None:
        return None
    return q3 - q1


def _percent_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100.0


def _format_percent(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _annotate_sales_queryset(qs):
    return qs.annotate(
        price_per_sqft=Case(
            When(living_area__gt=0, then=F("sale_price") / F("living_area")),
            default=Value(None),
            output_field=FloatField(),
        ),
        price_per_acre=Case(
            When(lot_size_acres__gt=0, then=F("sale_price") / F("lot_size_acres")),
            default=Value(None),
            output_field=FloatField(),
        ),
    )


def _load_parcel_map(parcels: Sequence[str]) -> Dict[str, MasterParcel]:
    if not parcels:
        return {}
    return {
        parcel.parcel_number: parcel
        for parcel in MasterParcel.objects.filter(parcel_number__in=parcels)
        .select_related("parcelplanningfacts", "geometry")
    }


def _sale_story(sale: SalesSearch, parcel: Optional[MasterParcel], reference: Optional[Dict[str, Any]] = None) -> str:
    reference = reference or {}
    ratio = sale.sale_to_market_ratio
    if not sale.is_arms_length:
        return "Recorded as a non-arms-length transfer; useful for context but excluded from stats."
    if ratio is not None:
        if ratio >= 1.2:
            return f"Closed roughly {(ratio - 1) * 100:.0f}% above assessed value."
        if ratio <= 0.85:
            return f"Traded about {(1 - ratio) * 100:.0f}% below assessed value."

    median_ppsf = reference.get("median_ppsf")
    if median_ppsf and sale.price_per_sqft:
        delta = ((sale.price_per_sqft - median_ppsf) / median_ppsf) * 100
        if delta >= 30:
            return "Price per square foot significantly higher than other recent closings."
        if delta <= -30:
            return "Price per square foot well below nearby comparables."

    if parcel and sale.sale_date and parcel.final_year_built:
        if sale.sale_date.year - parcel.final_year_built <= 1:
            return "New construction premium within the last year."

    city = parcel.city_district if parcel else (sale.zoning_jurisdiction or "the county")
    return f"Typical sale for {city} consistent with current market levels."


def _build_sale_rows(
    sales: Sequence[SalesSearch],
    reference: Optional[Dict[str, Any]] = None,
    limit: int = 50,
    extra_notes: Optional[Dict[int, str]] = None,
):
    ordered = sorted(
        sales,
        key=lambda s: ((s.sale_date or dt.date(1900, 1, 1)), s.sale_id or 0),
        reverse=True,
    )
    subset = ordered[:limit]
    parcel_map = _load_parcel_map({s.parcel_number for s in subset})
    extra_notes = extra_notes or {}

    rows = []
    for sale in subset:
        parcel = parcel_map.get(sale.parcel_number)
        detail_url = None
        if getattr(sale, "sale_id", None):
            detail_url = reverse("sales-search-row", args=[sale.sale_id])

        rows.append(
            {
                "sale": sale,
                "parcel": parcel,
                "story": extra_notes.get(sale.sale_id) or _sale_story(sale, parcel, reference),
                "detail": {"mode": "htmx", "url": detail_url} if detail_url else None,
            }
        )
    return rows


def _comparable_story(subject: Optional[cma.PropertySnapshot], comp: cma.ComparableResult) -> str:
    parts: List[str] = []
    if comp.sale_date:
        parts.append(f"Closed {date_format(comp.sale_date, 'M j, Y')}")
    if comp.distance_miles is not None:
        parts.append(f"{float(comp.distance_miles):.1f} miles from subject")
    flags = comp.difference_flags or {}
    notable = [name for name, flagged in flags.items() if flagged]
    if notable:
        parts.append("differs on " + ", ".join(notable[:2]))
    if not parts:
        return "Nearby comparable sale supporting the estimate."
    return ". ".join(parts) + "."


def _build_comparable_rows(result: cma.ComputationResult, limit: int = 30):
    comparables = result.comparables[:limit]
    rows = []
    for comp in comparables:
        sale_price = float(comp.sale_price) if comp.sale_price is not None else None
        living_area = comp.snapshot.living_area or comp.snapshot.metadata.get("calculated_square_footage")
        ppsf = None
        if sale_price and living_area:
            try:
                ppsf = sale_price / float(living_area)
            except (TypeError, ValueError):
                ppsf = None
        sale = SimpleNamespace(
            sale_id=None,
            parcel_number=comp.snapshot.parcel_number,
            sale_date=comp.sale_date,
            sale_price=sale_price,
            sale_to_market_ratio=None,
            is_arms_length=True,
            price_per_sqft=ppsf,
            qa_flags=[],
            ratio_trim_bucket=None,
            zoning_jurisdiction=comp.snapshot.metadata.get("city_district"),
        )
        parcel = SimpleNamespace(
            situs_address=comp.snapshot.address,
            city_district=comp.snapshot.metadata.get("city_district"),
        )
        rows.append(
            {
                "sale": sale,
                "parcel": parcel,
                "story": _comparable_story(result.subject, comp),
                "detail": {
                    "mode": "link",
                    "url": reverse("cma-detail", args=[comp.snapshot.parcel_number]),
                },
            }
        )
    return rows


def _market_pulse_context() -> Dict[str, Any]:
    today = timezone.now().date()
    window_days = 90
    start = today - dt.timedelta(days=window_days)
    base_filters = {
        "sale_date__gte": start,
        "sale_date__lte": today,
        "is_arms_length": True,
        "exclude_from_analysis": False,
    }
    qs = SalesSearch.objects.filter(**base_filters)
    if qs.count() < 10:
        window_days = 180
        base_filters["sale_date__gte"] = today - dt.timedelta(days=window_days)
        qs = SalesSearch.objects.filter(**base_filters)

    annotated_qs = _annotate_sales_queryset(qs)
    sales = list(annotated_qs)
    if not sales:
        return {
            "headline": "No recent arms-length sales to report yet.",
            "mode_intro": "Market Pulse opens with the latest countywide signals and trims statistical outliers automatically.",
            "metrics": [],
            "secondary_metrics": [],
            "rows": [],
            "table_caption": "Sales data unavailable for this time window.",
            "why_text": "We filter to arms-length residential transfers to avoid noise.",
        }

    median_price = _safe_median([sale.sale_price for sale in sales])
    median_ppsf = _safe_median([sale.price_per_sqft for sale in sales if sale.price_per_sqft])
    sale_count = len(sales)
    price_iqr = _safe_iqr([sale.sale_price for sale in sales])

    prev_start = base_filters["sale_date__gte"] - dt.timedelta(days=window_days)
    prev_end = base_filters["sale_date__gte"] - dt.timedelta(days=1)
    prev_sales = list(
        _annotate_sales_queryset(
            SalesSearch.objects.filter(
                sale_date__gte=prev_start,
                sale_date__lte=prev_end,
                is_arms_length=True,
                exclude_from_analysis=False,
            )
        )
    )
    prev_median = _safe_median([sale.sale_price for sale in prev_sales])
    trend = _percent_change(median_price, prev_median)

    reference = {"median_ppsf": median_ppsf}
    rows = _build_sale_rows(sales, reference=reference)

    freshness = _safe_median([(today - (row["sale"].sale_date or today)).days for row in rows])
    new_builds = 0
    for row in rows:
        parcel = row["parcel"]
        sale = row["sale"]
        if parcel and parcel.final_year_built and sale.sale_date:
            if sale.sale_date.year - parcel.final_year_built <= 1:
                new_builds += 1
    new_share = (new_builds / len(rows) * 100.0) if rows else None

    if trend is not None and median_price is not None:
        direction = "up" if trend > 0 else "down"
        headline = f"Median arms-length price is {abs(trend):.1f}% {direction} over the last {window_days} days."
    elif median_price is not None:
        headline = f"Median arms-length sale price over the last {window_days} days is {_format_currency(median_price)}."
    else:
        headline = "Market Pulse is watching for the next verified sales."

    metrics = [
        {
            "label": "Median sale price",
            "value": _format_currency(median_price),
            "delta": _format_percent(trend),
            "caption": f"vs prior {window_days} days",
        },
        {
            "label": "Median $/sq ft",
            "value": f"${intcomma(int(round(median_ppsf)))}" if median_ppsf else "—",
            "caption": "Residential only",
        },
        {
            "label": "Sales count",
            "value": f"{sale_count:,}",
            "caption": f"Last {window_days} days",
        },
    ]

    secondary_metrics = [
        {"label": "Price IQR", "value": _format_currency(price_iqr), "caption": "Spread of the middle 50%"},
        {
            "label": "New construction",
            "value": f"{new_share:.1f}%" if new_share is not None else "—",
            "caption": "Share of recent closings",
        },
        {
            "label": "Median days since close",
            "value": f"{int(round(freshness))} days" if freshness is not None else "—",
            "caption": "Freshness of data",
        },
    ]

    return {
        "headline": headline,
        "mode_intro": "Market Pulse surfaces the most recent countywide signals automatically.",
        "metrics": metrics,
        "secondary_metrics": secondary_metrics,
        "rows": rows,
        "table_caption": f"Showing the {len(rows)} most recent arms-length residential sales backing this view.",
        "why_text": "We focus on arms-length residential transactions from the past few months and trim obvious outliers to keep the signal clean.",
    }


def _compare_place_context(raw_query: str) -> Dict[str, Any]:
    query = (raw_query or "").strip()
    today = timezone.now().date()
    window_days = 365
    start = today - dt.timedelta(days=window_days)
    base_filters = {
        "sale_date__gte": start,
        "sale_date__lte": today,
        "is_arms_length": True,
        "exclude_from_analysis": False,
    }

    context: Dict[str, Any] = {
        "compare_query": query,
        "mode_intro": "Compare a place to the county using a single search. We auto-select the area, timeframe, and property type.",
        "rows": [],
        "metrics": [],
        "secondary_metrics": [],
        "table_caption": "Enter an address, parcel, or city to see comparable sales.",
        "why_text": "We keep this mode lightweight: one input drives all assumptions.",
        "needs_query": not bool(query),
    }
    if not query:
        context["headline"] = "Pick an address, parcel, or city to compare."
        return context

    parcel = (
        MasterParcel.objects.filter(parcel_number__iexact=query).first()
        or MasterParcel.objects.filter(situs_address__icontains=query).first()
    )
    subject_snapshot: Optional[cma.PropertySnapshot] = None
    if parcel:
        try:
            subject_snapshot = cma.load_subject(parcel.parcel_number)
        except Exception as exc:
            logger.warning("Compare mode subject load failed for %s: %s", parcel.parcel_number, exc)
            subject_snapshot = None
    hood_code = None
    if parcel and getattr(parcel, "hood_code", None):
        hood_code = parcel.hood_code.strip()
    if not hood_code and subject_snapshot:
        meta = subject_snapshot.metadata if isinstance(subject_snapshot.metadata, dict) else {}
        hood_code = (meta.get("neighborhood_code") or meta.get("neighborhood"))
        if hood_code:
            hood_code = str(hood_code).strip()

    if parcel:
        city = parcel.city_district or parcel.hood_code or query
        assumption = f"Interpreting '{query}' via parcel {parcel.parcel_number} located in {city or 'this area'}"
        if hood_code:
            assumption += f" (neighborhood {hood_code})."
        else:
            assumption += "."
    else:
        city = query
        assumption = f"Interpreting '{query}' as a city or jurisdiction filter."

    if not city:
        context["headline"] = "We couldn't determine an area for that input."
        context["compare_error"] = "Try a city name, parcel number, or address."
        return context

    city_filter = city.replace("-", " ") if city else city
    if hood_code:
        parcel_subquery = MasterParcel.objects.filter(hood_code__iexact=hood_code).values("parcel_number")
        area_qs = SalesSearch.objects.filter(**base_filters, parcel_number__in=parcel_subquery)
    else:
        area_qs = SalesSearch.objects.filter(**base_filters, zoning_jurisdiction__icontains=city_filter)
    area_sales = list(_annotate_sales_queryset(area_qs))
    area_found = bool(area_sales)
    county_sales = list(_annotate_sales_queryset(SalesSearch.objects.filter(**base_filters)))
    prev_filters = {
        "sale_date__gte": start - dt.timedelta(days=window_days),
        "sale_date__lte": start - dt.timedelta(days=1),
        "is_arms_length": True,
        "exclude_from_analysis": False,
    }
    if hood_code:
        parcel_subquery = MasterParcel.objects.filter(hood_code__iexact=hood_code).values("parcel_number")
        prev_qs = SalesSearch.objects.filter(**prev_filters, parcel_number__in=parcel_subquery)
    else:
        prev_qs = SalesSearch.objects.filter(**prev_filters, zoning_jurisdiction__icontains=city_filter)
    prev_area_sales = list(_annotate_sales_queryset(prev_qs))

    median_area = _safe_median([sale.sale_price for sale in area_sales])
    median_county = _safe_median([sale.sale_price for sale in county_sales])
    area_ppsf = _safe_median([sale.price_per_sqft for sale in area_sales if sale.price_per_sqft])
    county_ppsf = _safe_median([sale.price_per_sqft for sale in county_sales if sale.price_per_sqft])
    delta_county = _percent_change(median_area, median_county)
    delta_prior = _percent_change(median_area, _safe_median([sale.sale_price for sale in prev_area_sales]))

    if hood_code:
        parcel_count = MasterParcel.objects.filter(hood_code__iexact=hood_code).count()
    else:
        parcel_count = MasterParcel.objects.filter(city_district__icontains=city_filter).count()
    market_depth = (len(area_sales) / parcel_count * 1000) if parcel_count else None
    volatility = None
    area_iqr = _safe_iqr([sale.sale_price for sale in area_sales])
    if area_iqr and median_area:
        volatility = (area_iqr / median_area) * 100

    reference = {"median_ppsf": area_ppsf}
    rows = _build_sale_rows(area_sales, reference=reference)
    comparable_rows = []
    if subject_snapshot:
        try:
            comp_result = cma.build_comparables(subject_snapshot, limit=40)
            if comp_result and comp_result.comparables:
                comparable_rows = _build_comparable_rows(comp_result)
        except Exception as exc:
            logger.warning("Comparable build failed for %s: %s", subject_snapshot.parcel_number, exc)

    using_comparables = False
    if comparable_rows:
        rows = comparable_rows
        using_comparables = True

    if delta_county is not None and median_area is not None:
        direction = "above" if delta_county > 0 else "below"
        headline = f"{city} median price is {abs(delta_county):.1f}% {direction} the county baseline."
    elif median_area is not None:
        headline = f"{city} median price over the last year is {_format_currency(median_area)}."
    else:
        headline = f"We compared {city} but need more transactions."

    metrics = [
        {
            "label": f"{city} median price",
            "value": _format_currency(median_area),
            "delta": _format_percent(delta_county),
            "caption": "vs county",
        },
        {
            "label": "Median $/sq ft",
            "value": f"${intcomma(int(round(area_ppsf)))}" if area_ppsf else "—",
            "caption": "vs county",
            "delta": _format_percent(_percent_change(area_ppsf, county_ppsf)),
        },
        {
            "label": "Sales volume",
            "value": f"{len(area_sales):,}",
            "caption": "Last 12 months",
            "delta": _format_percent(delta_prior),
        },
    ]

    secondary_metrics = [
        {
            "label": "Market depth",
            "value": f"{market_depth:.1f} per 1k parcels" if market_depth else "—",
            "caption": "Sales relative to housing stock",
        },
        {
            "label": "Volatility",
            "value": f"{volatility:.1f}%" if volatility is not None else "—",
            "caption": "Price spread vs median",
        },
    ]

    context.update(
        {
            "headline": headline,
            "metrics": metrics,
            "secondary_metrics": secondary_metrics,
            "rows": rows,
            "table_caption": (
                f"Comparable sales near parcel {subject_snapshot.parcel_number}."
                if using_comparables and subject_snapshot
                else f"Recent sales informing the comparison for {city}."
            ),
            "why_text": "We auto-selected time window, property type, and nearby comparables based on your input.",
            "compare_assumption": assumption,
            "compare_subject": subject_snapshot,
            "needs_query": False,
        }
    )
    if not area_found and not using_comparables:
        context["headline"] = f"No recent sales found for '{city}'."
        context["compare_error"] = "Try a nearby city or parcel."
    return context


def _signals_mode_context() -> Dict[str, Any]:
    today = timezone.now().date()
    start = today - dt.timedelta(days=730)
    qs = SalesSearch.objects.filter(sale_date__gte=start)
    sales = list(_annotate_sales_queryset(qs))
    if not sales:
        return {
            "headline": "No historical sales to analyze yet.",
            "mode_intro": "Outliers & Signals shows the weird stuff: suspicious ratios, unusual $/sqft, family transfers, and more.",
            "metrics": [],
            "secondary_metrics": [],
            "rows": [],
            "table_caption": "No anomalies detected.",
            "why_text": "We look at the last two years of sales and surface the ones that defy the pattern.",
        }

    median_price = _safe_median([sale.sale_price for sale in sales])
    median_ppsf = _safe_median([sale.price_per_sqft for sale in sales if sale.price_per_sqft])

    reason_map: Dict[int, str] = {}
    score_rows: List[Tuple[float, SalesSearch]] = []
    for sale in sales:
        reasons: List[str] = []
        score = 0.0
        ratio = sale.sale_to_market_ratio
        if ratio is not None and (ratio <= 0.6 or ratio >= 1.4):
            direction = "high" if ratio > 1 else "low"
            reasons.append(f"Sale ratio {direction} at {ratio:.2f}× assessed.")
            score += abs(ratio - 1)
        if sale.price_per_sqft and median_ppsf:
            delta_pct = ((sale.price_per_sqft - median_ppsf) / median_ppsf) * 100
            if delta_pct >= 60:
                reasons.append(f"$/sq ft about {delta_pct:.0f}% above the county median.")
                score += delta_pct / 100
            elif delta_pct <= -60:
                reasons.append(f"$/sq ft roughly {abs(delta_pct):.0f}% below peers.")
                score += abs(delta_pct) / 100
        if sale.exclude_from_analysis:
            reasons.append("Flagged for exclusion in regression prep.")
            score += 0.5
        if sale.qa_flags:
            reasons.append("QA flags: " + ", ".join(sale.qa_flags[:2]))
            score += 0.3
        if not sale.is_arms_length:
            reasons.append("Recorded as non-arms-length.")
            score += 0.2
        if reasons:
            reason_map[sale.sale_id] = " ".join(reasons)
            score_rows.append((score, sale))

    score_rows.sort(key=lambda item: (item[0], item[1].sale_date or dt.date(1900, 1, 1)), reverse=True)
    flagged_sales = [sale for _, sale in score_rows]
    rows = _build_sale_rows(flagged_sales, reference={"median_ppsf": median_ppsf}, extra_notes=reason_map)

    flagged_count = len(flagged_sales)
    share = (flagged_count / len(sales) * 100.0) if sales else 0.0
    median_flag_score = _safe_median([score for score, _ in score_rows])

    metrics = [
        {"label": "Flagged sales", "value": f"{flagged_count}", "caption": f"{share:.1f}% of last {len(sales)} transfers"},
        {
            "label": "Median anomaly score",
            "value": f"{median_flag_score:.2f}" if median_flag_score is not None else "—",
            "caption": "Higher = weirder",
        },
        {"label": "Median price baseline", "value": _format_currency(median_price), "caption": "For reference"},
    ]

    return {
        "headline": f"{flagged_count} unusual sales detected in the last two years.",
        "mode_intro": "Outliers & Signals highlights anomalies — the ones people talk about.",
        "metrics": metrics,
        "secondary_metrics": [],
        "rows": rows[:50],
        "table_caption": "Top unusual transfers ranked by how far they deviate from the norm.",
        "why_text": "We analyze sale ratios, price-per-square-foot, QA flags, and exclusion markers to surface noteworthy transfers.",
    }


def _parse_int_param(value: Any, *, default: Optional[int] = None, minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _parse_float_param(value: Any, *, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_param(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() not in {"0", "false", "off", "no"}


def _build_sales_search_queryset(request):
    """
    Build a filtered, annotated queryset for SalesSearch along with filter metadata.
    """
    qs = SalesSearch.objects.all()
    today = dt.date.today()

    years_param = _parse_int_param(request.GET.get("years"))
    start_date = parse_date(request.GET.get("start_date")) if request.GET.get("start_date") else None
    end_date = parse_date(request.GET.get("end_date")) if request.GET.get("end_date") else None

    if years_param in SALES_SEARCH_ALLOWED_YEARS:
        start_date = today - dt.timedelta(days=years_param * 365)
    if start_date is None:
        start_date = today - dt.timedelta(days=SALES_SEARCH_DEFAULT_YEARS * 365)
    if end_date is None:
        end_date = today
    if start_date and end_date and start_date > end_date:
        start_date = end_date

    qs = qs.filter(sale_date__gte=start_date, sale_date__lte=end_date)

    min_price = _parse_float_param(request.GET.get("min_price"))
    max_price = _parse_float_param(request.GET.get("max_price"))
    if min_price is not None:
        qs = qs.filter(sale_price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(sale_price__lte=max_price)

    min_living_area = _parse_float_param(request.GET.get("min_living_area"))
    max_living_area = _parse_float_param(request.GET.get("max_living_area"))
    if min_living_area is not None:
        qs = qs.filter(living_area__gte=min_living_area)
    if max_living_area is not None:
        qs = qs.filter(living_area__lte=max_living_area)

    min_lot_acres = _parse_float_param(request.GET.get("min_lot_acres"))
    max_lot_acres = _parse_float_param(request.GET.get("max_lot_acres"))
    if min_lot_acres is not None:
        qs = qs.filter(lot_size_acres__gte=min_lot_acres)
    if max_lot_acres is not None:
        qs = qs.filter(lot_size_acres__lte=max_lot_acres)

    city = (request.GET.get("city") or "").strip()
    if city:
        qs = qs.filter(zoning_jurisdiction__iexact=city)

    parcel_number = (request.GET.get("parcel_number") or "").strip()
    if parcel_number:
        qs = qs.filter(parcel_number__icontains=parcel_number)

    arms_length_only = _bool_param(request.GET.get("arms_length_only"), default=True)
    if arms_length_only:
        qs = qs.filter(is_arms_length=True)

    exclude_outliers = _bool_param(request.GET.get("exclude_outliers"), default=True)
    if exclude_outliers:
        qs = qs.filter(exclude_from_analysis=False)

    qs = qs.annotate(
        price_per_sqft=Case(
            When(living_area__gt=0, then=F("sale_price") / F("living_area")),
            default=Value(None),
            output_field=FloatField(),
        ),
        price_per_acre=Case(
            When(lot_size_acres__gt=0, then=F("sale_price") / F("lot_size_acres")),
            default=Value(None),
            output_field=FloatField(),
        ),
    )

    sort_param = request.GET.get("sort") or "recent"
    direction_param = (request.GET.get("direction") or "").lower()
    allowed_directions = {"asc", "desc"}

    sort_field_map = {
        "recent": "sale_date",
        "sale_price": "sale_price",
        "price_per_sqft": "price_per_sqft",
        "price_per_acre": "price_per_acre",
        "ratio": "sale_to_market_ratio",
        "living_area": "living_area",
        "lot_size": "lot_size_acres",
    }
    selected_field = sort_field_map.get(sort_param, "sale_date")
    default_direction = "desc"
    sort_direction = direction_param if direction_param in allowed_directions else default_direction
    ordering = f"-{selected_field}" if sort_direction == "desc" else selected_field

    qs = qs.order_by(ordering, "-sale_id")

    filters = {
        "active_years": years_param if years_param in SALES_SEARCH_ALLOWED_YEARS else (SALES_SEARCH_DEFAULT_YEARS if not request.GET else None),
        "start_date": start_date,
        "end_date": end_date,
        "min_price": min_price,
        "max_price": max_price,
        "min_living_area": min_living_area,
        "max_living_area": max_living_area,
        "min_lot_acres": min_lot_acres,
        "max_lot_acres": max_lot_acres,
        "city": city,
        "arms_length_only": arms_length_only,
        "exclude_outliers": exclude_outliers,
        "parcel_number": parcel_number,
    }
    sort_meta = {"field": sort_param if sort_param in sort_field_map else "recent", "direction": sort_direction}

    return qs, filters, sort_meta


def _build_attribute_string(row: Dict[str, Any]) -> str:
    parts = []
    beds = _format_measure(row.get("bedrooms"), "bd", decimals=0)
    if beds:
        parts.append(beds)
    baths = _format_measure(row.get("bathrooms"), "ba", decimals=1)
    if baths:
        parts.append(baths)
    acres = _format_measure(row.get("acres"), "ac", decimals=2)
    if acres:
        parts.append(acres)
    return " • ".join(parts) if parts else "Details unavailable"


def _format_currency(value: Any) -> str:
    number = _clean_decimal(value)
    if number is None:
        return "—"
    return f"${intcomma(int(round(number)))}"


def _clean_address(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Treat common placeholder/import artifacts as missing
    lowered = s.lower()
    if lowered in {"nan", "nan nan, nan", "none", "null", "n/a"}:
        return None
    return s


def _fetch_top_sales(limit: int) -> List[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [limit])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results: List[Dict[str, Any]] = []
    for row in rows:
        sale_price_dec = _clean_decimal(row.get("sale_price"))
        sale_price_value = int(sale_price_dec) if sale_price_dec is not None else None
        sale_price_display = _format_currency(row.get("sale_price"))
        assessed_dec = _clean_decimal(row.get("assessed_value"))
        delta = _delta_metadata(sale_price_dec, assessed_dec)
        parcel_number = row.get("parcel_number")
        if not parcel_number:
            continue
        parcel_number = str(parcel_number).strip()
        attributes = _build_attribute_string(row)

        results.append(
            {
                "parcel_number": parcel_number,
                "address": _clean_address(row.get("address")) or "Address unavailable",
                "attributes": attributes,
                "sale_price_display": sale_price_display,
                "sale_price_value": sale_price_value,
                "delta_class": delta["class"],
                "delta_display": delta["display"],
                "sale_date_display": _format_sale_date(row.get("sale_date")),
                "links": {
                    "redfin": f"https://www.redfin.com/parcel/{parcel_number}",
                    "skagit": f"https://www.skagitcounty.net/assessor/?parcel={parcel_number}",
                },
                "modal_url": reverse("parcel-modal-partial", args=[parcel_number]),
            }
        )

    return results


def _fetch_sale_detail(parcel_number: str) -> Optional[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
          AND s.parcel_number = %s
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [parcel_number])
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
    if not row:
        return None
    return dict(zip(columns, row))


@require_GET
def top_sales_widget(request):
    """
    HTMX endpoint that renders the Top 25 sales list in a card-based layout.
    """
    results = _fetch_top_sales(TOP_SALES_LIMIT)
    return render(request, "openskagit/partials/top_sales_list.html", {"results": results})


@require_GET
def parcel_modal(request, parcel_number: str):
    """
    Render the parcel detail modal with lazy-loaded sale and valuation data.
    """
    record = _fetch_sale_detail(parcel_number)
    if not record:
        raise Http404("Parcel sale record not found.")

    sale_price_dec = _clean_decimal(record.get("sale_price"))
    assessed_dec = _clean_decimal(record.get("assessed_value"))
    delta = _delta_metadata(sale_price_dec, assessed_dec)

    sale = {
        "sale_price_display": _format_currency(record.get("sale_price")),
        "sale_price_value": int(sale_price_dec) if sale_price_dec is not None else None,
        "sale_date_display": _format_sale_date(record.get("sale_date")),
        "sale_type": (record.get("sale_type") or "").title() or None,
        "buyer_name": record.get("buyer_name"),
        "seller_name": record.get("seller_name"),
        "recording_number": _format_identifier(record.get("recording_number")) or "—",
        "excise_number": _format_identifier(record.get("excise_number")) or "—",
        "deed_type": record.get("deed_type"),
    }

    primary_metrics = [
        {"label": "Bedrooms", "value": _format_measure(record.get("bedrooms"), "bd", decimals=0) or "—"},
        {"label": "Bathrooms", "value": _format_measure(record.get("bathrooms"), "ba", decimals=1) or "—"},
        {"label": "Living Area", "value": _format_living_area(record.get("living_area")) or "—"},
        {"label": "Lot Size", "value": _format_measure(record.get("acres"), "ac", decimals=2) or "—"},
    ]

    valuation_metrics = [
        {"label": "Assessed Value", "value": _format_currency(record.get("assessed_value")), "subtitle": None},
        {"label": "Market Value", "value": _format_currency(record.get("total_market_value")), "subtitle": None},
        {"label": "Taxable Value", "value": _format_currency(record.get("taxable_value")), "subtitle": None},
    ]

    context = {
        "parcel_number": parcel_number,
        "address": _clean_address(record.get("address")) or "Address unavailable",
        "sale": sale,
        "delta": {"display": delta["display"], "class": delta["class"]},
        "primary_metrics": primary_metrics,
        "valuation_metrics": valuation_metrics,
    }
    return render(request, "openskagit/partials/parcel_modal.html", context)


def home(request):
    """
    Render the OpenSkagit portal homepage.
    """
    # flavor_signal_payload = extract_flavor_signals(limit=3)  # Not used on the homepage; leave disabled for now.

    page_title = "OpenSkagit · AI-Enhanced Data Portal for Skagit County"
    meta_description = (
        "OpenSkagit turns public records, menus, reviews, and local documents into "
        "responsive tools, live signals, and citeable answers for Skagit Valley."
    )
    canonical_url = request.build_absolute_uri()
    social_title = "Skagit Valley. Understood. · OpenSkagit"
    nav_links = _primary_nav_links()
    hero_questions = [
        "What can I build on my property?",
        "Why did my property taxes change?",
        "What’s happening in my neighborhood?",
        "Is this land buildable?",
        "What does zoning actually allow here?",
    ]
    total_parcels = MasterParcel.objects.count()
    restaurant_count = Restaurant.objects.count()
    menu_items_count = MenuItem.objects.count()

    context = _basic_page_context(page_title, meta_description)
    context.update(
        {
            "total_parcels": total_parcels,
            "restaurant_count": restaurant_count,
            "menu_items_count": menu_items_count,
            "hero_questions": hero_questions,
            "mcp_custom_gpt_url": MCP_CUSTOM_GPT_URL,
            # "flavor_signals": flavor_signal_payload,
            "og_title": social_title,
            "og_description": meta_description,
            "og_type": "website",
            "og_image": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1765735577/ChatGPT_Image_Dec_14_2025_10_05_37_AM_oprqoo.png",
            "og_url": canonical_url,
            "twitter_title": social_title,
            "twitter_description": meta_description,
            "twitter_card": "summary_large_image",
            "canonical_url": canonical_url,
            "nav_links": nav_links,
        }
    )
    return render(request, "openskagit/home_portal.html", context)

def _basic_page_context(title: str, description: str) -> Dict[str, Any]:
    context = {
        "page_title": title,
        "meta_description": description,
        "og_title": title,
        "og_description": description,
        "og_type": "website",
        "og_image": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1765735577/ChatGPT_Image_Dec_14_2025_10_05_37_AM_oprqoo.png",
        "meta_robots": "",
        "twitter_title": title,
        "twitter_description": description,
        "twitter_image": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1765735577/ChatGPT_Image_Dec_14_2025_10_05_37_AM_oprqoo.png",
        "twitter_card": "summary_large_image",
        "canonical_url": None,
        "og_url": None,
        "favicon": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1768253765/logoicon_c_crop_w_480_h_467_x_0_y_0-Picsart-BackgroundRemover_uklqfi.png",
        "apple_touch_icon": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1768253765/logoicon_c_crop_w_480_h_467_x_0_y_0-Picsart-BackgroundRemover_uklqfi.png",
        "nav_links": _primary_nav_links(),
    }
    return context


_MCP_HTTP_METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
_MCP_HTTP_METHOD_SET = {method.lower() for method in _MCP_HTTP_METHOD_ORDER}
_MCP_GROUP_METADATA = {
    "health": {
        "label": "Service Health",
        "description": "Ping endpoint used by clients to verify API availability before data calls.",
    },
    "lookup": {
        "label": "Parcel Discovery",
        "description": "Search by parcel number or address text to resolve parcel_id.",
    },
    "parcel": {
        "label": "Parcel Intelligence",
        "description": "Core parcel context: bundle, valuation history, flood metrics, comps, and neighborhood trends.",
    },
    "overlay": {
        "label": "Overlay Engine",
        "description": "Layer catalog + parcel overlay extraction for mapped reference datasets.",
    },
    "legal": {
        "label": "Legal Code",
        "description": "Jurisdiction-aware legal search and section retrieval from ingested code sources.",
    },
    "legacy_agent": {
        "label": "Legacy Agent API",
        "description": "Bearer-token endpoints from the legacy /agent/api surface.",
    },
    "gastronet": {
        "label": "Gastronet",
        "description": "Selected food intelligence and ingestion endpoints exposed for tool use.",
    },
    "nlq": {
        "label": "Guarded NLQ",
        "description": "Natural-language SQL fallback with schema/context and execution guardrails.",
    },
    "other": {
        "label": "Other",
        "description": "Additional operations outside primary parcel and legal groups.",
    },
}
_MCP_GROUP_ORDER = [
    "health",
    "lookup",
    "parcel",
    "overlay",
    "legal",
    "legacy_agent",
    "gastronet",
    "nlq",
    "other",
]


def _load_mcp_openapi_data(openapi_path: Path) -> Optional[Dict[str, Any]]:
    if not openapi_path.exists():
        logger.warning("MCP OpenAPI missing at %s", openapi_path)
        return None

    try:
        data = json.loads(openapi_path.read_text())
    except Exception as exc:  # pragma: no cover - defensive path for malformed files
        logger.warning("Failed to parse MCP OpenAPI at %s: %s", openapi_path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("MCP OpenAPI at %s did not parse to an object", openapi_path)
        return None

    return data


def _mcp_group_key_for_path(path: str) -> str:
    tokens = [token for token in path.strip("/").split("/") if token]
    if not tokens:
        return "other"

    if tokens[0] == "agent":
        if len(tokens) >= 2:
            second = tokens[1]
            if second == "api":
                return "legacy_agent"
            if second in _MCP_GROUP_METADATA:
                return second
            if second == "parcel":
                return "parcel"
        return "other"

    if tokens[0] == "api":
        if len(tokens) >= 2 and tokens[1] == "gastronet":
            return "gastronet"
        return "other"

    head = tokens[0]
    return head if head in _MCP_GROUP_METADATA else "other"


def _mcp_response_code_sort_key(code: str) -> Tuple[int, Any]:
    if code.isdigit():
        return (0, int(code))
    return (1, code)


def _mcp_schema_rule(schema: Dict[str, Any]) -> Optional[str]:
    if not isinstance(schema, dict):
        return None

    parts: List[str] = []
    if "minimum" in schema and "maximum" in schema:
        parts.append(f"{schema['minimum']}..{schema['maximum']}")
    else:
        if "minimum" in schema:
            parts.append(f">= {schema['minimum']}")
        if "maximum" in schema:
            parts.append(f"<= {schema['maximum']}")

    if "default" in schema:
        parts.append(f"default {schema['default']}")

    if not parts:
        return None

    return ", ".join(parts)


def _extract_mcp_capabilities_from_openapi(
    openapi_path: Path, openapi_data: Optional[Dict[str, Any]] = None
) -> List[str]:
    default_capabilities = [
        "Parcel lookup by address or parcel number",
        "Parcel bundle with site facts, geometry, and overlays in one payload",
        "Zoning, environmental, and jurisdiction overlays for a parcel",
        "Flood indicators plus neighborhood context around a parcel",
        "Comparable sales snapshots near a parcel",
        "Legal code search and section retrieval by jurisdiction",
        "Guardrailed natural-language answers when structured tools are not enough",
    ]
    data = openapi_data or _load_mcp_openapi_data(openapi_path)
    if not data:
        return default_capabilities

    entries: List[str] = []
    for path, methods in data.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for meta in methods.values():
            method_meta = meta if isinstance(meta, dict) else {}
            entries.append(
                " ".join(
                    [
                        str(path).lower(),
                        str(method_meta.get("summary", "")).lower(),
                        str(method_meta.get("description", "")).lower(),
                    ]
                )
            )

    patterns = [
        ("health", "Health check endpoint for API uptime verification"),
        ("lookup", "Parcel lookup by address or parcel number"),
        ("bundle", "Parcel bundle with site facts, geometry, and overlays in one payload"),
        ("history", "Valuation and tax roll history for a parcel"),
        ("flood", "FEMA flood zone indicators and base flood elevations where available"),
        (
            "intersect",
            "Check a parcel against zoning, flood, shoreline, wetlands, city limits, and fire districts",
        ),
        ("neighborhood", "Neighborhood ratios and trend context around a parcel"),
        ("sales", "Comparable sales near a parcel with guardrails on fit"),
        ("overlay", "List and fetch overlays and reference layers for a location"),
        ("legal", "Legal code search and section retrieval by jurisdiction"),
        ("nlq", "Guardrailed natural-language answers when structured tools are not enough"),
    ]

    capabilities: List[str] = []
    seen: Set[str] = set()
    for key, label in patterns:
        if any(key in entry for entry in entries):
            if label not in seen:
                capabilities.append(label)
                seen.add(label)

    return capabilities or default_capabilities


def _summarize_mcp_openapi(openapi_path: Path, openapi_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fallback = {
        "title": "OpenSkagit MCP Agent",
        "version": "unknown",
        "description": "Read-only MCP endpoints for parcel lookup, overlays, comps, and guarded NLQ.",
        "openapi_version": "unknown",
        "server_url": "https://openskagit.com",
        "spec_source": openapi_path.name,
        "spec_updated_at": None,
        "path_count": 0,
        "operation_count": 0,
        "method_breakdown": [],
        "group_cards": [],
        "response_codes": [],
        "constraints": [],
        "guardrails": [],
        "endpoint_rows": [],
        "flow_steps": [
            {
                "title": "Resolve parcel_id",
                "detail": "Search by address or parcel fragment before calling parcel-specific endpoints.",
            },
            {
                "title": "Fetch parcel context",
                "detail": "Use bundle, history, flood, comparables, and neighborhood endpoints for structured parcel data.",
            },
            {
                "title": "Join overlays or legal text",
                "detail": "Fetch overlay layers and legal code records for planning and compliance context.",
            },
            {
                "title": "Fallback to guarded NLQ",
                "detail": "Only use NLQ when structured endpoints cannot answer directly.",
            },
        ],
    }

    data = openapi_data or _load_mcp_openapi_data(openapi_path)
    if not data:
        return fallback

    paths = data.get("paths")
    if not isinstance(paths, dict):
        return fallback

    method_counts: Dict[str, int] = {}
    group_accumulator: Dict[str, Dict[str, Any]] = {}
    response_counts: Dict[str, int] = {}
    constraint_seen: Set[str] = set()
    constraints: List[Dict[str, str]] = []
    endpoint_rows: List[Dict[str, Any]] = []
    guardrail_flags: Set[str] = set()

    method_rank = {name.lower(): index for index, name in enumerate(_MCP_HTTP_METHOD_ORDER)}
    sorted_paths = sorted(paths.items(), key=lambda item: item[0])
    for path, methods in sorted_paths:
        if not isinstance(methods, dict):
            continue

        for method_name, meta in sorted(methods.items(), key=lambda item: method_rank.get(str(item[0]).lower(), 999)):
            method = str(method_name).lower()
            if method not in _MCP_HTTP_METHOD_SET:
                continue

            method_upper = method.upper()
            method_counts[method_upper] = method_counts.get(method_upper, 0) + 1

            method_meta = meta if isinstance(meta, dict) else {}
            summary = str(method_meta.get("summary") or "").strip()
            description = str(method_meta.get("description") or "").strip()
            operation_id = str(method_meta.get("operationId") or "").strip()
            if not operation_id:
                operation_id = f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}"
            if not summary:
                summary = description or "No summary provided."

            meta_blob = f"{summary} {description}".lower()
            if "allowlist" in meta_blob or "allowlisted" in meta_blob:
                guardrail_flags.add("allowlist")
            if "guardrail" in meta_blob:
                guardrail_flags.add("guardrail")
            if "cost/row" in meta_blob or ("cost" in meta_blob and "row" in meta_blob):
                guardrail_flags.add("cost")

            group_key = _mcp_group_key_for_path(path)
            group_entry = group_accumulator.setdefault(
                group_key,
                {"count": 0, "methods": set(), "operation_ids": [], "sample_paths": []},
            )
            group_entry["count"] += 1
            group_entry["methods"].add(method_upper)
            group_entry["operation_ids"].append(operation_id)
            if len(group_entry["sample_paths"]) < 2:
                group_entry["sample_paths"].append(path)

            required_inputs: List[str] = []
            optional_inputs: List[str] = []
            parameters = method_meta.get("parameters")
            if isinstance(parameters, list):
                for parameter in parameters:
                    if not isinstance(parameter, dict):
                        continue
                    name = str(parameter.get("name") or "").strip()
                    if not name:
                        continue

                    schema = parameter.get("schema")
                    if not isinstance(schema, dict):
                        schema = {}

                    if parameter.get("required"):
                        required_inputs.append(name)
                    else:
                        optional_inputs.append(name)

                    rule = _mcp_schema_rule(schema)
                    if rule:
                        constraint_key = f"{method_upper}|{path}|{name}|{rule}"
                        if constraint_key not in constraint_seen:
                            constraints.append(
                                {
                                    "context": f"{method_upper} {path}",
                                    "field": name,
                                    "rule": rule,
                                }
                            )
                            constraint_seen.add(constraint_key)

            request_body = method_meta.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if isinstance(content, dict):
                    json_body = content.get("application/json")
                    if isinstance(json_body, dict):
                        body_schema = json_body.get("schema")
                        if isinstance(body_schema, dict):
                            body_properties = body_schema.get("properties")
                            required_body_fields = body_schema.get("required")
                            required_body_set = (
                                set(required_body_fields)
                                if isinstance(required_body_fields, list)
                                else set()
                            )
                            if isinstance(body_properties, dict):
                                for field_name, field_schema in body_properties.items():
                                    body_field = f"body.{field_name}"
                                    if field_name in required_body_set:
                                        required_inputs.append(body_field)
                                    else:
                                        optional_inputs.append(body_field)

                                    schema = field_schema if isinstance(field_schema, dict) else {}
                                    rule = _mcp_schema_rule(schema)
                                    if rule:
                                        constraint_key = f"{method_upper}|{path}|{body_field}|{rule}"
                                        if constraint_key not in constraint_seen:
                                            constraints.append(
                                                {
                                                    "context": f"{method_upper} {path}",
                                                    "field": body_field,
                                                    "rule": rule,
                                                }
                                            )
                                            constraint_seen.add(constraint_key)

            required_unique = sorted(set(required_inputs))
            required_set = set(required_unique)
            optional_unique = sorted(item for item in set(optional_inputs) if item not in required_set)

            response_codes: List[str] = []
            responses = method_meta.get("responses")
            if isinstance(responses, dict):
                for response_code in responses.keys():
                    code = str(response_code)
                    response_codes.append(code)
                    response_counts[code] = response_counts.get(code, 0) + 1

            endpoint_rows.append(
                {
                    "method": method_upper,
                    "path": path,
                    "operation_id": operation_id,
                    "summary": summary,
                    "required_inputs": required_unique,
                    "optional_inputs": optional_unique,
                    "responses": sorted(set(response_codes), key=_mcp_response_code_sort_key),
                    "group": group_key,
                }
            )

    operation_count = len(endpoint_rows)
    if operation_count == 0:
        return fallback

    info = data.get("info")
    info_payload = info if isinstance(info, dict) else {}
    openapi_version = str(data.get("openapi") or "unknown")
    title = str(info_payload.get("title") or fallback["title"])
    version = str(info_payload.get("version") or fallback["version"])
    description = str(info_payload.get("description") or fallback["description"])

    servers = data.get("servers")
    server_url = fallback["server_url"]
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict):
            candidate = str(first.get("url") or "").strip()
            if candidate:
                server_url = candidate.rstrip("/")

    method_breakdown: List[Dict[str, Any]] = []
    for method_name in _MCP_HTTP_METHOD_ORDER:
        count = method_counts.get(method_name, 0)
        if count <= 0:
            continue
        method_breakdown.append(
            {
                "method": method_name,
                "count": count,
                "percent": round((count / operation_count) * 100),
            }
        )

    group_cards: List[Dict[str, Any]] = []
    known_groups = {key for key in group_accumulator.keys() if key in _MCP_GROUP_ORDER}
    ordered_groups = [key for key in _MCP_GROUP_ORDER if key in known_groups]
    ordered_groups.extend(sorted(key for key in group_accumulator.keys() if key not in _MCP_GROUP_ORDER))
    for group_key in ordered_groups:
        meta = _MCP_GROUP_METADATA.get(group_key, _MCP_GROUP_METADATA["other"])
        group_row = group_accumulator[group_key]
        group_cards.append(
            {
                "key": group_key,
                "label": meta["label"],
                "description": meta["description"],
                "count": group_row["count"],
                "methods": sorted(group_row["methods"]),
                "operation_ids": sorted(set(group_row["operation_ids"])),
                "sample_paths": group_row["sample_paths"],
            }
        )

    response_codes = []
    for code, count in sorted(response_counts.items(), key=lambda item: _mcp_response_code_sort_key(item[0])):
        response_codes.append(
            {
                "code": code,
                "count": count,
                "percent": round((count / operation_count) * 100),
            }
        )

    guardrails: List[str] = []
    get_count = method_counts.get("GET", 0)
    if get_count:
        guardrails.append(f"{get_count} of {operation_count} operations use GET for read-only retrieval.")

    has_limit_cap = any("25" in row["rule"] and row["field"] == "limit" for row in constraints)
    if has_limit_cap:
        guardrails.append("Search/list routes set explicit result caps (for example, limit <= 25).")

    if "allowlist" in guardrail_flags:
        guardrails.append("Overlay intersection is constrained to allowlisted layer keys.")

    if "guardrail" in guardrail_flags or "cost" in guardrail_flags:
        guardrails.append("NLQ route is documented with SQL guardrails and execution checks.")

    if any(code["code"] == "400" for code in response_codes):
        guardrails.append("Invalid or missing inputs return explicit 400-series responses.")

    flow_steps = [
        {
            "title": "Resolve parcel_id",
            "detail": "Start with lookup to resolve a parcel from free text address or parcel fragment.",
        },
        {
            "title": "Load parcel context",
            "detail": "Fetch bundle/history/flood/neighborhood/comps endpoints for deterministic parcel facts.",
        },
        {
            "title": "Expand with overlays and legal",
            "detail": "Pull overlay layers or legal sections for jurisdiction and compliance context.",
        },
        {
            "title": "Fallback to NLQ",
            "detail": "Use guarded natural-language SQL only when structured endpoints are insufficient.",
        },
    ]

    spec_updated_at = None
    try:
        spec_updated_at = dt.datetime.fromtimestamp(openapi_path.stat().st_mtime, tz=dt.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except OSError:
        spec_updated_at = None

    return {
        "title": title,
        "version": version,
        "description": description,
        "openapi_version": openapi_version,
        "server_url": server_url,
        "spec_source": openapi_path.name,
        "spec_updated_at": spec_updated_at,
        "path_count": len(paths),
        "operation_count": operation_count,
        "method_breakdown": method_breakdown,
        "group_cards": group_cards,
        "response_codes": response_codes,
        "constraints": constraints,
        "guardrails": guardrails,
        "endpoint_rows": endpoint_rows,
        "flow_steps": flow_steps,
    }


@require_GET
def about_view(request):
    context = _basic_page_context("About OpenSkagit", "Learn about the mission, team, and approach behind OpenSkagit.")
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/about.html", context)


@require_http_methods(["GET", "POST"])
def contact_view(request):
    context = _basic_page_context(
        "Contact OpenSkagit",
        "Get in touch with the OpenSkagit team for support, media, or collaboration.",
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]

    if request.method == "POST":
        form = ContactSubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save()
            email_sent = _send_contact_submission_email(submission)
            if email_sent:
                messages.success(request, "Thanks! We received your note and will get back to you shortly.")
            else:
                messages.warning(
                    request,
                    "We saved your message, but delivering the notification email failed. We'll review it inside the dashboard.",
                )
            return redirect("contact")
        messages.error(request, "Please fix the highlighted fields and try again.")
    else:
        initial = {}
        requested_topic = (request.GET.get("topic") or "").strip()
        if requested_topic in dict(ContactSubmission.TOPIC_CHOICES):
            initial["topic"] = requested_topic
        prefills = [
            (request.GET.get("message") or "").strip(),
            (request.GET.get("subject") or "").strip(),
        ]
        for value in prefills:
            if value:
                initial["message"] = value
                break
        form = ContactSubmissionForm(initial=initial or None)

    context["form"] = form
    return render(request, "openskagit/contact.html", context)


@require_http_methods(["GET", "POST"])
def coappraiser_upload_view(request):
    context = _basic_page_context(
        "CO Appraiser Upload · OpenSkagit",
        "Upload a CAMA parcel CSV for CO appraiser workflows.",
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]

    if request.method == "POST":
        upload = request.FILES.get("csv_file")
        if upload is None:
            messages.error(request, "Choose a CSV file to upload.")
            return redirect("coappraiser-upload")

        original_name = Path(upload.name or "").name or "upload.csv"
        if not original_name.lower().endswith(".csv"):
            messages.error(request, "Only CSV uploads are supported right now.")
            return redirect("coappraiser-upload")

        safe_name = get_valid_filename(original_name) or "upload.csv"
        safe_path = Path(safe_name)
        stem = safe_path.stem or "upload"
        suffix = safe_path.suffix.lower() or ".csv"
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        unique_suffix = uuid.uuid4().hex[:8]
        relative_path = f"coappraiser/{timestamp}_{unique_suffix}_{stem}{suffix}"

        storage = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)
        saved_relative_path = storage.save(relative_path, upload)
        messages.success(request, f"Uploaded {original_name} to /media/{saved_relative_path}.")
        return redirect("coappraiser-upload")

    return render(request, "openskagit/coappraiser_upload.html", context)


@require_GET
def mcp_openapi_json(request):
    openapi_path = Path(settings.BASE_DIR) / "mcp_agent_openapi.json"
    openapi_data = _load_mcp_openapi_data(openapi_path)
    if not openapi_data:
        return JsonResponse({"error": "mcp_openapi_unavailable"}, status=503)

    site_url = request.build_absolute_uri("/").rstrip("/")
    payload = copy.deepcopy(openapi_data)
    if site_url:
        payload["servers"] = [{"url": site_url}]

    return JsonResponse(payload)


@require_GET
def mcp_view(request):
    context = _basic_page_context(
        "SkagitMCP · OpenSkagit",
        "Connect AI assistants to Skagit Valley property and planning data through simple, stable tools.",
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    openapi_path = Path(settings.BASE_DIR) / "mcp_agent_openapi.json"
    openapi_data = _load_mcp_openapi_data(openapi_path)
    context["mcp_capabilities"] = _extract_mcp_capabilities_from_openapi(openapi_path, openapi_data=openapi_data)
    context["mcp_openapi"] = _summarize_mcp_openapi(openapi_path, openapi_data=openapi_data)
    context["mcp_custom_gpt_url"] = MCP_CUSTOM_GPT_URL
    return render(request, "openskagit/mcp.html", context)


@require_GET
def privacy_policy_view(request):
    context = _basic_page_context(
        "Privacy Policy | OpenSkagit",
        "How OpenSkagit handles personal information, analytics data, and public records.",
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/privacy.html", context)


def _send_contact_submission_email(submission: ContactSubmission) -> bool:
    subject = f"OpenSkagit contact: {submission.get_topic_display()}"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@openskagit.com")
    submitted_at = submission.created_at
    if timezone.is_aware(submitted_at):
        submitted_at = timezone.localtime(submitted_at)

    body = (
        "New contact submission on openskagit.com\n\n"
        f"From: {submission.email}\n"
        f"Topic: {submission.get_topic_display()} ({submission.topic})\n"
        f"Submitted: {submitted_at:%Y-%m-%d %H:%M %Z}\n\n"
        f"Message:\n{submission.message}"
    )

    try:
        send_mail(subject, body, from_email, ["ian.larsen.1976@gmail.com"])
        return True
    except Exception:
        logger.exception("Unable to send contact submission notification (id=%s)", submission.id)
        return False


@require_GET
def votevector_view(request):
    hero_description = (
        "VoteVector now measures the Neighborhood Participation Index (NPI)—ballots cast per residential parcel—to spotlight where civic energy concentrates."
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(election_year) FROM fact_neighborhood_participation")
        latest_year_row = cursor.fetchone()
        latest_year = latest_year_row[0] if latest_year_row else None
        stats = []
        if latest_year:
            cursor.execute(
                """
                SELECT
                    COUNT(DISTINCT neighborhood_code) AS neighborhoods,
                    COALESCE(SUM(ballots_cast), 0) AS ballots_cast,
                    COALESCE(SUM(residential_parcels), 0) AS parcels_tracked,
                    AVG(npi) AS avg_npi
                FROM fact_neighborhood_participation
                WHERE election_year = %s
                """,
                [latest_year],
            )
            neighborhoods, ballots_cast, parcels_tracked, avg_npi = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM neighborhood_participation_classification
                WHERE election_year = %s AND quartile = 4
                """,
                [latest_year],
            )
            q4_count = cursor.fetchone()[0]
            stats = [
                {
                    "label": "Active neighborhoods",
                    "value": neighborhoods or 0,
                    "caption": f"Cohorts included for election {latest_year}.",
                    "accent_class": "bg-emerald-200",
                    "badge_label": "Live",
                    "badge_class": "bg-emerald-50 text-emerald-700",
                    "animate": True,
                },
                {
                    "label": "Ballots analyzed",
                    "value": ballots_cast or 0,
                    "caption": "Mapped to residential parcels countywide.",
                    "accent_class": "bg-sky-200",
                    "badge_label": f"{latest_year}",
                    "badge_class": "bg-sky-50 text-sky-800",
                    "animate": True,
                },
                {
                    "label": "Residential parcels tracked",
                    "value": parcels_tracked or 0,
                    "caption": "Households included in NPI calculations.",
                    "accent_class": "bg-amber-200",
                    "badge_label": "Parcels",
                    "badge_class": "bg-amber-50 text-amber-800",
                    "animate": True,
                },
                {
                    "label": "High-density neighborhoods",
                    "value": q4_count or 0,
                    "caption": "Neighborhoods in the top participation quartile.",
                    "accent_class": "bg-rose-200",
                    "badge_label": "Quartile 4",
                    "badge_class": "bg-rose-50 text-rose-800",
                    "animate": True,
                },
            ]
            if avg_npi is not None:
                stats.append(
                    {
                        "label": "Average NPI",
                        "value": round(avg_npi, 2),
                        "caption": "Countywide ballots per residential parcel.",
                        "accent_class": "bg-indigo-200",
                        "badge_label": "Mean",
                        "badge_class": "bg-indigo-50 text-indigo-800",
                        "animate": False,
                        "display": f"{avg_npi:.2f}",
                    }
                )
    context = _basic_page_context("VoteVector · OpenSkagit", hero_description)
    context.update(
        {
            "canonical_url": request.build_absolute_uri(),
            "votevector": {
                "tagline": "Tracking how strongly each neighborhood shows up.",
                "hero_description": hero_description,
                "short_explainer": (
                    "Neighborhood Participation Index (NPI) divides ballots by residential parcels. Higher values reveal neighborhoods where a large share of households voted; lower values highlight places with civic slack."
                ),
                "metric_label": "Neighborhood Participation Index (NPI)",
                "hover_helper": "Higher NPI = more ballots per residential parcel.",
                "legend_subtitle": "Ballots cast per residential parcel",
                "launch_points": [
                    "VoteVector is still system diagnostics, but now centered on how intensely each neighborhood participates.",
                    "Anchoring on residential parcels keeps the metric household-friendly and stable over time.",
                ],
                "mental_model": [
                    ("Geometry", "neighborhood boundaries"),
                    ("Neighborhood Participation Index", "ballots ÷ residential parcels"),
                    ("Neighborhood", "spatial unit"),
                    ("Quartiles", "participation density bands"),
                ],
            },
        }
    )
    context["og_url"] = context["canonical_url"]
    context["votevector_stats"] = stats
    return render(request, "openskagit/votevector.html", context)


@require_GET
def votevector_district3_view(request):
    hero_description = (
        "Commissioner District 3 lens for turnout, neighborhood participation, "
        "census demographics, neighborhood trends, new construction, and major-party lean."
    )
    context = _basic_page_context("VoteVector District 3 · OpenSkagit", hero_description)
    context.update(
        {
            "canonical_url": request.build_absolute_uri(),
            "votevector_district": {
                "district_label": "Commissioner District 3",
                "hero_description": hero_description,
                "api_endpoint": reverse("votevector-district3-map"),
                "intro": (
                    "Toggle NPI, turnout, demographics, party-lean, neighborhood trend, and new construction overlays "
                    "to inspect District 3 using the most recent election year in the database."
                ),
            },
        }
    )
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/votevector_district3.html", context)


@require_GET
def sedro_woolley_portal(request):
    context = _basic_page_context(
        "Sedro-Woolley | OpenSkagit",
        "Public Sedro-Woolley city limits portal: parcels, value, sales, permits, and civic snapshots.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context["city_map_url"] = reverse("sedro-woolley-zoning-map")
    context["zoning_map_url"] = context["city_map_url"]
    context["portal_error"] = None

    try:
        context["portal"] = load_sedro_woolley_portal_context()
    except Exception:
        logger.exception("Unable to load Sedro-Woolley public portal context.")
        context["portal_error"] = "Data is still loading. Try again in a minute."
        context["portal"] = empty_sedro_woolley_portal_context()

    return render(request, "openskagit/sedro_woolley_portal.html", context)


@require_GET
def sedro_woolley_zoning_map(request):
    context = _basic_page_context(
        "Sedro-Woolley Parcel Map | OpenSkagit",
        "Interactive parcel map for zoning, land lift, new construction, and ward context in Sedro-Woolley.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context["zoning_data_endpoint"] = reverse("sedro-woolley-zoning-data")
    return render(request, "openskagit/sedro_woolley_zoning_map.html", context)


@require_GET
def sedro_woolley_zoning_data(request):
    refresh_param = (request.GET.get("refresh") or "").strip().lower()
    force_refresh = bool(request.user.is_staff and refresh_param in {"1", "true", "yes"})
    try:
        payload = load_sedro_woolley_zoning_feature_collection(force_refresh=force_refresh)
    except Exception:
        logger.exception("Unable to load Sedro-Woolley zoning map data.")
        return JsonResponse(
            {
                "error": "Unable to load Sedro-Woolley zoning map data right now.",
                "details": {"city": "Sedro-Woolley"},
            },
            status=503,
        )
    return JsonResponse(payload)


@require_POST
def subscribe_briefing(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (AttributeError, ValueError, UnicodeDecodeError):
        payload = request.POST
    email = (payload.get('email') or '').strip()
    if not email:
        return JsonResponse({"ok": False, "error": "Email is required."}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"ok": False, "error": "Please enter a valid email."}, status=400)
    normalized = email.lower()
    subscriber, created = WeeklyBriefingSubscriber.objects.get_or_create(email=normalized)
    return JsonResponse({"ok": True, "created": created})


DEFAULT_BRIEFING_SECTIONS = [
    {
        "title": "Weekly data refresh",
        "summary": "Parcels, sales, and permit updates are pulled each Monday to keep you ahead of the latest county numbers.",
        "badge": "Updated",
        "highlight": "New every Monday",
    },
    {
        "title": "Neighborhood pulse",
        "summary": "Spotlight cards feature neighborhoods that are seeing movement in permits, participatory sessions, or civic milestones.",
        "badge": "Spotlight",
        "highlight": "Context + direction",
    },
    {
        "title": "Stories + invitations",
        "summary": "We share data-backed stories and links to upcoming workshops so community partners can plug in quickly.",
        "badge": "Community",
        "highlight": "Opportunities this week",
    },
]

WeeklyBriefingSectionFormSet = inlineformset_factory(
    WeeklyBriefingTemplate,
    WeeklyBriefingSection,
    form=WeeklyBriefingSectionForm,
    extra=2,
    can_delete=True,
    min_num=2,
    validate_min=True,
)


def _ensure_weekly_briefing_template() -> WeeklyBriefingTemplate:
    template, created = WeeklyBriefingTemplate.objects.get_or_create()
    if created or not template.sections.exists():
        for index, section_data in enumerate(DEFAULT_BRIEFING_SECTIONS):
            WeeklyBriefingSection.objects.create(template=template, order=index, **section_data)
    return template


@login_required
def newsletter_dashboard(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    template = _ensure_weekly_briefing_template()
    post_data = request.POST if request.method == "POST" else None
    section_formset = WeeklyBriefingSectionFormSet(
        post_data, instance=template, prefix="sections"
    )
    template_form = WeeklyBriefingTemplateForm(post_data, instance=template)

    test_recipient = request.user.email or request.user.get_username()
    if request.method == "POST":
        action = request.POST.get("action")
        if template_form.is_valid() and section_formset.is_valid():
            template_form.save()
            section_formset.save()
            if action == "send":
                messages.info(request, "Dispatching the Weekly Briefing to all subscribers…")
                try:
                    log = send_weekly_briefing()
                except ValueError as exc:
                    messages.error(request, f"Unable to send briefing: {exc}")
                else:
                    messages.success(
                        request,
                        f"Weekly briefing sent to {log.sent_count} subscribers "
                        f"({log.error_count} failed deliveries).",
                    )
                    if log.error_count:
                        error_note = (
                            log.error_snapshot
                            if log.error_snapshot
                            else "Some deliveries failed—check the logs for details."
                        )
                        messages.warning(request, error_note)
            elif action == "test":
                if not request.user.email:
                    messages.error(request, "Your user account needs an email to receive a test send.")
                else:
                    messages.info(
                        request,
                        f"Sending a test Weekly Briefing to {request.user.email} only.",
                    )
                    try:
                        log = send_weekly_briefing(recipients=[request.user.email])
                    except ValueError as exc:
                        messages.error(request, f"Unable to send test briefing: {exc}")
                    else:
                        messages.success(
                            request,
                            f"Test briefing sent to {request.user.email} "
                            f"({log.sent_count} delivery attempt).",
                        )
                        if log.error_count:
                            error_note = (
                                log.error_snapshot
                                if log.error_snapshot
                                else "Some deliveries failed—check the logs for details."
                            )
                            messages.warning(request, error_note)
            else:
                messages.success(request, "Weekly briefing template saved.")
            return redirect("newsletter-dashboard")
        else:
            messages.error(
                request,
                "Please fix the highlighted template/section errors before sending.",
            )

    preview_context = preview_briefing_context(template)
    preview_html = render_to_string(
        "openskagit/emails/weekly_briefing.html", preview_context
    )

    total_subscribers = WeeklyBriefingSubscriber.objects.count()
    recent_subscribers = WeeklyBriefingSubscriber.objects.order_by(
        "-created_at"
    )[:5]
    latest_send = WeeklyBriefingSendLog.objects.first()

    context = _basic_page_context(
        "Weekly Briefing dashboard",
        "View subscribers, edit newsletter sections, and record sends for the OpenSkagit Weekly Briefing.",
    )
    context.update(
        {
            "template_form": template_form,
            "section_formset": section_formset,
            "total_subscribers": total_subscribers,
            "recent_subscribers": recent_subscribers,
            "latest_send": latest_send,
            "preview_html": preview_html,
            "preview_context": preview_context,
            "test_recipient": test_recipient,
        }
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context["og_title"] = "Weekly Briefing dashboard · OpenSkagit"
    context["twitter_title"] = context["og_title"]
    context["meta_description"] = "Manage the OpenSkagit Weekly Briefing narrative, subscribers, and sends."
    context["og_description"] = context["meta_description"]
    context["twitter_description"] = context["meta_description"]
    context["twitter_image"] = context["og_image"]
    return render(request, "openskagit/newsletter/dashboard.html", context)


@require_http_methods(["GET", "POST"])
def newsletter_unsubscribe(request, token: str):
    subscriber = WeeklyBriefingSubscriber.from_unsubscribe_token(token)
    if not subscriber:
        status = "invalid"
    elif request.method == "POST":
        subscriber.delete()
        status = "success"
    else:
        status = "confirm"
    context = _basic_page_context(
        "Weekly Briefing unsubscribe",
        "Confirm you no longer want the OpenSkagit Weekly Briefing in your inbox.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context.update({"status": status, "subscriber": subscriber})
    return render(
        request,
        "openskagit/newsletter/unsubscribe.html",
        context,
    )


@require_GET
def partner_view(request):
    context = _basic_page_context("Partner with OpenSkagit", "Explore partnership opportunities to bring OpenSkagit data and tools into your organization.")
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/partner.html", context)


def _normalize_sentiment_overall_label(label: Optional[str]) -> Optional[float]:
    if not label:
        return None
    normalized = str(label).strip().lower()
    if "positive" in normalized:
        return 1.0
    if "negative" in normalized:
        return -1.0
    if "neutral" in normalized or "mixed" in normalized:
        return 0.0
    return None


def _extract_review_sentiment(review: Review) -> Optional[float]:
    enrichment = getattr(review, "enrichment", None)
    if enrichment and enrichment.sentiment_score is not None:
        return enrichment.sentiment_score

    payload = review.analysis_payload or {}
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            score_value = result.get("sentiment_score")
            if score_value is not None:
                try:
                    return float(score_value)
                except (TypeError, ValueError):
                    pass
            overall = result.get("sentiment_overall")
            normalized = _normalize_sentiment_overall_label(overall)
            if normalized is not None:
                return normalized

    if enrichment and enrichment.sentiment_overall:
        return _normalize_sentiment_overall_label(enrichment.sentiment_overall)

    return None


def _collect_flavor_heatmap_points() -> List[List[float]]:
    cutoff = timezone.now() - dt.timedelta(days=90)
    recent_reviews = (
        Review.objects.filter(created_at__gte=cutoff)
        .select_related("restaurant", "enrichment")
        .order_by("restaurant_id")
    )
    aggregated: Dict[int, Dict[str, float]] = {}
    for review in recent_reviews:
        restaurant = review.restaurant
        lat = restaurant.latitude
        lon = restaurant.longitude
        if lat is None or lon is None:
            continue
        sentiment = _extract_review_sentiment(review)
        if sentiment is None:
            continue
        entry = aggregated.setdefault(
            restaurant.id,
            {"lat": lat, "lon": lon, "total": 0.0, "count": 0},
        )
        entry["total"] += sentiment
        entry["count"] += 1

    points: List[List[float]] = []
    for stats in aggregated.values():
        count = stats["count"]
        if count <= 0:
            continue
        average = stats["total"] / count
        positive_average = max(0.0, average)
        if positive_average <= 0:
            continue
        weight = positive_average * math.log1p(count)
        if weight <= 0:
            continue
        points.append([stats["lat"], stats["lon"], weight])
    return points


def _restaurant_sales_history() -> Dict[str, Any]:
    current_year = timezone.now().year
    min_year = current_year - 5
    base_filters = {
        "naics_code": "722",
        "is_total_row": False,
        "taxable_sales__isnull": False,
        "quarter__year__gte": min_year,
    }

    aggregated_records = list(
        DorNaicsRecord.objects.filter(**base_filters)
        .values("quarter__period", "quarter__year", "quarter__quarter")
        .annotate(
            total_sales=Sum("taxable_sales"),
            total_units=Sum("units"),
        )
        .order_by("quarter__year", "quarter__quarter")
    )
    periods = [record["quarter__period"] for record in aggregated_records]
    county_sales = [record.get("total_sales") or 0 for record in aggregated_records]
    county_units = [record.get("total_units") or 0 for record in aggregated_records]

    city_records = (
        DorNaicsRecord.objects.filter(
            **base_filters,
            location__location_type="city",
        )
        .values("quarter__period", "location__name", "location__location_code")
        .annotate(
            total_sales=Sum("taxable_sales"),
            total_units=Sum("units"),
        )
        .order_by("location__location_code", "quarter__period")
    )

    city_stats: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {"name": "", "sales": defaultdict(int), "units": defaultdict(int)}
    )
    for record in city_records:
        location_code = record["location__location_code"]
        period = record["quarter__period"]
        stats = city_stats[location_code]
        stats["name"] = record["location__name"]
        stats["sales"][period] = record.get("total_sales") or 0
        stats["units"][period] = record.get("total_units") or 0

    city_totals = {
        code: sum(values["sales"].values())
        for code, values in city_stats.items()
    }
    max_cities = 8
    top_cities = sorted(
        city_totals,
        key=lambda code: city_totals[code],
        reverse=True,
    )[:max_cities]

    city_series = []
    for code in top_cities:
        stats = city_stats[code]
        label_override = DOR_LOCATION_LABEL_OVERRIDES.get(code)
        city_series.append({
            "label": label_override or stats["name"] or f"DOR Location {code}",
            "sales": [stats["sales"].get(period, 0) for period in periods],
            "units": [stats["units"].get(period, 0) for period in periods],
        })

    return {
        "periods": periods,
        "county": {
            "sales": county_sales,
            "units": county_units,
        },
        "city_series": city_series,
    }


@require_GET
def flavor_index(request):
    """Landing page for The Flavor Index and its builder tool."""

    flavor_identity, identity_version = _get_skagit_flavor_identity()
    generation_hints = flavor_identity.get("generation_hints") if isinstance(flavor_identity, dict) else {}
    flavor_targets = generation_hints.get("flavor_targets") if isinstance(generation_hints, dict) else {}

    hero_stats: List[Dict[str, Any]] = []
    for flavor in HERO_FLAVORS:
        intensity = float(flavor_targets.get(flavor) or 0.0)
        hero_stats.append(
            {
                "label": flavor.capitalize(),
                "value": round(intensity * 100),
                "display": "",
                "suffix": "%",
                "caption": "",
            }
        )
    review_count = Review.objects.count()
    menu_item_count = MenuItem.objects.count()
    hero_stats.extend(
        [
            {
                "label": "Reviews analyzed",
                "value": None,
                "display": intcomma(review_count),
                "suffix": "",
                "caption": "Total diner reviews inside the flavor corpus.",
            },
            {
                "label": "Menu items traced",
                "value": None,
                "display": intcomma(menu_item_count),
                "suffix": "",
                "caption": "Individual dishes captured across menus.",
            },
        ]
    )

    recent_entries = list(SkagitDishIdea.objects.order_by("-created_at")[:8])
    serialized_gallery = [_serialize_dish_entry(entry) for entry in recent_entries]
    latest_serialized = serialized_gallery[0] if serialized_gallery else None

    context = _basic_page_context(
        "The Flavor Index · OpenSkagit",
        "Skagit Valley's flavor identity, built from public menus and aggregated review patterns.",
    )
    context.update(
        {
            "hero_stats": hero_stats,
            "flavor_identity": flavor_identity or {},
            "flavor_identity_version": identity_version,
            "latest_dish": latest_serialized,
            "recent_dishes": serialized_gallery,
            "identity_available": bool(flavor_identity),
            "default_creative_bias": 48,
        }
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/flavor_index.html", context)


@require_POST
def build_skagit_dish(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    raw_bias = payload.get("creative_bias")
    try:
        creative_bias_value = int(raw_bias if raw_bias is not None else 50)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Set the classic-to-creative slider first."}, status=400)
    creative_bias_value = max(0, min(100, creative_bias_value))
    creative_band = _creative_band_for_value(creative_bias_value)

    flavor_identity, identity_version = _get_skagit_flavor_identity()
    if not flavor_identity:
        return JsonResponse({"error": "Flavor identity is unavailable right now."}, status=503)

    identity_json = json.dumps(flavor_identity, ensure_ascii=False)
    recent_reference_entries = list(SkagitDishIdea.objects.order_by("-created_at")[:20])
    recent_reference: List[Dict[str, Any]] = []
    for entry in recent_reference_entries:
        payload = entry.payload if isinstance(entry.payload, dict) else {}
        if not payload:
            continue
        recent_reference.append(
            {
                "dish_name": payload.get("dish_name"),
                "description": payload.get("description"),
                "ingredients": payload.get("ingredients"),
                "techniques": payload.get("why_it_fits_skagit"),
            }
        )
    recent_reference_json = json.dumps(recent_reference, ensure_ascii=False)

    guardrails = (
        "This is a synthesis exercise grounded in Skagit Valley. Use only the provided identity JSON. "
        "Do not invent flavor rules outside this file. This is not a chat or free-form recipe generator. "
        "Favor familiarity unless the creative dial explicitly allows gentle risks."
    )
    prompt = (
        "You are co-designing a single dish that fits Skagit's shared flavor identity.\n"
        "Static identity JSON (authoritative, read-only):\n"
        f"{identity_json}\n\n"
        f"Creative dial: {creative_band['label']} ({creative_bias_value}/100).\n"
        f"Dial interpretation: {creative_band['prompt']}\n\n"
        f"Previous dishes to avoid repeating (names, carriers, ingredient stacks, sauces, or prep methods):\n"
        f"{recent_reference_json}\n\n"
        f"{guardrails}\n"
        "Requirements:\n"
        "- Keep umami–salty–fatty core intact and respect dominant/supporting/underrepresented flavors.\n"
        "- Use ingredient_character items as the pantry; seafood and beef should stay approachable.\n"
        "- Incorporate acceptance_push_pull guidance: avoid the avoided items, echo the favored patterns.\n"
        "- Use familiar carriers (rice, noodles, tortillas, sandwiches, bowls).\n"
        "- Honor the creative dial: Classic = zero risks, Balanced = one subtle lift, Creative Push = noticeable but approachable twist.\n"
        "- No measurements, no chef backstory, no plating prose, no markdown.\n"
        "- Dish name must be new and never reuse any provided names.\n"
        "- Never repeat the same carrier + protein + sauce combination or technique found in the previous dishes list.\n"
        "- Vary cuisines, textures, and finishing accents to keep each dish distinct.\n"
        "- Provide three concise reasons why it fits Skagit.\n"
        "- After completing the dish metadata, craft a lifelike photography prompt describing the plating, lighting, and camera treatment.\n"
        "Return exactly ONE dish following the required JSON schema."
    )

    schema = {
        "type": "object",
        "properties": {
            "dish_name": {"type": "string", "description": "Unique, Skagit-ready dish name."},
            "description": {
                "type": "string",
                "description": "Two to three sentences describing the dish and how it eats.",
            },
            "why_it_fits_skagit": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
            },
            "ingredients": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 5,
            },
            "confidence_notes": {
                "type": "object",
                "properties": {
                    "flavor_alignment": {"type": "string"},
                    "familiarity_alignment": {"type": "string"},
                    "local_alignment": {"type": "string"},
                },
                "required": [
                    "flavor_alignment",
                    "familiarity_alignment",
                    "local_alignment",
                ],
                "additionalProperties": False,
            },
            "creative_profile": {
                "type": "string",
                "description": "Short statement describing how the creative dial influenced the dish.",
            },
            "image_prompt": {
                "type": "string",
                "description": "Detailed prompt describing the finished dish for photorealistic image generation.",
            },
        },
        "required": [
            "dish_name",
            "description",
            "why_it_fits_skagit",
            "ingredients",
            "confidence_notes",
            "creative_profile",
            "image_prompt",
        ],
        "additionalProperties": False,
    }

    def _log_openai_http_error(prefix: str, error: Exception) -> None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        body = None
        if response is not None:
            try:
                body = response.text
            except Exception:  # pragma: no cover - defensive
                try:
                    body = response.content
                except Exception:  # pragma: no cover - defensive
                    body = "<unable to read body>"
        logger.error("%s (status=%s): %s", prefix, status, body)

    try:
        client = llm.get_openai_client()
        model_name = getattr(settings, "OPENAI_SKAGIT_DISH_MODEL", "gpt-5-nano")
        response = client.responses.create(
            model=model_name,
            instructions="Return JSON only. No markdown. No explanation.",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "skagit_dish",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
    except httpx.HTTPStatusError as exc:
        _log_openai_http_error("Skagit dish OpenAI request failed via httpx", exc)
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)
    except llm.OpenAIError as exc:
        _log_openai_http_error("Skagit dish OpenAI client error", exc)
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)
    except Exception:
        logger.exception("Unexpected error during Skagit dish generation")
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)

    if getattr(response, "refusal", None):  # pragma: no cover - defensive
        logger.warning("Skagit dish request refused: %s", response.refusal)
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)

    raw_text = getattr(response, "output_text", "") or ""
    if not raw_text:
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)

    try:
        dish_payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("LLM did not return valid JSON")
        return JsonResponse({"error": "Couldn't finish cooking that dish. Try again."}, status=502)

    dish_payload.setdefault("creative_profile", creative_band["label"])
    dish_payload.setdefault("direction", creative_band["label"])
    dish_payload["creative_bias_value"] = creative_bias_value
    image_prompt = dish_payload.get("image_prompt")

    entry = SkagitDishIdea.objects.create(
        direction=creative_band["label"],
        identity_version=identity_version,
        payload=dish_payload,
    )

    _generate_and_store_dish_image(entry, image_prompt)

    serialized = _serialize_dish_entry(entry)
    generated_at = serialized.get("generated_at")
    if isinstance(generated_at, dt.datetime):
        serialized["generated_at"] = generated_at.isoformat()
    serialized["identity_version"] = identity_version

    return JsonResponse({"dish": serialized})


def _build_menu_profile_rows(restaurants):
    profile_rows = []
    for restaurant in restaurants:
        profile = restaurant.menu_profile_v1 or {}
        item_count = int(profile.get("item_count") or 0)
        if item_count <= 0:
            continue
        centroid_source = profile.get("flavor_centroid") or {}
        centroid = {key: float(centroid_source.get(key, 0.0)) for key in FLAVOR_DIMENSIONS}
        profile_rows.append(
            {
                "restaurant": restaurant,
                "item_count": item_count,
                "centroid": centroid,
                "avg_familiarity": float(profile.get("avg_familiarity") or 0.0),
                "local_signal_rate": float(profile.get("local_signal_rate") or 0.0),
                "technique_diversity": float(profile.get("technique_diversity") or 0.0),
            }
        )
    return profile_rows


def _weighted_flavor_centroid(profile_rows, total_items):
    if not total_items:
        return {key: 0.0 for key in FLAVOR_DIMENSIONS}
    totals = {key: 0.0 for key in FLAVOR_DIMENSIONS}
    for row in profile_rows:
        for flavor in FLAVOR_DIMENSIONS:
            totals[flavor] += row["centroid"].get(flavor, 0.0) * row["item_count"]
    return {key: totals[key] / total_items for key in FLAVOR_DIMENSIONS}


def _weighted_average(profile_rows, field_name, total_items):
    if not total_items:
        return 0.0
    numerator = sum(row[field_name] * row["item_count"] for row in profile_rows)
    return numerator / total_items if total_items else 0.0


def _build_valley_annotations(county_flavor_display):
    annotation_copy = [
        ("sweet", "Sweet", "Berry farms meet kitchen creativity"),
        ("umami", "Umami", "Salish Sea influence runs deep"),
        ("spicy", "Spicy", "We don't chase heat"),
        ("fatty", "Fatty", "Comfort-forward cooking"),
        ("herbal", "Herbal", "Subtle but persistent"),
    ]
    annotations = []
    for key, label, description in annotation_copy:
        score_value = county_flavor_display.get(key, 0)
        annotations.append(
            {
                "label": label,
                "score": f"{score_value}%",
                "description": description,
            }
        )
    return annotations


def _calculate_city_profiles(profile_rows):
    city_profiles = {}
    for row in profile_rows:
        city_label = (row["restaurant"].city or "Unincorporated Skagit").strip() or "Unincorporated Skagit"
        entry = city_profiles.get(city_label)
        if not entry:
            entry = {
                "item_count": 0,
                "restaurant_count": 0,
                "flavor_totals": {key: 0.0 for key in FLAVOR_DIMENSIONS},
            }
            city_profiles[city_label] = entry
        entry["item_count"] += row["item_count"]
        entry["restaurant_count"] += 1
        for flavor in FLAVOR_DIMENSIONS:
            entry["flavor_totals"][flavor] += row["centroid"].get(flavor, 0.0) * row["item_count"]

    for city, data in city_profiles.items():
        totals = data.pop("flavor_totals")
        if data["item_count"]:
            data["centroid"] = {
                flavor: totals[flavor] / data["item_count"] for flavor in FLAVOR_DIMENSIONS
            }
        else:
            data["centroid"] = {flavor: 0.0 for flavor in FLAVOR_DIMENSIONS}
        city_profiles[city] = data
    return city_profiles


def _derive_city_leaders(city_profiles, county_centroid):
    leaders = {}
    for flavor in ("herbal", "umami", "spicy"):
        candidate = _city_leader(city_profiles, flavor, county_centroid)
        if candidate:
            leaders[flavor] = candidate
    return leaders


def _city_leader(city_profiles, flavor, county_centroid):
    best_city = None
    best_score = None
    for city, data in city_profiles.items():
        if data["item_count"] < MIN_CITY_ITEMS_FOR_LEADER:
            continue
        score = data["centroid"].get(flavor, 0.0)
        if best_score is None or score > best_score:
            best_city = city
            best_score = score
    if best_city is None:
        return None
    return {
        "name": best_city,
        "score": best_score,
        "county_avg": county_centroid.get(flavor, 0.0),
    }


def _build_map_callouts(city_leaders):
    callouts = []
    herbal = city_leaders.get("herbal")
    if herbal:
        callouts.append(
            {
                "title": f"{herbal['name']}: Herbal Hotspot",
                "description": (
                    f"Average herbal score: {herbal['score']:.2f} "
                    f"(vs {herbal['county_avg']:.2f} county average)"
                ),
            }
        )
    umami = city_leaders.get("umami")
    if umami:
        callouts.append(
            {
                "title": f"{umami['name']}: Umami Central",
                "description": (
                    f"Average umami score: {umami['score']:.2f} "
                    "— the deepest concentration in Skagit."
                ),
            }
        )
    spicy = city_leaders.get("spicy")
    if spicy:
        callouts.append(
            {
                "title": f"{spicy['name']}: Unexpected Spice",
                "description": (
                    f"Average spice score: {spicy['score']:.2f} "
                    f"(vs {spicy['county_avg']:.2f} county average)"
                ),
            }
        )
    return callouts


def _select_character_restaurants(profile_rows, county_centroid, comfort_percentage, local_percentage):
    if not profile_rows:
        return []
    enriched_rows = []
    for row in profile_rows:
        centroid = row["centroid"]
        dominant_flavor, dominant_score = max(centroid.items(), key=lambda item: item[1])
        avg_flavor = statistics.mean(centroid.values()) if centroid else 0.0
        balance_score = sum(abs(centroid[key] - county_centroid.get(key, 0.0)) for key in FLAVOR_DIMENSIONS)
        enriched_rows.append(
            {
                **row,
                "dominant_flavor": dominant_flavor,
                "dominant_score": dominant_score,
                "dominance": (dominant_score / avg_flavor) if avg_flavor else 0.0,
                "balance_score": balance_score,
            }
        )

    def pick_candidate(key_func, *, reverse=True, condition=None):
        candidates = [
            row for row in enriched_rows if row["restaurant"].id not in used_ids and (condition(row) if condition else True)
        ]
        if not candidates:
            return None
        return max(candidates, key=key_func) if reverse else min(candidates, key=key_func)

    def describe_location(restaurant):
        if restaurant.city:
            return f"📍 {restaurant.city}"
        return "📍 Across Skagit"

    def build_card(row, personality, description, signature, focus):
        return {
            "name": row["restaurant"].name,
            "personality": personality,
            "description": description,
            "signature_moves": signature,
            "location": describe_location(row["restaurant"]),
            "focus": focus,
            "dominant_flavor": row["dominant_flavor"],
            "dominant_percent": f"{row['dominant_score'] * 100:.0f}%",
            "icon": FLAVOR_EMOJIS.get(row["dominant_flavor"], "⬤"),
        }

    characters = []
    used_ids = set()

    comfort = pick_candidate(lambda row: row["avg_familiarity"])
    if comfort:
        characters.append(
            build_card(
                comfort,
                "The Comfort Champion",
                (
                    f"With a familiarity score of {comfort['avg_familiarity']:.2f}, this is where Skagit goes "
                    f"when it wants to taste home. County comfort level averages {comfort_percentage}%."
                ),
                "Slow braises, crowd-pleasing sauces, confident service",
                "Highest familiarity countywide",
            )
        )
        used_ids.add(comfort["restaurant"].id)

    explorer = pick_candidate(
        lambda row: row["technique_diversity"],
        condition=lambda row: row["avg_familiarity"] < 0.75,
    )
    if explorer:
        characters.append(
            build_card(
                explorer,
                f"The Adventurous {explorer['dominant_flavor'].title()} Explorer",
                (
                    "While most of Skagit plays it safe, this kitchen leans into bold techniques "
                    "and layered flavors without losing balance."
                ),
                "Fermentation, high-acid balancing, playful plating",
                f"Technique diversity: {explorer['technique_diversity']:.2f}",
            )
        )
        used_ids.add(explorer["restaurant"].id)

    for flavor, personality, focus_text in [
        ("herbal", "The Herbal Specialist", "Garden-forward builds"),
        ("umami", "The Umami Master", "Depth from sea and soil"),
        ("spicy", "The Spice Outlier", "Heat corridor hero"),
        ("sweet", "The Sweet Specialist", "Fruit-led comfort"),
    ]:
        candidate = pick_candidate(lambda row, key=flavor: row["centroid"].get(key, 0.0), condition=None)
        if candidate:
            focus = (
                f"{flavor.capitalize()} score {candidate['centroid'][flavor]:.2f} "
                f"(county avg {county_centroid.get(flavor, 0.0):.2f})"
            )
            characters.append(
                build_card(
                    candidate,
                    personality,
                    f"This is where {flavor} stops being garnish and becomes the point.",
                    "Seasonal sourcing, precise layering, confident restraint",
                    focus,
                )
            )
            used_ids.add(candidate["restaurant"].id)
            if len(characters) >= 8:
                break

    local_champ = pick_candidate(lambda row: row["local_signal_rate"], condition=lambda row: row["local_signal_rate"] > 0.15)
    if local_champ and len(characters) < 8:
        characters.append(
            build_card(
                local_champ,
                "The Local Champion",
                (
                    f"Only {local_percentage}% of county menu items explicitly signal local sourcing, "
                    f"but this restaurant hits {(local_champ['local_signal_rate'] * 100):.0f}%."
                ),
                "Farm partnerships, seasonal menus, provenance on the menu",
                "Local-first menu signals",
            )
        )
        used_ids.add(local_champ["restaurant"].id)

    balanced = pick_candidate(lambda row: row["balance_score"], reverse=False)
    if balanced and len(characters) < 8:
        characters.append(
            build_card(
                balanced,
                "The Neighborhood Anchor",
                "Statistically average on every axis—which makes it the taste of home.",
                "Consistent execution, beloved staples, dependable warmth",
                "Closest match to county flavor centroid",
            )
        )
        used_ids.add(balanced["restaurant"].id)

    return characters[:8]


def _generate_restaurant_geojson(profile_rows):
    features = []
    for row in profile_rows:
        restaurant = row["restaurant"]
        lat = restaurant.latitude
        lon = restaurant.longitude
        if lat is None or lon is None:
            continue
        centroid = row["centroid"]
        dominant_flavor, dominant_score = max(centroid.items(), key=lambda item: item[1])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": restaurant.name,
                    "city": restaurant.city,
                    "dominant_flavor": dominant_flavor,
                    "dominant_score": round(dominant_score, 3),
                    "flavor_centroid": centroid,
                    "familiarity": row["avg_familiarity"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@require_GET
def sales_search(request):
    """
    Answer-first sales intelligence page with opinionated modes.
    """
    mode = (request.GET.get("mode") or "pulse").lower()
    if mode not in {"pulse", "compare", "signals"}:
        mode = "pulse"

    if mode == "compare":
        payload = _compare_place_context(request.GET.get("q") or "")
    elif mode == "signals":
        payload = _signals_mode_context()
    else:
        payload = _market_pulse_context()

    nav = [
        {"key": "pulse", "label": "Market Pulse", "description": "Default", "active": mode == "pulse"},
        {"key": "compare", "label": "Compare a Place", "description": "Single input", "active": mode == "compare"},
        {"key": "signals", "label": "Outliers & Signals", "description": "Anomalies", "active": mode == "signals"},
    ]

    context = {
        "mode": mode,
        "mode_nav": nav,
    }
    context.update(payload)
    context.setdefault("rows", [])
    context.setdefault("table_caption", "No sales available yet.")
    context.setdefault("metrics", [])
    context.setdefault("secondary_metrics", [])
    context.setdefault("needs_query", False)

    return render(request, "openskagit/sales_search.html", context)


@require_GET
def sales_compare_search(request):
    query = (request.GET.get("q") or request.GET.get("value") or "").strip()
    results = []
    if query:
        results = list(
            Parcel.objects.filter(
                Q(parcel_number__istartswith=query) | Q(address__icontains=query)
            )[:10]
        )
    return render(
        request,
        "partials/compare_search_results.html",
        {"query": query, "results": results},
    )


@require_GET
def sales_search_row(request, sale_id: int):
    """
    Return a small detail drawer for a single sale.
    """
    sale = get_object_or_404(
        SalesSearch.objects.annotate(
            price_per_sqft=Case(
                When(living_area__gt=0, then=F("sale_price") / F("living_area")),
                default=Value(None),
                output_field=FloatField(),
            ),
            price_per_acre=Case(
                When(lot_size_acres__gt=0, then=F("sale_price") / F("lot_size_acres")),
                default=Value(None),
                output_field=FloatField(),
            ),
        ),
        sale_id=sale_id,
    )
    parcel = (
        MasterParcel.objects.select_related("geometry", "parcelplanningfacts")
        .filter(parcel_number=sale.parcel_number)
        .first()
    )
    planning = None
    if parcel:
        try:
            planning = parcel.parcelplanningfacts
        except Exception:
            planning = None

    geometry = None
    if parcel:
        try:
            geometry = parcel.geometry
        except Exception:
            geometry = None

    recent_sales = (
        SalesSearch.objects.filter(parcel_number=sale.parcel_number)
        .exclude(sale_id=sale.sale_id)
        .order_by("-sale_date", "-sale_id")[:5]
    )
    return render(
        request,
        "partials/sales_row_detail.html",
        {
            "sale": sale,
            "parcel": parcel,
            "planning": planning,
            "geometry": geometry,
            "recent_sales": recent_sales,
        },
    )


@require_GET
def sales_search_export(request):
    """
    CSV export of the current sales search filters (capped for safety).
    """
    qs, _, _ = _build_sales_search_queryset(request)
    qs = qs[:SALES_SEARCH_EXPORT_LIMIT]

    timestamp = dt.datetime.now().strftime("%Y%m%d")
    filename = f"sales_search_{timestamp}.csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "sale_id",
            "parcel_number",
            "sale_date",
            "sale_price",
            "market_value",
            "assessed_value",
            "sale_to_market_ratio",
            "price_per_sqft",
            "price_per_acre",
            "living_area",
            "lot_size_acres",
            "zoning_jurisdiction",
            "zone_id",
            "ratio_trim_bucket",
            "is_arms_length",
            "exclude_from_analysis",
        ]
    )

    for sale in qs:
        writer.writerow(
            [
                sale.sale_id,
                sale.parcel_number,
                sale.sale_date.isoformat() if sale.sale_date else "",
                sale.sale_price,
                sale.market_value or "",
                sale.assessed_value or "",
                sale.sale_to_market_ratio or "",
                getattr(sale, "price_per_sqft", "") or "",
                getattr(sale, "price_per_acre", "") or "",
                sale.living_area or "",
                sale.lot_size_acres or "",
                sale.zoning_jurisdiction or "",
                sale.zone_id or "",
                sale.ratio_trim_bucket or "",
                sale.is_arms_length,
                sale.exclude_from_analysis,
            ]
        )

    return response


@require_GET
def live_activity_feed(request):
    """
    Serve the recent live activity feed as JSON for the homepage widget.
    """
    limit_param = request.GET.get("limit")
    limit: Optional[int] = None
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), activity_feed.LIVE_ACTIVITY_LIMIT))
        except (TypeError, ValueError):
            limit = None

    entries = activity_feed.get_recent_activity(limit=limit)
    return JsonResponse(entries, safe=False)


@staff_member_required
@require_POST
def documents_upload(request):
    """
    Accept staff uploads and outline the next ingestion steps.
    """

    files = request.FILES.getlist("documents")
    if not files:
        return HttpResponse(
            "<p class='text-sm text-red-600'>No documents were selected. Choose one or more files to process.</p>",
            status=400,
        )

    filenames = [f.name for f in files]
    guidance = render_to_string(
        "partials/upload_status.html",
        {
            "filenames": filenames,
            "next_command": "python manage.py generate_embeddings",
        },
        request=request,
    )
    # TODO: persist files to storage and enqueue ingestion worker.
    return HttpResponse(guidance)


@staff_member_required
def api_docs(request):
    """
    Render an internal API reference for staff-only access.
    """
    endpoints = []
    for endpoint in API_ENDPOINTS:
        entry = copy.deepcopy(endpoint)
        querystring = entry.get("default_querystring") or ""
        entry["display_path"] = f"{entry['path']}?{querystring}" if querystring else entry["path"]
        if entry.get("request_example"):
            entry["payload_json"] = entry["request_example"]
            entry["payload_label"] = "Sample Request"
        elif entry.get("default_body"):
            entry["payload_json"] = entry["default_body"]
            entry["payload_label"] = "Sample Payload"
        if entry.get("sample"):
            entry["sample_json"] = json.dumps(entry["sample"], indent=2)
        endpoints.append(entry)

    canonical = request.build_absolute_uri()
    context = {
        "endpoints": endpoints,
        "endpoints_json": json.dumps(endpoints),
        "schema_sql": """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='public';
""".strip(),
        "notes": [
            "All endpoints return JSON responses designed for frontend consumption.",
            "Search endpoints default to page size 25 with optional `page` and `page_size` parameters.",
            "Pass numeric filters as query parameters (e.g. `min_value`, `max_value`, `min_acres`).",
            "Parcel detail responses are organized into sections (valuation, structure, land, sales) to minimize payload size.",
            "Sales leaderboard responses always scope to `sale_type = \"valid sale\"` and include assessor joins for comps.",
            "Sales sorting defaults to descending; set `direction=asc` or `direction=desc` to override.",
            "Semantic search requires embeddings generated in the `assessor.embedding` vector column.",
        ],
        "canonical_url": canonical,
    }
    return render(request, "openskagit/api_docs.html", context)


@staff_member_required
def api_dashboard(request):
    """
    Staff-only API playground with request builders and tooling.
    """
    endpoints = copy.deepcopy(API_ENDPOINTS)
    for endpoint in endpoints:
        if endpoint.get("default_body") and isinstance(endpoint["default_body"], str):
            # ensure JSON formatting preserved for UI defaults
            endpoint["default_body"] = endpoint["default_body"]

    context = {
        "endpoints_json": json.dumps(endpoints),
        "presets_json": json.dumps(API_PRESETS),
    }
    return render(request, "openskagit/api_dashboard.html", context)


@staff_member_required
@require_http_methods(["GET", "POST"])
def staff_tax_foreclosure_report(request):
    """
    Staff-only tax foreclosure scan page.
    Runs a fresh local candidate scan, live verifies candidates against county data,
    writes tax_status on MasterParcel, and renders a simple parcel list.
    """

    def _parse_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def _parse_decimal(raw: Any, default: Decimal, minimum: Decimal) -> Decimal:
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return default
        return value if value >= minimum else minimum

    def _parse_float(raw: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    source = request.POST if request.method == "POST" else request.GET
    tax_year = _parse_int(source.get("tax_year"), timezone.now().year, 2000, 2100)
    min_delinquent = _parse_decimal(source.get("min_delinquent"), Decimal("7500"), Decimal("0"))
    min_ratio = _parse_float(source.get("min_ratio"), 2.5, 0.0, 20.0)
    candidate_limit = _parse_int(source.get("candidate_limit"), 120, 1, 2000)
    max_workers = _parse_int(source.get("max_workers"), 6, 1, 20)
    display_limit = _parse_int(request.GET.get("display_limit"), 500, 1, 5000)
    land_use_raw = (source.get("land_use_codes") or "").strip()
    land_use_codes = [item.strip() for item in land_use_raw.split(",") if item.strip()]

    run_summary: Optional[Dict[str, Any]] = None
    if request.method == "POST":
        try:
            run_summary, _verified_rows = run_tax_foreclosure_scan_and_verify(
                tax_year=tax_year,
                min_delinquent=min_delinquent,
                min_ratio=min_ratio,
                candidate_limit=candidate_limit,
                max_workers=max_workers,
                land_use_codes=land_use_codes,
            )
            messages.success(
                request,
                (
                    f"Scan complete. candidates={run_summary['candidate_count']} "
                    f"confirmed={run_summary['confirmed_count']} "
                    f"cleared={run_summary['cleared_count']} "
                    f"errors={run_summary['error_count']} "
                    f"updated={run_summary['updated_count']}"
                ),
            )
        except Exception as exc:
            logger.exception("Staff tax foreclosure scan failed: %s", exc)
            messages.error(request, f"Scan failed: {exc}")

    status_filter = (request.GET.get("status") or TAX_STATUS_CONFIRMED_DELINQUENT).strip()
    valid_filters = {
        "all",
        TAX_STATUS_CONFIRMED_DELINQUENT,
        TAX_STATUS_NOT_DELINQUENT,
        TAX_STATUS_VERIFY_ERROR,
    }
    if status_filter not in valid_filters:
        status_filter = TAX_STATUS_CONFIRMED_DELINQUENT

    qs = MasterParcel.objects.filter(tax_status__isnull=False)
    if status_filter != "all":
        qs = qs.filter(tax_status=status_filter)

    rows = list(
        qs.order_by("parcel_number")
        .values(
            "parcel_number",
            "situs_address",
            "owner__owner_name",
            "tax_status",
            "tax_status_updated_at",
        )[:display_limit]
    )

    counts_by_status = {
        item["tax_status"]: item["count"]
        for item in (
            MasterParcel.objects.filter(tax_status__isnull=False)
            .values("tax_status")
            .annotate(count=Count("parcel_number"))
        )
    }

    context = _basic_page_context(
        "Staff Tax Foreclosure Report | OpenSkagit",
        "Staff-only report for delinquent parcel scan, live verification, and tax status.",
    )
    context.update(
        {
            "canonical_url": request.build_absolute_uri(),
            "og_url": request.build_absolute_uri(),
            "run_summary": run_summary,
            "rows": rows,
            "status_filter": status_filter,
            "display_limit": display_limit,
            "tax_year": tax_year,
            "min_delinquent": str(min_delinquent),
            "min_ratio": min_ratio,
            "candidate_limit": candidate_limit,
            "max_workers": max_workers,
            "land_use_codes_raw": land_use_raw,
            "tax_status_confirmed": TAX_STATUS_CONFIRMED_DELINQUENT,
            "tax_status_not_delinquent": TAX_STATUS_NOT_DELINQUENT,
            "tax_status_verify_error": TAX_STATUS_VERIFY_ERROR,
            "counts_by_status": counts_by_status,
        }
    )
    return render(request, "openskagit/staff_tax_foreclosure_report.html", context)


@staff_member_required
@require_GET
def staff_image_generator(request):
    """
    Staff-only image generation page. Jobs execute asynchronously and the frontend polls status.
    """
    context = _basic_page_context(
        "Staff Image Generator | OpenSkagit",
        "Internal image generation tool powered by a remote Modal deployment.",
    )
    context.update(
        {
            "canonical_url": request.build_absolute_uri(),
            "og_url": request.build_absolute_uri(),
            "form": StaffImageGeneratorForm(),
            "modal_app_name": getattr(settings, "MODAL_IMAGE_APP_NAME", "flux-generator"),
            "modal_function_name": getattr(settings, "MODAL_IMAGE_FUNCTION_NAME", "generate_image"),
            "start_url": reverse("staff-image-generator-start"),
            "poll_interval_ms": int(getattr(settings, "MODAL_IMAGE_POLL_INTERVAL_MS", 2000)),
        }
    )
    return render(request, "openskagit/staff_image_generator.html", context)


@staff_member_required
@require_POST
def staff_image_generator_start(request):
    form = StaffImageGeneratorForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "message": "Please fix the highlighted form errors and try again.",
                "errors": _serialize_form_errors(form),
            },
            status=400,
        )

    upload = form.cleaned_data.get("init_image")
    job = StaffImageGenerationJob(
        created_by=request.user,
        prompt=form.cleaned_data["prompt"],
        steps=form.cleaned_data["steps"],
        guidance_scale=form.cleaned_data["guidance_scale"],
        width=form.cleaned_data["width"],
        height=form.cleaned_data["height"],
        seed=form.cleaned_data["seed"],
        status=StaffImageGenerationJob.STATUS_PENDING,
        status_detail="Queued for generation.",
    )
    if upload is not None:
        job.init_image = upload
    job.save()
    try:
        _enqueue_staff_image_generation_job(job.id)
    except Exception as exc:
        logger.exception("Failed to queue staff image generation job %s: %s", job.id, exc)
        job.status = StaffImageGenerationJob.STATUS_FAILED
        job.status_detail = "Unable to queue generation job."
        job.error_message = str(exc).strip()[:4000] or exc.__class__.__name__
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "status_detail", "error_message", "completed_at", "updated_at"])
        return JsonResponse(
            {
                "ok": False,
                "message": "Unable to queue generation job.",
                "job_id": str(job.id),
            },
            status=500,
        )

    job_token = _build_staff_image_job_token(job)
    status_path = reverse("staff-image-generator-status", kwargs={"job_id": job.id})
    cancel_path = reverse("staff-image-generator-cancel", kwargs={"job_id": job.id})
    token_query = urlencode({"token": job_token})
    return JsonResponse(
        {
            "ok": True,
            "job_id": str(job.id),
            "job_token": job_token,
            "status_url": f"{status_path}?{token_query}",
            "cancel_url": f"{cancel_path}?{token_query}",
            "status": job.status,
            "status_detail": job.status_detail,
        }
    )


@require_GET
def staff_image_generator_status(request, job_id):
    token = (request.GET.get("token") or request.headers.get("X-Image-Job-Token") or "").strip()
    try:
        job = _run_staff_image_poll_db_call(_resolve_staff_image_job_from_token, job_id=job_id, token=token)
    except FuturesTimeoutError:
        return JsonResponse(
            {
                "ok": False,
                "message": "Timed out while loading generation status.",
            },
            status=504,
        )
    except Exception as exc:
        logger.exception("Failed to load staff image generation status for job %s: %s", job_id, exc)
        return JsonResponse(
            {
                "ok": False,
                "message": "Unable to load generation status.",
            },
            status=500,
        )
    if job is None:
        return JsonResponse(
            {
                "ok": False,
                "message": "Invalid or expired job token.",
            },
            status=403,
        )
    return JsonResponse({"ok": True, "job": _serialize_staff_image_job(job)})


@require_POST
def staff_image_generator_cancel(request, job_id):
    token = (request.GET.get("token") or request.headers.get("X-Image-Job-Token") or "").strip()
    try:
        job = _run_staff_image_poll_db_call(_cancel_staff_image_job_by_token, job_id=job_id, token=token)
    except FuturesTimeoutError:
        return JsonResponse(
            {
                "ok": False,
                "message": "Timed out while requesting cancellation.",
            },
            status=504,
        )
    except Exception as exc:
        logger.exception("Failed to cancel staff image generation job %s: %s", job_id, exc)
        return JsonResponse(
            {
                "ok": False,
                "message": "Unable to cancel generation job.",
            },
            status=500,
        )
    if job is None:
        return JsonResponse(
            {
                "ok": False,
                "message": "Invalid or expired job token.",
            },
            status=403,
        )
    return JsonResponse({"ok": True, "job": _serialize_staff_image_job(job)})


@staff_member_required
@require_GET
def sw_hub(request):
    """
    Staff-only Sedro-Woolley intelligence page backed by crawl artifacts in MEDIA_ROOT.
    """

    tag_filter = (request.GET.get("tag") or "").strip()
    query = (request.GET.get("q") or "").strip()

    dashboard = load_sw_dashboard_context(
        media_root=Path(settings.MEDIA_ROOT),
        media_url=settings.MEDIA_URL,
        tag_filter=tag_filter or None,
        query=query or None,
        limit=500,
    )

    summary = dashboard["summary"]
    manifest_rel_path = summary.get("manifest_path") if isinstance(summary, dict) else None
    summary_rel_path = summary.get("run_summary_path") if isinstance(summary, dict) else None

    context = _basic_page_context(
        "Sedro-Woolley Staff Hub | OpenSkagit",
        "Staff-only Sedro-Woolley data hub across crawl, ingest, and legal code sources.",
    )
    context.update(
        {
            "summary": dashboard.get("summary", {}),
            "latest_run": dashboard.get("latest_run", {}),
            "records": dashboard.get("records", []),
            "available_tags": dashboard.get("available_tags", []),
            "category_stats": dashboard.get("category_stats", {}),
            "pipeline_summary": dashboard.get("pipeline_summary", {}),
            "legal_summary": dashboard.get("legal_summary", {}),
            "legal_records": dashboard.get("legal_records", []),
            "legal_jurisdictions": dashboard.get("legal_jurisdictions", []),
            "has_data": dashboard.get("has_data", False),
            "selected_tag": tag_filter,
            "query": query,
            "media_root": str(settings.MEDIA_ROOT),
            "manifest_absolute_path": str(Path(settings.MEDIA_ROOT) / manifest_rel_path) if manifest_rel_path else "",
            "run_summary_absolute_path": str(Path(settings.MEDIA_ROOT) / summary_rel_path) if summary_rel_path else "",
        }
    )
    return render(request, "openskagit/sw_hub.html", context)


def _build_cma_context(request, parcel_number: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = params or request.GET
    parcel_state = _get_parcel_state(request, parcel_number)
    filters = cma.parse_filters_from_request(params)
    sort_field, sort_direction = _current_sort(
        request,
        parcel_state,
        params.get("sort_field"),
        params.get("sort_direction"),
    )
    limit = _parse_limit(params.get("limit"))
    raw_view_mode = (params.get("view_mode") or "").strip().lower()
    advanced_mode = raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"}
    view_mode = "advanced" if advanced_mode else "standard"

    excluded = parcel_state.get("excluded", [])

    rollup_cache: Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, object]] = {}

    try:
        subject = cma.load_subject(parcel_number, rollup_cache=rollup_cache)
    except ValueError as exc:
        return {"error": str(exc)}

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        excluded=excluded,
        sort_field=sort_field,
        sort_direction=sort_direction,
        limit=limit,
        load_improvements=advanced_mode,
        rollup_cache=rollup_cache,
    )
    for comparable in computation.comparables:
        setattr(comparable, "adjustment_payload", None)

    advanced_payload: Optional[Dict[str, Any]] = None
    advanced_error: Optional[str] = None
    advanced_summary: Optional[Dict[str, Any]] = None
    if advanced_mode:
        advanced_payload, advanced_error = _compute_adjustment_summary(subject, computation.comparables)
        if advanced_payload:
            comp_map = {item["comp_id"]: item for item in advanced_payload.get("comparables", [])}
            for comparable in computation.comparables:
                comparable.adjustment_payload = comp_map.get(comparable.snapshot.parcel_number)
            advanced_summary = {
                "subject_pred_price": advanced_payload.get("subject_pred_price"),
                "market_group": advanced_payload.get("market_group"),
            }

    return {
        "subject": computation.subject,
        "comparables": computation.comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "excluded": excluded,
        "markers": computation.marker_payloads(),
        "limit": limit,
        "view_mode": view_mode,
        "advanced_mode": advanced_mode,
        "advanced_summary": advanced_summary,
        "advanced_error": advanced_error,
        "adjustment_labels": ADJUSTMENT_LABELS,
        "error": None,
    }


@require_GET
def cma_dashboard_view(request, parcel_number: Optional[str] = None):
    context: Dict[str, Any] = {"parcel_number": parcel_number}
    if parcel_number:
        detail_context = _build_cma_context(request, parcel_number)
        context.update(detail_context)
        if not request.headers.get("HX-Request"):
            subject = detail_context.get("subject")
            if subject:
                activity_feed.log_activity(
                    "comparison",
                    "Finding Comparisons for",
                    subject.address or parcel_number,
                )
    template_name = "openskagit/cma/dashboard.html"
    if request.headers.get("HX-Request"):
        template_name = "openskagit/cma/partials/dashboard_content.html"
    return render(request, template_name, context)


@require_GET
def cma_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        sale_subquery = (
            Sales.objects.filter(parcel_number=OuterRef("parcel_number"))
            .order_by("-sale_date")
        )
        qs = (
            MasterParcel.objects
            .annotate(latest_sale_date=Subquery(sale_subquery.values("sale_date")[:1]))
            .filter(
                Q(parcel_number__istartswith=query)
                | Q(situs_address__icontains=query)
            )
            .order_by("parcel_number")
        )
        results = list(qs[:15])
        for parcel in results:
            setattr(parcel, "address", getattr(parcel, "situs_address", None))
            setattr(parcel, "sale_date", getattr(parcel, "latest_sale_date", None))

    return render(
        request,
        "openskagit/cma/partials/parcel_search_results.html",
        {"query": query, "results": results},
    )



@require_GET
def cma_comparison_grid(request, parcel_number: str):
    context = _build_cma_context(request, parcel_number)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_comparable_improvements(request, parcel_number: str, comp_parcel: str):
    improvements = cma.get_improvement_rollup(
        comp_parcel,
    )

    return render(
        request,
        "openskagit/cma/partials/comparable_improvement_info.html",
        {"improvements": improvements},
    )


@require_POST
def cma_toggle_comparable(request, parcel_number: str, comp_parcel: str):
    _toggle_comparable_inclusion(request, parcel_number, comp_parcel)
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_map_data(request, parcel_number: str):
    params = _merge_request_params(request)
    filters = cma.parse_filters_from_request(params)
    try:
        subject = cma.load_subject(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    comparables = cma.fetch_sales_within_view(subject, filters)
    subject_marker = []
    subject_point = subject.display_point()
    if subject_point:
        subject_marker = [
            {
                "parcel_number": subject.parcel_number,
                "lat": subject_point.y,
                "lon": subject_point.x,
                "address": subject.address,
                "type": "subject",
            }
        ]
    markers = subject_marker + [dict(marker, **{"type": "comparable"}) for marker in comparables]
    return render(
        request,
        "openskagit/cma/partials/map_payload.html",
        {"markers": markers},
    )


@login_required
@require_POST
def cma_save_analysis(request, parcel_number: str):
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])

    comparables = context.get("comparables", [])
    if not comparables:
        return HttpResponseBadRequest("At least one comparable is required.")

    analysis_record = CmaAnalysis.objects.create(
        user=request.user,
        subject_parcel=context["subject"].parcel_number,
        subject_snapshot=context["subject"].as_dict(),
        filters=context["filters"].as_dict(),
        manual_adjustments={},
    )

    for comp in comparables:
        CmaComparableSelection.objects.create(
            analysis=analysis_record,
            parcel_number=comp.snapshot.parcel_number,
            included=True,
            rank=comp.inclusion_rank,
            raw_sale_price=comp.sale_price,
            adjusted_sale_price=comp.sale_price,
            gross_percentage_adjustment=Decimal("0"),
            auto_adjustments=[],
            manual_adjustments={},
            metadata=comp.snapshot.as_dict(),
        )

    share_url = request.build_absolute_uri(reverse("cma-share", args=[analysis_record.share_uuid]))
    return render(
        request,
        "openskagit/cma/partials/save_success.html",
        {"share_url": share_url},
    )


@require_GET
def cma_share(request, share_uuid):
    analysis_record = get_object_or_404(CmaAnalysis, share_uuid=share_uuid)
    filters = cma.filters_from_dict(analysis_record.filters)

    try:
        subject = cma.load_subject(analysis_record.subject_parcel)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        excluded=[],
        sort_field="score",
        sort_direction="desc",
        limit=cma.MAX_COMPARABLE_LIMIT,
    )

    saved_rankings = {
        comp.parcel_number: comp.rank for comp in analysis_record.comparables.all().order_by("rank")
    }
    comparables = [
        comp
        for comp in computation.comparables
        if comp.snapshot.parcel_number in saved_rankings
    ]
    for comp in comparables:
        comp.inclusion_rank = saved_rankings.get(comp.snapshot.parcel_number, comp.inclusion_rank)
    comparables.sort(key=lambda item: item.inclusion_rank)

    context = {
        "parcel_number": analysis_record.subject_parcel,
        "subject": computation.subject,
        "comparables": comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "shared_analysis": analysis_record,
        "share_mode": True,
        "markers": computation.marker_payloads(),
    }
    return render(request, "openskagit/cma/dashboard.html", context)


# ------------------------------
# Citizen Appeal Helper (simple)
# ------------------------------

APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 3


@require_GET
def appeal_home(request):
    """
    Minimal, citizen-friendly entry with a single address/parcel search box.
    """
    canonical_url = request.build_absolute_uri()
    context = _basic_page_context(
        "Parcel Partner · Find Your Property",
        "Search Skagit County parcels by address or parcel number to start the Parcel Partner workflow.",
    )
    context.update(
        {
            "step": 1,
            "og_title": "Parcel Partner · Find Your Property",
            "og_url": canonical_url,
            "canonical_url": canonical_url,
            "portal_badge": "OpenSkagit Parcel Partner",
            "show_stepper": True,
        }
    )
    return render(
        request,
        "openskagit/appeal_home_v3.html",
        context,
    )

APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 3

@require_GET
def appeal_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < APPEAL_MIN_QUERY_LENGTH
    results = []
    source = (request.GET.get("source") or "appeal").strip()
    include_sale_price = source not in {"alert"}

    if not query_too_short:
        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        qs = Parcel.objects.filter(property_type="R")
        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        qs = (
            qs.exclude(address__isnull=True)
            .exclude(address__exact="")
            .exclude(address__icontains="nan")
        )

        if include_sale_price:
            latest_sale_price = (
                Sales.objects.filter(parcel_number=OuterRef("parcel_number"))
                .order_by("-sale_date", "-id")
                .values("sale_price")[:1]
            )
            results = (
                qs.annotate(sale_price=Subquery(latest_sale_price))
                .order_by("parcel_number")[:APPEAL_SEARCH_LIMIT]
            )
        else:
            results = (
                qs.only("parcel_number", "address", "neighborhood_code")
                .order_by("parcel_number")[:APPEAL_SEARCH_LIMIT]
            )

    return render(
        request,
        "openskagit/appeal_parcel_search_results_v3.html",
        {
            "query": query,
            "results": results,
            "query_too_short": query_too_short,
            "min_search_length": APPEAL_MIN_QUERY_LENGTH,
            "source": source,
        },
    )


# ------------------------------
# Parcel Tax Breakdown Tool
# ------------------------------

TAX_SEARCH_LIMIT = 15
TAX_MIN_QUERY_LENGTH = 3


@require_GET
def tax_levy_home(request):
    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "openskagit/tax_levy_home.html",
        {
            "meta_description": "Review your parcel tax history over time and compare neighborhood fairness metrics.",
            "page_title": "Taxes · Parcel History & Fairness",
            "og_title": "Taxes · Parcel History & Fairness",
            "og_url": canonical_url,
            "canonical_url": canonical_url,
        },
    )


@require_GET
def tax_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < TAX_MIN_QUERY_LENGTH
    results = []

    if not query_too_short:
        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        qs = Parcel.objects.all()
        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        latest_sale_price = (
            Sales.objects.filter(parcel_number=OuterRef("parcel_number"))
            .order_by("-sale_date", "-id")
            .values("sale_price")[:1]
        )

        results = (
            qs.exclude(address__isnull=True)
              .exclude(address__exact="")
              .exclude(address__icontains="nan")
              .annotate(sale_price=Subquery(latest_sale_price))
              .order_by("parcel_number")[:TAX_SEARCH_LIMIT]
        )

    return render(
        request,
        "openskagit/tax_parcel_search_results.html",
        {
            "query": query,
            "results": results,
            "query_too_short": query_too_short,
            "min_search_length": TAX_MIN_QUERY_LENGTH,
        },
    )


@require_GET
def appeal_result(request, parcel_number: str):
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    subject_meta = getattr(subject, "metadata", {}) or {}
    neighborhood = {
        "code": subject_meta.get("neighborhood_code"),
        "name": subject_meta.get("neighborhood"),
    }
    subject_year_built = subject.year_built or subject.effective_year_built

    comparables_url = request.path + "comparables/"
    parcel_history_points = _parcel_value_history(parcel_number)
    neighborhood_analysis_url = request.path + "neighborhood-analysis/"
    # Planning dossier temporarily hidden.
    # Keep backend hooks in place for easy re-enable later.
    # planning = (
    #     ParcelPlanningFacts.objects.only(*PLANNING_DOSSIER_FIELDS)
    #     .filter(parcel__parcel_number=parcel_number)
    #     .first()
    # )
    # waterfacts = None
    # if PLANNING_DOSSIER_WATER_FIELDS:
    #     waterfacts = (
    #         ParcelWaterfacts.objects.only(*PLANNING_DOSSIER_WATER_FIELDS)
    #         .filter(parcel__parcel_number=parcel_number)
    #         .first()
    #     )
    # planning_sections = build_planning_dossier_sections(planning, waterfacts)

    return render(
        request,
        "openskagit/appeal_results_v3.html",
        {
            "subject": subject,
            "parcel_number": parcel_number,
            "neighborhood": neighborhood,
            "subject_year_built": subject_year_built,
            "comparables_url": comparables_url,
            "neighborhood_analysis_url": neighborhood_analysis_url,
            "parcel_history_points": parcel_history_points,
            "step": 2,
            "meta_description": f"Review parcel {parcel_number} assessments, fairness diagnostics, and comparable sales in Parcel Partner.",
            "page_title": f"Parcel Partner · Parcel {parcel_number}",
            "og_title": f"Parcel Partner · Parcel {parcel_number}",
            "og_url": request.build_absolute_uri(),
        },
    )


@require_GET
def appeal_result_neighborhood_analysis(request, parcel_number: str):
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    neighborhood = appeals.get_subject_neighborhood_snapshot(subject)
    neighborhood_geom_geojson = None
    if neighborhood and neighborhood.get("code"):
        try:
            geom = NeighborhoodGeom.objects.get(code=neighborhood["code"])
            neighborhood_geom_geojson = json.loads(geom.geom_4326.geojson)
        except NeighborhoodGeom.DoesNotExist:
            neighborhood_geom_geojson = None

    return render(
        request,
        "openskagit/partials/appeal_neighborhood_analysis_content.html",
        {
            "subject": subject,
            "neighborhood": neighborhood,
            "neighborhood_geom_geojson": neighborhood_geom_geojson,
        },
    )


def _build_appeal_map_payload(
    subject: cma.PropertySnapshot,
    comparables: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    subject_payload = {
        "address": getattr(subject, "address", None),
        "lat": _safe_float_value(getattr(subject, "latitude", None)),
        "lon": _safe_float_value(getattr(subject, "longitude", None)),
    }
    comp_payloads: List[Dict[str, Any]] = []
    for comp in comparables:
        lat = _safe_float_value(comp.get("latitude"))
        lon = _safe_float_value(comp.get("longitude"))
        if lat is None or lon is None:
            continue
        sale_date = comp.get("sale_date")
        sale_date_display = sale_date.strftime("%b %d, %Y") if hasattr(sale_date, "strftime") else ""
        comp_payloads.append(
            {
                "parcel_number": comp.get("parcel_number"),
                "address": comp.get("address"),
                "lat": lat,
                "lon": lon,
                "sale_price": _safe_float_value(comp.get("sale_price")),
                "sale_date_display": sale_date_display,
                "distance_miles": _safe_float_value(comp.get("distance_miles")),
                "bedrooms": _safe_float_value(comp.get("bedrooms")),
                "bathrooms": _safe_float_value(comp.get("bathrooms")),
                "sqft": _safe_float_value(comp.get("calculated_square_footage") or comp.get("living_area")),
                "missing_bedrooms": bool(comp.get("missing_bedrooms")),
                "adjusted_price": _safe_float_value(comp.get("adjusted_price")),
                "total_adjustment": _safe_float_value(comp.get("total_adjustment")),
            }
        )
    return {
        "subject": subject_payload,
        "comparables": comp_payloads,
    }


def _build_appeal_comparables_display_context(
    *,
    subject: cma.PropertySnapshot,
    comparables: Sequence[cma.ComparableResult],
    display_limit: int,
    sort_by: str,
    sort_direction: str,
    advanced_mode: bool,
    radius_used: Optional[float],
    allow_widen_pass: bool,
    parcel_number: str,
    debug_flag: bool = False,
) -> Dict[str, Any]:
    subject_meta = getattr(subject, "metadata", {}) or {}
    subject_area = _safe_float_value(getattr(subject, "living_area", None))
    subject_lot = _safe_float_value(
        getattr(subject, "acres", None)
        or getattr(subject, "lot_acres", None)
        or subject_meta.get("lot_acres")
    )
    subject_quality = subject_meta.get("quality_score")
    subject_condition = subject_meta.get("condition_score")

    advanced_error: Optional[str] = None
    advanced_summary: Optional[Dict[str, Any]] = None
    advanced_ready = False
    valuation_date_for_adjustments: Optional[dt.date] = None
    subject_adjustment_features: Dict[str, Optional[float]] = {}
    adjustment_coefficients: Dict[str, Any] = {}
    if advanced_mode:
        try:
            advanced_summary = build_adjustment_support_v1(
                subject,
                months_lookback=24,
                min_sample_target=30,
                debug=debug_flag,
            )
            if advanced_summary.get("status") == "error":
                advanced_error = advanced_summary.get("error") or "Advanced analysis failed."
            else:
                advanced_summary = _decorate_adjustment_support_summary(advanced_summary)
        except Exception as exc:  # pragma: no cover - defensive safeguard
            logger.exception("Adjustment support failed for parcel %s", parcel_number)
            advanced_error = str(exc) or "Advanced analysis failed."
            advanced_summary = {
                "model_version": "adjustment_support_v1",
                "status": "error",
                "not_enough_sales": False,
                "suppressed": False,
                "warnings": [],
            }

    if advanced_mode and advanced_summary and advanced_summary.get("status") == "ready":
        advanced_ready = True
        valuation_date_for_adjustments = _adjustment_support_valuation_date(subject, advanced_summary)
        subject_adjustment_features = _adjustment_support_subject_features(
            subject,
            valuation_date_for_adjustments,
        )
        adjustment_coefficients = advanced_summary.get("coefficient_estimates") or {}

    def _comp_calc_square_footage(comp_result: cma.ComparableResult) -> Optional[float]:
        snapshot = getattr(comp_result, "snapshot", None)
        comp_meta = getattr(snapshot, "metadata", {}) or {}
        comp_living_area = _safe_float_value(getattr(snapshot, "living_area", None) if snapshot else None)
        comp_calc_sqft = _safe_float_value(comp_meta.get("calculated_square_footage"))
        return comp_calc_sqft if comp_calc_sqft is not None else comp_living_area

    def _build_view_comp(comp_result: cma.ComparableResult, *, saved_index: int) -> Dict[str, Any]:
        snapshot = getattr(comp_result, "snapshot", None)
        address = getattr(snapshot, "address", None) if snapshot else None
        bedrooms = getattr(snapshot, "bedrooms", None) if snapshot else None
        bathrooms = getattr(snapshot, "bathrooms", None) if snapshot else None
        living_area = getattr(snapshot, "living_area", None) if snapshot else None
        year_built = getattr(snapshot, "year_built", None) if snapshot else None
        missing_bedrooms = _safe_float_value(bedrooms) is None
        missing_bathrooms = _safe_float_value(bathrooms) is None
        lat = getattr(snapshot, "latitude", None) if snapshot else None
        lon = getattr(snapshot, "longitude", None) if snapshot else None
        if (lat is None or lon is None) and snapshot is not None:
            point = snapshot.display_point()
            if point is not None:
                lat = getattr(point, "y", None)
                lon = getattr(point, "x", None)
        if (lat is None or lon is None) and snapshot is not None:
            geom = getattr(snapshot, "geom", None)
            lat, lon = _centroid_lat_lon(geom)
        try:
            sqft = float(living_area) if living_area not in (None, 0) else None
        except Exception:
            sqft = None
        try:
            price = float(comp_result.sale_price) if comp_result.sale_price is not None else None
        except Exception:
            price = None
        price_per_sqft = None
        if price is not None and sqft not in (None, 0):
            try:
                price_per_sqft = price / sqft
            except Exception:
                price_per_sqft = None

        comp_meta = getattr(snapshot, "metadata", {}) or {}
        comp_living_area = _safe_float_value(living_area)
        comp_calc_sqft = _comp_calc_square_footage(comp_result)
        missing_living_area = comp_calc_sqft is None
        missing_year_built = _safe_float_value(year_built) is None
        comp_lot_value = _safe_float_value(
            getattr(snapshot, "acres", None)
            or getattr(snapshot, "lot_acres", None)
            or comp_meta.get("lot_acres")
        )
        comp_score_obj = getattr(comp_result, "score", None)
        proximity_score = (
            _safe_float_value(getattr(comp_score_obj, "location_score", None))
            if comp_score_obj
            else None
        )
        time_score = (
            _safe_float_value(getattr(comp_score_obj, "time_score", None))
            if comp_score_obj
            else None
        )
        size_ratio = _ratio_similarity(subject_area, comp_living_area)
        land_ratio = _ratio_similarity(subject_lot, comp_lot_value)
        quality_match = _match_text_score(subject_quality, comp_meta.get("quality_score"))
        condition_match = _match_text_score(subject_condition, comp_meta.get("condition_score"))
        quality_condition_ratio = _average_score([quality_match, condition_match])
        available_ratios = [
            value
            for value in (
                proximity_score,
                time_score,
                size_ratio,
                quality_condition_ratio,
                land_ratio,
            )
            if value is not None
        ]
        overall_ratio = _average_score(available_ratios)
        if overall_ratio is None:
            fallback_total = (
                _safe_float_value(getattr(comp_score_obj, "total_score", None))
                if comp_score_obj
                else None
            )
            overall_ratio = fallback_total
        if overall_ratio is None:
            overall_ratio = 0.0
        else:
            overall_ratio = max(0.0, min(1.0, overall_ratio))
        similarity = {
            "overall": _percentage_score(overall_ratio),
            "time": _percentage_score(time_score),
            "proximity": _percentage_score(proximity_score),
            "size": _percentage_score(size_ratio),
            "quality_condition": _percentage_score(quality_condition_ratio),
            "land": _percentage_score(land_ratio),
        }

        adjustment_payload = {
            "available": False,
            "adjusted_price": None,
            "total_adjustment": None,
            "adjustment_by_key": {},
            "adjustments": [],
            "time_months_delta": None,
        }
        if advanced_ready and valuation_date_for_adjustments is not None:
            comp_features = _adjustment_support_comp_features(
                snapshot=snapshot,
                sale_date=comp_result.sale_date,
                valuation_date=valuation_date_for_adjustments,
            )
            adjustment_payload = _compute_comp_adjustment_payload(
                sale_price=price,
                subject_features=subject_adjustment_features,
                comp_features=comp_features,
                coefficients=adjustment_coefficients,
            )

        quality_metrics = compute_adjustment_quality_metrics(
            sale_price=price,
            total_adjustment=adjustment_payload.get("total_adjustment"),
            adjustments=adjustment_payload.get("adjustments") or [],
            subject_living_area=subject_area,
            comp_living_area=comp_calc_sqft,
        )
        rank_penalty_points = int(quality_metrics.get("penalty_points") or 0) if advanced_ready else 0
        rank_similarity = max(
            0.0,
            float((similarity or {}).get("overall") or 0) - float(rank_penalty_points),
        )
        comp_group = str(quality_metrics.get("group") or "primary") if advanced_ready else "primary"
        support_reasons = _support_reason_labels(
            group_reasons=quality_metrics.get("group_reasons") or [],
            quality_flags=quality_metrics.get("flags") or [],
            missing_bedrooms=missing_bedrooms,
            missing_bathrooms=missing_bathrooms,
            missing_living_area=missing_living_area,
            missing_year_built=missing_year_built,
        )

        return {
            "parcel_number": getattr(snapshot, "parcel_number", None) if snapshot else None,
            "address": address,
            "sale_price": comp_result.sale_price,
            "sale_date": comp_result.sale_date,
            "distance_miles": comp_result.distance_miles,
            "assessed_value": comp_result.assessed_value,
            "bedrooms": bedrooms,
            "missing_bedrooms": missing_bedrooms,
            "missing_bathrooms": missing_bathrooms,
            "missing_living_area": missing_living_area,
            "missing_year_built": missing_year_built,
            "bathrooms": bathrooms,
            "living_area": living_area,
            "calculated_square_footage": comp_calc_sqft,
            "year_built": year_built,
            "price_per_sqft": price_per_sqft,
            "latitude": lat,
            "longitude": lon,
            "similarity": similarity,
            "adjusted_price": adjustment_payload.get("adjusted_price"),
            "total_adjustment": adjustment_payload.get("total_adjustment"),
            "adjustment_by_key": adjustment_payload.get("adjustment_by_key") or {},
            "adjustments": adjustment_payload.get("adjustments") or [],
            "time_months_delta": adjustment_payload.get("time_months_delta"),
            "comp_group": comp_group,
            "comp_group_reasons": quality_metrics.get("group_reasons") or [],
            "quality_flags": quality_metrics.get("flags") or [],
            "_comp_group": comp_group,
            "_comp_group_reasons": quality_metrics.get("group_reasons") or [],
            "_rank_penalty_points": rank_penalty_points,
            "_rank_similarity": rank_similarity,
            "_quality_flags": quality_metrics.get("flags") or [],
            "_saved_index": saved_index,
            "support_reasons": support_reasons,
        }

    def _sort_view_comps(
        items: List[Dict[str, Any]],
        *,
        metric: str,
        direction: str,
    ) -> List[Dict[str, Any]]:
        descending = direction == "desc"

        def _metric_value(item: Dict[str, Any]) -> Optional[float]:
            if metric == "saved_order":
                return _safe_float_value(item.get("_saved_index"))
            if metric == "similarity":
                return _safe_float_value(item.get("_rank_similarity"))
            if metric == "sale_price":
                return _safe_float_value(item.get("sale_price"))
            if metric == "sale_date":
                sale_date = item.get("sale_date")
                return float(sale_date.toordinal()) if hasattr(sale_date, "toordinal") else None
            if metric == "distance":
                return _safe_float_value(item.get("distance_miles"))
            if metric == "bedrooms":
                return _safe_float_value(item.get("bedrooms"))
            if metric == "bathrooms":
                return _safe_float_value(item.get("bathrooms"))
            if metric == "sqft":
                return _safe_float_value(item.get("calculated_square_footage") or item.get("living_area"))
            if metric == "year_built":
                return _safe_float_value(item.get("year_built"))
            if metric == "price_per_sqft":
                return _safe_float_value(item.get("price_per_sqft"))
            return _safe_float_value(item.get("_rank_similarity"))

        def _key(item: Dict[str, Any]) -> Tuple[int, int, float, float, int, float]:
            metric_value = _metric_value(item)
            metric_key = float(metric_value or 0)
            if descending:
                metric_key = -metric_key
            return (
                0 if item.get("_comp_group") == "primary" else 1,
                1 if metric_value is None else 0,
                metric_key,
                -float(item.get("_rank_similarity") or 0),
                -(item.get("sale_date").toordinal() if hasattr(item.get("sale_date"), "toordinal") else 0),
                float(item.get("distance_miles") or 9999),
            )

        return sorted(items, key=_key)

    candidate_comps = list(comparables)
    view_comps = _sort_view_comps(
        [_build_view_comp(comp_result, saved_index=index) for index, comp_result in enumerate(candidate_comps)],
        metric=sort_by,
        direction=sort_direction,
    )

    if (
        allow_widen_pass
        and advanced_ready
        and display_limit < appeals.EXTENDED_COMPARABLE_LIMIT
        and sum(1 for item in view_comps if item.get("_comp_group") != "support") < 3
    ):
        tightened_gla_ratio_min = 0.85
        widened = appeals.build_sales_comps_v2(
            subject,
            limit=appeals.EXTENDED_COMPARABLE_LIMIT,
            months=appeals.DEFAULT_LOOKBACK_MONTHS,
            base_radius_m=appeals.SECONDARY_RADIUS_M,
            max_radius_m=appeals.SECONDARY_RADIUS_M * 2,
        )
        expanded_comps = list(widened.comparables or [])
        expanded_radius = widened.radius_meters_used
        seen_parcels = {
            _normalize_parcel_token(getattr(getattr(comp_result, "snapshot", None), "parcel_number", None))
            for comp_result in candidate_comps
        }
        appended_count = 0
        for comp_result in expanded_comps:
            parcel_key = _normalize_parcel_token(getattr(getattr(comp_result, "snapshot", None), "parcel_number", None))
            if not parcel_key or parcel_key in seen_parcels:
                continue
            size_ratio = _ratio_similarity(subject_area, _comp_calc_square_footage(comp_result))
            if size_ratio is None or size_ratio < tightened_gla_ratio_min:
                continue
            seen_parcels.add(parcel_key)
            candidate_comps.append(comp_result)
            appended_count += 1
        if appended_count:
            if expanded_radius:
                radius_used = max(radius_used or 0, expanded_radius)
            view_comps = _sort_view_comps(
                [_build_view_comp(comp_result, saved_index=index) for index, comp_result in enumerate(candidate_comps)],
                metric=sort_by,
                direction=sort_direction,
            )
            view_comps = view_comps[:display_limit]
        if isinstance(advanced_summary, dict):
            warnings = list(advanced_summary.get("warnings") or [])
            warnings.append(
                "Controlled widen pass run (primary comps < 3): expanded geography once and "
                "kept only tighter GLA matches (>= 85% size similarity)."
            )
            if appended_count == 0:
                warnings.append("No additional widened candidates cleared the tighter GLA gate.")
            advanced_summary["warnings"] = warnings

    primary_comps = [item for item in view_comps if item.get("_comp_group") != "support"]
    support_comps = [item for item in view_comps if item.get("_comp_group") == "support"]
    show_comp_groups = advanced_ready and bool(support_comps)

    try:
        lat = getattr(subject, "latitude", None)
        lon = getattr(subject, "longitude", None)
        if lat is None or lon is None:
            point = subject.display_point() if hasattr(subject, "display_point") else None
            if point is not None:
                lat = getattr(point, "y", None)
                lon = getattr(point, "x", None)
        if lat is None or lon is None:
            geom = getattr(subject, "geom", None)
            lat, lon = _centroid_lat_lon(geom)
        existing_lat = getattr(subject, "latitude", None)
        existing_lon = getattr(subject, "longitude", None)
        if lat is not None and lon is not None and (existing_lat is None or existing_lon is None):
            setattr(subject, "latitude", lat)
            setattr(subject, "longitude", lon)
    except Exception:
        pass

    sort_labels = {option["value"]: option["label"] for option in APPEAL_WORKSPACE_SORT_OPTIONS}
    sort_label = sort_labels.get(sort_by, "Similarity")
    return {
        "comparables": view_comps,
        "primary_comparables": primary_comps,
        "support_comparables": support_comps,
        "show_comp_groups": show_comp_groups,
        "advanced_summary": advanced_summary,
        "advanced_error": advanced_error,
        "advanced_mode": advanced_mode,
        "radius_meters_used": radius_used,
        "sort_label": sort_label,
        "map_payload": _build_appeal_map_payload(subject, view_comps),
        "market_area_payload": (
            advanced_summary.get("market_area")
            if isinstance(advanced_summary, dict)
            else None
        ),
    }


@require_GET
def appeal_result_comparables(request, parcel_number: str):
    raw_view_mode = (request.GET.get("view_mode") or "").strip().lower()
    advanced_mode = raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"}
    view_mode = "advanced" if advanced_mode else "standard"
    current_view = (request.GET.get("current_view") or "list").strip().lower()
    if current_view not in {"list", "grid", "map"}:
        current_view = "list"
    sort_by, sort_direction = _normalize_appeal_comp_sort(
        request.GET.get("sort_by"),
        request.GET.get("sort_dir"),
    )
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    activity_feed.log_activity(
        "comparison",
        "Finding Comparisons for",
        subject.address or parcel_number,
    )

    try:
        requested_count = int(request.GET.get("count", appeals.INITIAL_COMPARABLE_LIMIT))
    except (TypeError, ValueError):
        requested_count = appeals.INITIAL_COMPARABLE_LIMIT
    display_limit = (
        appeals.EXTENDED_COMPARABLE_LIMIT
        if requested_count >= appeals.EXTENDED_COMPARABLE_LIMIT
        else appeals.INITIAL_COMPARABLE_LIMIT
    )

    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    comps = _cached_appeal_pool_comparables(
        request,
        parcel_number,
        display_limit=display_limit,
    )
    comparables_from_cache = comps is not None
    if comps is None:
        comps, radius_used = appeals._comparable_candidates(subject, display_limit)
        parcel_state = _refresh_appeal_comp_pool(request, parcel_number, comps)
        parcel_state["last_radius_meters"] = _safe_float_value(radius_used)
        parcel_state["last_limit"] = display_limit
        request.session.modified = True
    else:
        radius_used = _safe_float_value(parcel_state.get("last_radius_meters"))

    pool = parcel_state.get("pool")
    pool_count = len(pool) if isinstance(pool, dict) else len(comps)
    saved_order = _get_appeal_saved_order(request, parcel_number)
    saved_set = set(saved_order)
    no_comp_diagnostics: Optional[Dict[str, Any]] = None
    if not comps:
        no_comp_diagnostics = diagnose_no_comp_path(
            subject,
            limit=display_limit,
            months=appeals.DEFAULT_LOOKBACK_MONTHS,
            base_radius_m=appeals.PRIMARY_RADIUS_M,
            max_radius_m=appeals.SECONDARY_RADIUS_M,
        )

    summary = appeals.citizen_assessment_summary(
        subject,
        comparables=comps,
        radius_meters=radius_used,
        limit=display_limit,
    )

    over_pct = summary.get("over_assessment_pct")
    comp_count = summary.get("comp_count") or 0
    neigh = summary.get("neighborhood") or {}
    neigh_diff = summary.get("neigh_diff_pct")
    avg_change_pct = neigh.get("avg_increase_pct")
    your_change_pct = appeals.extract_assessment_change_pct(subject.metadata)
    if your_change_pct is None and avg_change_pct is not None and neigh_diff is not None:
        your_change_pct = avg_change_pct + neigh_diff
    if neigh_diff is None and avg_change_pct is not None and your_change_pct is not None:
        neigh_diff = your_change_pct - avg_change_pct

    score = summary.get("score") or 0
    soft_stop = False
    soft_reasons: List[str] = []
    if over_pct is not None and over_pct < 7:
        soft_stop = True
        soft_reasons.append("Assessed value is less than ~7% above market comps.")
    if comp_count < 3:
        soft_stop = True
        soft_reasons.append("Fewer than 3 strong comparable sales are available.")
    if (neigh_diff is not None) and neigh_diff <= 0:
        soft_stop = True
        soft_reasons.append("Your assessment did not rise more than your neighborhood average.")
    if score < 45:
        soft_stop = True
        soft_reasons.append("Overall appeal likelihood is below ~45%.")

    has_more = False
    if display_limit < appeals.EXTENDED_COMPARABLE_LIMIT:
        has_more = pool_count > display_limit or len(comps) == display_limit
    load_more_query = {
        "count": appeals.EXTENDED_COMPARABLE_LIMIT,
        "current_view": current_view,
        "sort_by": sort_by,
        "sort_dir": sort_direction,
    }
    if advanced_mode:
        load_more_query["view_mode"] = "advanced"
    load_more_url = f"{request.path}?{urlencode(load_more_query)}"
    debug_flag = (request.GET.get("debug") or "").strip().lower() in {"1", "true", "yes", "on"}
    display_context = _build_appeal_comparables_display_context(
        subject=subject,
        comparables=comps,
        display_limit=display_limit,
        sort_by=sort_by,
        sort_direction=sort_direction,
        advanced_mode=advanced_mode,
        radius_used=radius_used,
        allow_widen_pass=True,
        parcel_number=parcel_number,
        debug_flag=debug_flag,
    )

    for comp in display_context["comparables"]:
        comp["is_saved"] = _normalize_parcel_token(comp.get("parcel_number")) in saved_set

    tray_context = _build_appeal_saved_tray_context(request, parcel_number)
    context = {
        "subject": subject,
        "soft_stop": soft_stop,
        "soft_reasons": soft_reasons,
        "score": score,
        "rating": summary.get("rating"),
        "reasons": summary.get("reasons", []),
        "has_more": has_more,
        "load_more_url": load_more_url,
        "extended_limit": appeals.EXTENDED_COMPARABLE_LIMIT,
        "parcel_number": parcel_number,
        "view_mode": view_mode,
        "current_view": current_view,
        "radius_meters_used": display_context.get("radius_meters_used"),
        "fetch_url": request.path,
        "sort_options": APPEAL_COMPARABLE_SORT_OPTIONS,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "sort_label": display_context.get("sort_label"),
        "no_comp_diagnostics": no_comp_diagnostics,
        "comparables_from_cache": comparables_from_cache,
        "saved_comps_url": reverse("appeal-saved-comps", args=[parcel_number]),
        "workspace_url": tray_context["workspace_url"],
        "saved_rows": tray_context["saved_rows"],
        "saved_count": tray_context["saved_count"],
        "saved_limit": tray_context["saved_limit"],
        "saved_ids": tray_context["saved_ids"],
        **display_context,
    }

    fragment = (request.GET.get("fragment") or "").strip().lower()
    if fragment == "content":
        return render(request, "openskagit/partials/appeal_comparables_content.html", context)
    return render(request, "openskagit/appeal_results_comparables_v3.html", context)


@require_POST
def appeal_saved_comps(request, parcel_number: str):
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "JSON object required."}, status=400)

    action = str(payload.get("action") or "").strip().lower()
    if action not in {"add", "remove", "reorder", "clear"}:
        return JsonResponse({"ok": False, "error": "Unsupported action."}, status=400)

    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool = parcel_state.get("pool")
    if not isinstance(pool, dict):
        pool = {}
        parcel_state["pool"] = pool
        request.session.modified = True
    pool_keys = {_normalize_parcel_token(parcel_id) for parcel_id in pool.keys() if _normalize_parcel_token(parcel_id)}
    saved_order = _normalize_saved_order(parcel_state.get("saved_order"), allowed_ids=pool_keys)
    message = ""

    if action == "add":
        comp_parcel = _normalize_parcel_token(payload.get("comp_parcel"))
        if not comp_parcel:
            return JsonResponse({"ok": False, "error": "comp_parcel is required for add."}, status=400)
        if comp_parcel not in pool_keys:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Comparable is not available in the current pool. Refresh comparables and try again.",
                },
                status=400,
            )
        if comp_parcel in saved_order:
            message = "Comparable is already saved."
        elif len(saved_order) >= APPEAL_SAVED_COMP_LIMIT:
            return JsonResponse(
                {
                    "ok": False,
                    "error": f"Saved comps are capped at {APPEAL_SAVED_COMP_LIMIT}. Remove one before adding another.",
                },
                status=400,
            )
        else:
            saved_order.append(comp_parcel)
            message = "Comparable added."

    elif action == "remove":
        comp_parcel = _normalize_parcel_token(payload.get("comp_parcel"))
        if not comp_parcel:
            return JsonResponse({"ok": False, "error": "comp_parcel is required for remove."}, status=400)
        saved_order = [parcel_id for parcel_id in saved_order if parcel_id != comp_parcel]
        message = "Comparable removed."

    elif action == "reorder":
        order_payload = payload.get("order")
        if not isinstance(order_payload, list):
            return JsonResponse({"ok": False, "error": "order must be a list for reorder."}, status=400)
        normalized_order = _normalize_saved_order(order_payload, allowed_ids=set(saved_order))
        if len(normalized_order) != len(saved_order) or set(normalized_order) != set(saved_order):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "order must contain each currently saved comparable exactly once.",
                },
                status=400,
            )
        saved_order = normalized_order
        message = "Order updated."

    elif action == "clear":
        saved_order = []
        message = "Saved comps cleared."

    parcel_state["saved_order"] = saved_order
    parcel_state["updated_at"] = timezone.now().isoformat()
    request.session.modified = True

    tray_context = _build_appeal_saved_tray_context(request, parcel_number)
    return JsonResponse(
        {
            "ok": True,
            "saved_count": tray_context["saved_count"],
            "saved_ids": tray_context["saved_ids"],
            "saved_limit": tray_context["saved_limit"],
            "workspace_url": tray_context["workspace_url"],
            "tray_html": render_to_string(
                "openskagit/partials/appeal_saved_comp_tray.html",
                tray_context,
                request=request,
            ),
            "message": message,
        }
    )


def _load_saved_comparable_results(request, parcel_number: str) -> List[cma.ComparableResult]:
    parcel_state = _get_appeal_comp_parcel_state(request, parcel_number)
    pool = parcel_state.get("pool")
    if not isinstance(pool, dict):
        return []
    saved_order = _get_appeal_saved_order(request, parcel_number)
    comparables: List[cma.ComparableResult] = []
    for parcel_id in saved_order:
        payload = pool.get(parcel_id)
        if not isinstance(payload, dict):
            continue
        try:
            comparables.append(appeals._comparable_from_payload(payload))
        except Exception:
            logger.exception("Unable to deserialize saved comparable payload %s", parcel_id)
    return comparables


def _build_workspace_board_context(
    request,
    *,
    subject: cma.PropertySnapshot,
    parcel_number: str,
    view_mode: str,
    workspace_view: str,
    sort_by: str,
    sort_direction: str,
) -> Dict[str, Any]:
    saved_comparables = _load_saved_comparable_results(request, parcel_number)
    advanced_mode = view_mode == "advanced"
    display_context = _build_appeal_comparables_display_context(
        subject=subject,
        comparables=saved_comparables,
        display_limit=max(1, len(saved_comparables)),
        sort_by=sort_by,
        sort_direction=sort_direction,
        advanced_mode=advanced_mode,
        radius_used=None,
        allow_widen_pass=False,
        parcel_number=parcel_number,
    )
    for comp in display_context["comparables"]:
        comp["is_saved"] = True
    saved_order = [comp.get("parcel_number") for comp in display_context["comparables"] if comp.get("parcel_number")]
    return {
        "subject": subject,
        "parcel_number": parcel_number,
        "view_mode": view_mode,
        "workspace_view": workspace_view,
        "advanced_mode": advanced_mode,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "sort_label": display_context.get("sort_label"),
        "saved_count": len(saved_comparables),
        "saved_ids": saved_order,
        **display_context,
    }


@require_GET
def appeal_comp_workspace(request, parcel_number: str):
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    raw_view_mode = (request.GET.get("view_mode") or "").strip().lower()
    view_mode = "advanced" if raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"} else "standard"
    workspace_view = _normalize_workspace_view(request.GET.get("workspace_view"))
    sort_by, sort_direction = _normalize_workspace_comp_sort(
        request.GET.get("sort_by"),
        request.GET.get("sort_dir"),
    )
    context = _build_workspace_board_context(
        request,
        subject=subject,
        parcel_number=parcel_number,
        view_mode=view_mode,
        workspace_view=workspace_view,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    context.update(
        {
            "saved_comps_url": reverse("appeal-saved-comps", args=[parcel_number]),
            "workspace_board_url": reverse("appeal-comp-workspace-board", args=[parcel_number]),
            "comparables_url": reverse("appeal-result-comparables", args=[parcel_number]),
            "sort_options": APPEAL_WORKSPACE_SORT_OPTIONS,
            "workspace_view": workspace_view,
            "meta_description": f"Compare saved comps side by side for parcel {parcel_number} in Parcel Partner.",
            "page_title": f"Parcel Partner · Workspace {parcel_number}",
            "og_title": f"Parcel Partner · Workspace {parcel_number}",
            "og_url": request.build_absolute_uri(),
        }
    )
    return render(request, "openskagit/appeal_comp_workspace.html", context)


@require_GET
def appeal_comp_workspace_board(request, parcel_number: str):
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    raw_view_mode = (request.GET.get("view_mode") or "").strip().lower()
    view_mode = "advanced" if raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"} else "standard"
    workspace_view = _normalize_workspace_view(request.GET.get("workspace_view"))
    sort_by, sort_direction = _normalize_workspace_comp_sort(
        request.GET.get("sort_by"),
        request.GET.get("sort_dir"),
    )
    context = _build_workspace_board_context(
        request,
        subject=subject,
        parcel_number=parcel_number,
        view_mode=view_mode,
        workspace_view=workspace_view,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    return render(request, "openskagit/partials/appeal_comp_workspace_board.html", context)


@require_GET
def appeal_fairness_analysis(request, parcel_number: str):
    message = "Fairness analysis is deprecated and no longer available in Parcel Partner."
    logger.info("Deprecated fairness endpoint requested for parcel %s", parcel_number)
    return HttpResponseGone(message)


def _parse_iso_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    parsed = parse_datetime(value)
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed


def _build_methodology_context_from_diagnostics(diagnostics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    diagnostics = diagnostics or {}
    segments = diagnostics.get("segments") or []
    stats_list = diagnostics.get("stats") or []
    if not stats_list and segments:
        for seg in segments:
            perf = seg.get("performance") or {}
            band = seg.get("tier_price_band") or {}
            stats_list.append(
                {
                    "label": seg.get("segment") or f"{seg.get('market_group', '')}__{seg.get('value_tier', '')}",
                    "market_group": seg.get("market_group"),
                    "value_tier": seg.get("value_tier"),
                    "n": perf.get("n"),
                    "r2": perf.get("r2"),
                    "adj_r2": perf.get("adj_r2"),
                    "COD": perf.get("COD"),
                    "PRD": perf.get("PRD"),
                    "PRB": perf.get("PRB"),
                    "median_ratio": perf.get("median_ratio"),
                    "price_min": band.get("min"),
                    "price_max": band.get("max"),
                    "value_drivers": (seg.get("drivers") or {}).get("value_drivers") or [],
                    "value_driver_groups": (seg.get("drivers") or {}).get("driver_groups") or [],
                    "calib_bands": (seg.get("calibration") or {}).get("bands") or [],
                    "chart_data": seg.get("chart_data") or [],
                }
            )
    stats_rows = [row for row in stats_list if isinstance(row, dict)]

    raw_coefficients = diagnostics.get("coefficients") or []
    coefficients_raw = [
        entry if isinstance(entry, dict) else getattr(entry, "dict", lambda: {})()
        for entry in raw_coefficients
    ]
    coefficients_by_group: Dict[str, Dict[str, Any]] = {}
    for entry in coefficients_raw:
        if not isinstance(entry, dict):
            continue
        market_group = entry.get("market_group")
        if not market_group:
            continue
        coefficients_by_group[market_group] = {
            "coefficients": entry.get("coefficients", []),
            "display_name": entry.get("display_name") or market_group.replace("_", " ").title(),
        }

    model_stats: Dict[str, Dict[str, Any]] = {}
    for stat in stats_rows:
        label = stat.get("label") or stat.get("market_group")
        if not label:
            continue
        model_stats[label] = stat

    interactive_rows: List[Dict[str, Any]] = []
    for group_name, group_data in coefficients_by_group.items():
        stats = model_stats.get(group_name, {})
        coeff_rows = group_data.get("coefficients", []) or []
        for coeff in coeff_rows:
            if not isinstance(coeff, dict):
                continue
            interactive_rows.append(
                {
                    "market_group": group_name,
                    "term": coeff.get("term"),
                    "beta": coeff.get("beta"),
                    "beta_se": coeff.get("beta_se"),
                    "display_name": group_data.get("display_name"),
                    "n": stats.get("n"),
                    "r2": stats.get("r2"),
                    "adj_r2": stats.get("adj_r2"),
                    "COD": stats.get("COD"),
                    "PRD": stats.get("PRD"),
                    "median_ratio": stats.get("median_ratio"),
                }
            )

    aggregated_value_drivers: Dict[str, Dict[str, Any]] = {}
    for stats in stats_rows:
        drivers = stats.get("value_drivers", []) or []
        for driver in drivers:
            if not isinstance(driver, dict):
                continue
            predictor = driver.get("predictor")
            if not predictor:
                continue
            entry = aggregated_value_drivers.setdefault(
                predictor,
                {
                    "importance": 0.0,
                    "direction_counts": {"up": 0, "down": 0},
                    "group_counts": {},
                    "last_group": None,
                },
            )
            entry["importance"] += float(driver.get("importance") or 0.0)
            direction = (driver.get("direction") or "").lower()
            if direction in entry["direction_counts"]:
                entry["direction_counts"][direction] += 1
            group = driver.get("group")
            if group:
                counts = entry.setdefault("group_counts", {})
                counts[group] = counts.get(group, 0) + 1
                entry["last_group"] = group

    total_driver_importance = sum(entry["importance"] for entry in aggregated_value_drivers.values()) or 1.0

    def resolve_group_label(data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return "General"
        group_counts = data.get("group_counts") or {}
        if group_counts:
            group_key = max(group_counts.items(), key=lambda kv: kv[1])[0]
        else:
            group_key = data.get("last_group")
        if not group_key:
            return "General"
        return group_key.replace("_", " ").title()

    def resolve_direction_code(data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return "mixed"
        counts = data.get("direction_counts") or {}
        lowers_ratio = counts.get("up", 0)
        raises_ratio = counts.get("down", 0)
        if lowers_ratio > raises_ratio:
            return "lower"
        if raises_ratio > lowers_ratio:
            return "higher"
        return "mixed"

    def resolve_importance_percent(data: Optional[Dict[str, Any]]) -> Optional[float]:
        if not data or total_driver_importance <= 0:
            return None
        share = data.get("importance") or 0.0
        if share <= 0:
            return None
        return round((share / total_driver_importance) * 100, 1)

    value_driver_rows: List[Dict[str, Any]] = []
    seen_predictors: Set[str] = set()
    for feature in copy.deepcopy(FEATURE_EXPLANATIONS):
        predictor = feature.get("term")
        stats = aggregated_value_drivers.get(predictor)
        value_driver_rows.append(
            {
                "term": predictor,
                "label": feature.get("simple") or (predictor or "").replace("_", " ").title(),
                "description": feature.get("explanation") or "",
                "group_label": resolve_group_label(stats),
                "direction": resolve_direction_code(stats),
                "importance_pct": resolve_importance_percent(stats),
            }
        )
        if predictor:
            seen_predictors.add(predictor)

    extra_rows: List[Dict[str, Any]] = []
    for predictor, stats in aggregated_value_drivers.items():
        if predictor in seen_predictors:
            continue
        extra_rows.append(
            {
                "term": predictor,
                "label": predictor.replace("_", " ").title(),
                "description": "Predictor surfaced in this run.",
                "group_label": resolve_group_label(stats),
                "direction": resolve_direction_code(stats),
                "importance_pct": resolve_importance_percent(stats),
            }
        )

    extra_rows.sort(key=lambda row: row.get("importance_pct") or 0, reverse=True)
    value_driver_rows.extend(extra_rows)

    total_observations = 0
    if diagnostics.get("global_metrics"):
        global_metrics = diagnostics["global_metrics"]
        if isinstance(global_metrics, dict):
            total_observations = global_metrics.get("total_observations") or 0
    if not total_observations:
        total_observations = sum(int(stat.get("n") or 0) for stat in stats_rows)

    generated_at = diagnostics.get("generated_at") or diagnostics.get("generated")
    last_updated = _parse_iso_datetime(generated_at)
    adjustment_run_stats_json = json.dumps(stats_rows, default=str)
    chart_data = stats_rows[0].get("chart_data", []) if stats_rows else []

    return {
        "adjustment_run_stats": stats_rows,
        "adjustment_run_stats_json": adjustment_run_stats_json,
        "coefficients_by_group": coefficients_by_group,
        "model_stats": model_stats,
        "feature_explanations": copy.deepcopy(FEATURE_EXPLANATIONS),
        "value_driver_rows": value_driver_rows,
        "last_updated": last_updated,
        "latest_adjustment_run": {"run_id": diagnostics.get("run_id"), "created_at": last_updated} if diagnostics else None,
        "total_observations": total_observations,
        "model_stats_list": stats_rows,
        "chart_data": chart_data,
    }


@require_GET
def methodology_view(request):
    """
    Public-facing page explaining the regression methodology used for property valuations.
    Shows real coefficients and model performance metrics for transparency.
    """
    requested_run_id = request.GET.get("run_id")
    requested_mode = request.GET.get("mode")
    payload, _ = load_regression_run(run_id=requested_run_id, mode=requested_mode)
    stats_list = payload.stats if payload else []
    metadata = payload.metadata if payload else None
    last_updated = _parse_iso_datetime(metadata.generated_at if metadata else None)
    latest_adjustment_run = (
        {"run_id": metadata.run_id, "created_at": last_updated} if metadata else None
    )

    raw_coefficients = payload.coefficients if payload else []
    coefficients_raw = [
        entry.dict() if hasattr(entry, "dict") else entry for entry in raw_coefficients
    ]
    coefficients_by_group: Dict[str, Dict[str, Any]] = {}
    for entry in coefficients_raw:
        market_group = entry.get("market_group")
        if not market_group:
            continue
        coefficients_by_group[market_group] = {
            "coefficients": entry.get("coefficients", []),
            "display_name": entry.get("display_name") or market_group.replace("_", " ").title(),
        }

    model_stats: Dict[str, Dict[str, Any]] = {}
    for stat in stats_list:
        if not isinstance(stat, dict):
            continue
        label = stat.get("label") or stat.get("market_group")
        if not label:
            continue
        model_stats[label] = stat

    model_stats_list = stats_list
    feature_explanations = copy.deepcopy(FEATURE_EXPLANATIONS)

    interactive_rows: List[Dict[str, Any]] = []
    for group_name, group_data in coefficients_by_group.items():
        stats = model_stats.get(group_name, {})
        for coeff in group_data["coefficients"]:
            interactive_rows.append({
                "market_group": group_name,
                "term": coeff.get("term"),
                "beta": coeff.get("beta"),
                "beta_se": coeff.get("beta_se"),
                "display_name": group_data["display_name"],
                "n": stats.get("n"),
                "r2": stats.get("r2"),
                "adj_r2": stats.get("adj_r2"),
                "COD": stats.get("COD"),
                "PRD": stats.get("PRD"),
                "median_ratio": stats.get("median_ratio"),
            })

    aggregated_value_drivers: Dict[str, Dict[str, Any]] = {}
    for stats in stats_list:
        for driver in stats.get("value_drivers", []) or []:
            predictor = driver.get("predictor")
            if not predictor:
                continue
            entry = aggregated_value_drivers.setdefault(
                predictor,
                {
                    "importance": 0.0,
                    "direction_counts": {"up": 0, "down": 0},
                    "group_counts": {},
                    "last_group": None,
                },
            )
            entry["importance"] += float(driver.get("importance") or 0.0)
            direction = (driver.get("direction") or "").lower()
            if direction in entry["direction_counts"]:
                entry["direction_counts"][direction] += 1
            group = driver.get("group")
            if group:
                counts = entry.setdefault("group_counts", {})
                counts[group] = counts.get(group, 0) + 1
                entry["last_group"] = group

    total_driver_importance = sum(entry["importance"] for entry in aggregated_value_drivers.values())

    def resolve_group_label(data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return "General"
        group_counts = data.get("group_counts") or {}
        if group_counts:
            group_key = max(group_counts.items(), key=lambda kv: kv[1])[0]
        else:
            group_key = data.get("last_group")
        if not group_key:
            return "General"
        return group_key.replace("_", " ").title()

    def resolve_direction_code(data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return "mixed"
        counts = data.get("direction_counts") or {}
        lowers_ratio = counts.get("up", 0)
        raises_ratio = counts.get("down", 0)
        if lowers_ratio > raises_ratio:
            return "lower"
        if raises_ratio > lowers_ratio:
            return "higher"
        return "mixed"

    def resolve_importance_percent(data: Optional[Dict[str, Any]]) -> Optional[float]:
        if not data or total_driver_importance <= 0:
            return None
        share = data.get("importance") or 0.0
        if share <= 0:
            return None
        return round((share / total_driver_importance) * 100, 1)

    value_driver_rows: List[Dict[str, Any]] = []
    seen_predictors: Set[str] = set()
    for feature in feature_explanations:
        predictor = feature.get("term")
        stats = aggregated_value_drivers.get(predictor)
        value_driver_rows.append(
            {
                "term": predictor,
                "label": feature.get("simple") or (predictor or "").replace("_", " ").title(),
                "description": feature.get("explanation") or "",
                "group_label": resolve_group_label(stats),
                "direction": resolve_direction_code(stats),
                "importance_pct": resolve_importance_percent(stats),
            }
        )
        if predictor:
            seen_predictors.add(predictor)

    extra_rows: List[Dict[str, Any]] = []
    for predictor, stats in aggregated_value_drivers.items():
        if predictor in seen_predictors:
            continue
        extra_rows.append(
            {
                "term": predictor,
                "label": predictor.replace("_", " ").title(),
                "description": "Predictor surfaced in the latest regression run.",
                "group_label": resolve_group_label(stats),
                "direction": resolve_direction_code(stats),
                "importance_pct": resolve_importance_percent(stats),
            }
        )

    extra_rows.sort(key=lambda row: row.get("importance_pct") or 0, reverse=True)
    value_driver_rows.extend(extra_rows)

    global_metrics = payload.global_metrics if payload else None
    if global_metrics:
        total_observations = int(global_metrics.total_observations)
    else:
        total_observations = sum(int(stat.get("n") or 0) for stat in stats_list)

    runs_available = [meta.dict() for meta in list_regression_runs(mode=requested_mode)]

    context = {
        "coefficients_by_group": coefficients_by_group,
        "model_stats": model_stats,
        "feature_explanations": feature_explanations,
        "value_driver_rows": value_driver_rows,
        "last_updated": last_updated,
        "latest_adjustment_run": latest_adjustment_run,
        "adjustment_run_stats": stats_list,
        "adjustment_run_stats_json": json.dumps(stats_list, default=str),
        "interactive_rows": interactive_rows,
        "total_observations": total_observations,
        "model_stats_list": model_stats_list,
        "chart_data": stats_list[0].get("chart_data", []) if stats_list else [],
        "runs_available": runs_available,
        "selected_run_id": metadata.run_id if metadata else None,
        "current_run_mode": metadata.mode if metadata else None,
    }

    return render(request, "openskagit/methodology.html", context)


@require_GET
def faq_view(request):
    """
    Frequently Asked Questions page with searchable, categorized content.
    """
    return render(request, 'openskagit/faq.html')


def hood_trend_list(request):
    """
    Left-hand panel: list of hoods that have trends.
    HTMX will pull the detail view on click.
    """
    hoods = (
        NeighborhoodTrend.objects.values("hood_id")
        .annotate(
            first_year=Min("value_year"),
            last_year=Max("value_year"),
            n_years=Count("id"),
            avg_stability=Avg("stability_score"),
        )
        .order_by("hood_id")
    )

    return render(request, "trends/hood_trend_list.html", {"hoods": hoods})


def hood_trend_detail(request, hood_id):
    """
    Right-hand panel: full time series for one hood.
    """
    qs = NeighborhoodTrend.objects.filter(hood_id=hood_id).order_by("value_year")
    if not qs.exists():
        return render(
            request, "trends/hood_trend_detail.html", {"hood": hood_id, "rows": []}
        )

    rows = list(qs)

    first_year = rows[0].value_year
    last_year = rows[-1].value_year
    avg_stability = sum(r.stability_score or 0 for r in rows) / max(
        len([r for r in rows if r.stability_score is not None]), 1
    )

    context = {
        "hood": hood_id,
        "rows": rows,
        "first_year": first_year,
        "last_year": last_year,
        "avg_stability": round(avg_stability, 1),
    }

    return render(request, "trends/hood_trend_detail.html", context)


NEIGHBORHOOD_TRENDS_SEARCH_LIMIT = 15
NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH = 3


@require_GET
def neighborhood_trends_page(request):
    """
    Entry point for the Neighborhood Trends tool.
    """
    hoods = (
        NeighborhoodTrend.objects.values("hood_id")
        .annotate(
            first_year=Min("value_year"),
            last_year=Max("value_year"),
            avg_stability=Avg("stability_score"),
        )
        .order_by("hood_id")
    )

    return render(
        request,
        "openskagit/neighborhood_trends_page.html",
        {
            "hoods": hoods,
            "cesium_token": getattr(settings, "CESIUM_ION_TOKEN", None),
        },
    )


@require_GET
def neighborhood_trend_data(request, hood_id):
    """
    Chart-specific JSON payload with yearly trend arrays.
    """
    activity_feed.log_activity(
        "neighborhood",
        "Creating Neighborhood Analysis for",
        hood_id,
    )
    fairness_data = _load_neighborhood_fairness_data(hood_id)
    rows = list(
        NeighborhoodTrend.objects.filter(hood_id=hood_id).order_by("value_year")
    )
    if not rows:
        empty_series = {
            "years": [],
            "median_market_total": [],
            "median_land_market": [],
            "median_building": [],
            "median_tax_amount": [],
            "yoy_change_total": [],
            "tax_percent_of_value": [],
        }
        return JsonResponse(
        {
            "hood_id": hood_id,
            "years": [],
            "series": empty_series,
            "summary": {
                "first_year": None,
                "last_year": None,
                "avg_stability": None,
                "fairness": fairness_data,
            },
        }
        )

    series = {
        "median_market_total": [],
        "median_land_market": [],
        "median_building": [],
        "median_tax_amount": [],
        "yoy_change_total": [],
        "tax_percent_of_value": [],
    }
    stability_values = []

    for row in rows:
        series["median_market_total"].append(row.median_market_total)
        series["median_land_market"].append(row.median_land_market)
        series["median_building"].append(row.median_building)
        series["median_tax_amount"].append(row.median_tax_amount)
        series["yoy_change_total"].append(row.yoy_change_total)

        if row.median_market_total and row.median_tax_amount:
            series["tax_percent_of_value"].append(
                round(row.median_tax_amount / row.median_market_total * 100, 2)
            )
        else:
            series["tax_percent_of_value"].append(None)

        if row.stability_score is not None:
            stability_values.append(row.stability_score)

    avg_stability = (
        round(sum(stability_values) / len(stability_values), 1)
        if stability_values
        else None
    )

    summary = {
        "first_year": rows[0].value_year,
        "last_year": rows[-1].value_year,
        "avg_stability": avg_stability,
        "fairness": fairness_data,
    }

    return JsonResponse(
        {
            "hood_id": hood_id,
            "years": [row.value_year for row in rows],
            "series": series,
            "summary": summary,
        }
    )


@require_GET
def neighborhood_trend_geom(request, hood_id):
    """
    GeoJSON payload for the selected neighborhood polygon.
    """
    try:
        geom_record = NeighborhoodGeom.objects.get(code=hood_id)
    except NeighborhoodGeom.DoesNotExist:
        return JsonResponse(
            {"hood_id": hood_id, "name": None, "geom": None, "centroid": None}
        )

    geom_obj = getattr(geom_record, "geom_4326", None)
    centroid_lat, centroid_lon = _centroid_lat_lon(geom_obj)

    return JsonResponse(
        {
            "hood_id": hood_id,
            "name": geom_record.name or geom_record.code,
            "geom": json.loads(geom_obj.geojson) if geom_obj else None,
            "centroid": {"lat": centroid_lat, "lng": centroid_lon},
        }
    )


@require_GET
def neighborhood_trend_address_search(request):
    """
    Address autocomplete for selecting a neighborhood via parcel search.
    """
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH
    results = []

    if not query_too_short:
        qs = (
            Parcel.objects.filter(
                neighborhood_code__isnull=False
            )
            .exclude(neighborhood_code__exact="")
            .exclude(address__isnull=True)
            .exclude(address__exact="")
        )

        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        results = (
            qs.order_by("address")
            [:NEIGHBORHOOD_TRENDS_SEARCH_LIMIT]
        )

    return render(
        request,
        "openskagit/neighborhood_trends_search_results.html",
        {
            "query": query,
            "query_too_short": query_too_short,
            "results": results,
            "min_search_length": NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH,
        },
    )


# -------------------------------------------------------------------
# EXPERIMENT UI
# -------------------------------------------------------------------

def _parse_tags(raw: str) -> List[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _dedupe_ordered(items: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        token = (item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _sanitize_selection(raw_items: Sequence[str], allowed: Set[str]) -> List[str]:
    return [token for token in _dedupe_ordered(raw_items) if token in allowed]


def _load_diagnostics(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            payload = json.load(f)
            if not isinstance(payload, dict):
                logger.warning("Diagnostics payload is not an object for path %s", path)
                return None
            return payload
    except Exception:
        return None


REGRESSION_GATE_PASSWORD = "grandson2025"
REGRESSION_GATE_SESSION_KEY = "regression_control_unlocked_at"
REGRESSION_GATE_SESSION_TTL = dt.timedelta(hours=12)
REGRESSION_SEGMENTATION_OPTIONS = [
    {
        "value": "valuation_area",
        "label": "Valuation Area (Recommended)",
        "description": "Stable county macro segments (west/central/east style).",
    },
    {
        "value": "city_district",
        "label": "City / District",
        "description": "Groups by city jurisdiction from master parcel records.",
    },
    {
        "value": "hood_code",
        "label": "Neighborhood (hood_code)",
        "description": "Most granular grouping; can be sparse in low-sale neighborhoods.",
    },
]

REGRESSION_PREDICTOR_SOURCE_HINTS: Dict[str, Dict[str, str]] = {
    "log_area": {"model": "MasterParcel", "field": "final_living_area / total_living_area"},
    "log_area_sq": {"model": "MasterParcel", "field": "living area curvature"},
    "log_age": {"model": "MasterParcel", "field": "year_built"},
    "log_eff_age": {"model": "MasterParcel", "field": "eff_year_built"},
    "quality_score": {"model": "MasterParcel", "field": "quality_score"},
    "condition_score": {"model": "MasterParcel", "field": "condition_score"},
    "log_lot": {"model": "MasterParcel", "field": "acres"},
    "log_lot_sq": {"model": "MasterParcel", "field": "lot size curvature"},
    "land_share": {"model": "MasterParcel", "field": "land vs total market value"},
    "log_far": {"model": "MasterParcel", "field": "floor_area_ratio"},
    "has_garage": {"model": "MasterParcel", "field": "garage area rollup"},
    "has_basement": {"model": "MasterParcel", "field": "basement area rollup"},
    "bedrooms": {"model": "MasterParcel", "field": "number_of_bedrooms"},
    "bathrooms": {"model": "MasterParcel", "field": "total_baths"},
    "baths_per_bed": {"model": "MasterParcel", "field": "bathrooms / bedrooms"},
    "is_view": {"model": "MasterParcel", "field": "hood_code-derived view flag"},
    "missing_quality": {"model": "MasterParcel", "field": "quality_score null flag"},
    "missing_condition": {"model": "MasterParcel", "field": "condition_score null flag"},
    "log_elev": {"model": "ParcelGeometry", "field": "elev"},
    "log_major_road": {"model": "ParcelGeometry", "field": "dist_major_road"},
    "view_aspect_west": {"model": "ParcelGeometry", "field": "aspect"},
    "view_elev": {"model": "ParcelGeometry", "field": "is_view x log_elev"},
    "view_level": {"model": "ParcelGeometry", "field": "view + aspect composite"},
    "in_flood_zone_flag": {"model": "ParcelPlanningFacts", "field": "in_flood_zone"},
    "in_sfha_flag": {"model": "ParcelPlanningFacts", "field": "in_sfha"},
    "in_wetland_flag": {"model": "ParcelPlanningFacts", "field": "in_wetland"},
    "in_shoreline_flag": {"model": "ParcelPlanningFacts", "field": "in_shoreline_jurisdiction"},
    "sewer_available_flag": {"model": "ParcelPlanningFacts", "field": "public_sewer_available"},
    "recent_permits_flag": {"model": "ParcelPlanningFacts", "field": "has_recent_permits_5yr"},
    "log_buildable_area": {"model": "ParcelPlanningFacts", "field": "buildable_area_sqft"},
    "t": {"model": "Sales", "field": "sale_date months since anchor"},
    "t_sq": {"model": "Sales", "field": "time curvature"},
    "land_time": {"model": "Derived", "field": "land_share x time"},
    "area_time": {"model": "Derived", "field": "log_area x time"},
}


def _build_regression_predictor_catalog(
    core_predictor_options: Sequence[str],
    candidate_predictor_options: Sequence[str],
) -> List[Dict[str, str]]:
    core_set = set(core_predictor_options)
    rows: List[Dict[str, str]] = []
    for predictor in _dedupe_ordered(list(core_predictor_options) + list(candidate_predictor_options)):
        hint = REGRESSION_PREDICTOR_SOURCE_HINTS.get(predictor, {"model": "Derived", "field": "engineered feature"})
        rows.append(
            {
                "name": predictor,
                "scope": "core" if predictor in core_set else "candidate",
                "source_model": hint["model"],
                "source_field": hint["field"],
            }
        )
    return rows


def _is_regression_gate_unlocked(request) -> bool:
    unlocked_at_raw = request.session.get(REGRESSION_GATE_SESSION_KEY)
    if not unlocked_at_raw:
        return False
    unlocked_at = parse_datetime(unlocked_at_raw)
    if not unlocked_at:
        request.session.pop(REGRESSION_GATE_SESSION_KEY, None)
        return False
    if timezone.is_naive(unlocked_at):
        unlocked_at = timezone.make_aware(unlocked_at, timezone.get_current_timezone())
    if timezone.now() - unlocked_at > REGRESSION_GATE_SESSION_TTL:
        request.session.pop(REGRESSION_GATE_SESSION_KEY, None)
        return False
    return True


def _unlock_regression_gate(request) -> None:
    request.session[REGRESSION_GATE_SESSION_KEY] = timezone.now().isoformat()


def regression_gate_required(view_func):
    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if _is_regression_gate_unlocked(request):
            return view_func(request, *args, **kwargs)

        accepts_json = "application/json" in (request.headers.get("Accept") or "")
        if accepts_json:
            return JsonResponse(
                {"error": "Regression access password required.", "code": "regression_password_required"},
                status=403,
            )

        messages.info(request, "Enter the regression password to access experiment pages.")
        return redirect("regression_control")

    return _wrapped


def regression_control_center(request):
    if not _is_regression_gate_unlocked(request):
        error_message = None
        if request.method == "POST":
            password = (request.POST.get("gate_password") or "").strip()
            if password == REGRESSION_GATE_PASSWORD:
                _unlock_regression_gate(request)
                return redirect("regression_control")
            error_message = "Incorrect password. Please try again."
        return render(
            request,
            "openskagit/regression/password_gate.html",
            {"error_message": error_message},
        )

    predictor_profiles = list(PREDICTOR_PROFILES.keys())
    interaction_bundles = list(INTERACTION_BUNDLES.keys())
    locked_mode = "sfr"
    segmentation_options = list(REGRESSION_SEGMENTATION_OPTIONS)
    segmentation_option_values = {opt["value"] for opt in segmentation_options}
    default_market_group_col = (
        segmentation_options[0]["value"] if segmentation_options else "valuation_area"
    )
    profile_core_options: List[str] = []
    profile_candidate_options: List[str] = []
    for profile in PREDICTOR_PROFILES.values():
        if not isinstance(profile, dict):
            continue
        profile_core_options.extend(profile.get("core") or [])
        profile_candidate_options.extend(profile.get("candidates") or [])

    core_predictor_options = _dedupe_ordered(list(CORE_PREDICTORS) + profile_core_options)
    candidate_predictor_options = _dedupe_ordered(list(CANDIDATE_PREDICTORS) + profile_candidate_options)
    core_option_set = set(core_predictor_options)
    candidate_predictor_options = [p for p in candidate_predictor_options if p not in core_option_set]
    interaction_term_options = sorted(INTERACTIONS.keys())
    tier_interaction_var_options = _dedupe_ordered(
        list(TIER_INTERACTION_VARS) + core_predictor_options + candidate_predictor_options
    )
    predictor_option_set = set(_dedupe_ordered(core_predictor_options + candidate_predictor_options))
    interaction_term_set = set(interaction_term_options)
    tier_interaction_var_set = set(tier_interaction_var_options)
    predictor_catalog_rows = _build_regression_predictor_catalog(
        core_predictor_options,
        candidate_predictor_options,
    )
    recipe_candidate_rows = [row for row in predictor_catalog_rows if row.get("scope") == "candidate"]

    default_profile = "baseline" if "baseline" in predictor_profiles else (predictor_profiles[0] if predictor_profiles else "")
    default_bundle = "standard" if "standard" in interaction_bundles else (interaction_bundles[0] if interaction_bundles else "")

    form_defaults = {
        "name": "",
        "mode": locked_mode,
        "market_group_col": default_market_group_col,
        "predictor_profile": default_profile,
        "interaction_bundle": default_bundle,
        "countywide": False,
        "no_interactions": False,
        "tags": "",
        "notes": "",
        "core_include": [],
        "core_exclude": [],
        "candidate_include": [],
        "candidate_exclude": [],
        "force_include": [],
        "force_exclude": [],
        "interaction_terms": [],
        "tier_interaction_vars": list(TIER_INTERACTION_VARS),
    }

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        mode = locked_mode
        predictor_profile = (request.POST.get("predictor_profile") or default_profile).strip()
        interaction_bundle = (request.POST.get("interaction_bundle") or default_bundle).strip()
        countywide = request.POST.get("countywide") == "on"
        no_interactions = request.POST.get("no_interactions") == "on"
        market_group_col = (request.POST.get("market_group_col") or default_market_group_col).strip()
        notes = (request.POST.get("notes") or "").strip()
        tags_raw = (request.POST.get("tags") or "").strip()
        tags = _parse_tags(tags_raw)
        core_include = _sanitize_selection(request.POST.getlist("core_include"), predictor_option_set)
        core_exclude = _sanitize_selection(request.POST.getlist("core_exclude"), predictor_option_set)
        candidate_include = _sanitize_selection(request.POST.getlist("candidate_include"), predictor_option_set)
        candidate_exclude = _sanitize_selection(request.POST.getlist("candidate_exclude"), predictor_option_set)
        force_include = _sanitize_selection(request.POST.getlist("force_include"), predictor_option_set)
        force_exclude = _sanitize_selection(request.POST.getlist("force_exclude"), predictor_option_set)
        interaction_terms = _sanitize_selection(request.POST.getlist("interaction_terms"), interaction_term_set)
        tier_interaction_vars = _sanitize_selection(
            request.POST.getlist("tier_interaction_vars"),
            tier_interaction_var_set,
        )

        if predictor_profile not in predictor_profiles:
            messages.error(request, f"Invalid predictor profile '{predictor_profile}'.")
            return redirect("regression_control")
        if interaction_bundle not in interaction_bundles:
            messages.error(request, f"Invalid interaction bundle '{interaction_bundle}'.")
            return redirect("regression_control")
        if market_group_col not in segmentation_option_values:
            messages.error(request, f"Invalid segmentation '{market_group_col}'.")
            return redirect("regression_control")

        if not name:
            timestamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            name = f"Regression {mode} {predictor_profile} {timestamp}"

        experiment = ExperimentRun.objects.create(
            name=name,
            mode=mode,
            predictor_profile=predictor_profile,
            interaction_bundle=interaction_bundle,
            countywide=countywide,
            market_group_col=market_group_col,
            notes=notes,
            tags=tags,
            full_config={
                "mode": mode,
                "predictor_profile": predictor_profile,
                "interaction_bundle": interaction_bundle,
                "no_interactions": no_interactions,
                "countywide": countywide,
                "market_group_col": market_group_col,
                "tags": tags,
                "core_include": core_include,
                "core_exclude": core_exclude,
                "candidate_include": candidate_include,
                "candidate_exclude": candidate_exclude,
                "force_include": force_include,
                "force_exclude": force_exclude,
                "interaction_terms": interaction_terms,
                "tier_interaction_vars": tier_interaction_vars,
            },
        )

        manage_py = Path(settings.BASE_DIR) / "manage.py"
        cmd = [
            sys.executable,
            str(manage_py),
            "regression_masterparcel",
            "--experiment",
            "--experiment-id",
            str(experiment.id),
            "--mode",
            mode,
            "--predictor-set",
            predictor_profile,
            "--interactions",
            interaction_bundle,
            "--market-group-col",
            market_group_col,
        ]
        if no_interactions:
            cmd.append("--no-interactions")
        if countywide:
            cmd.append("--countywide")
        if core_include:
            cmd.extend(["--core-include", ",".join(core_include)])
        if core_exclude:
            cmd.extend(["--core-exclude", ",".join(core_exclude)])
        if candidate_include:
            cmd.extend(["--candidate-include", ",".join(candidate_include)])
        if candidate_exclude:
            cmd.extend(["--candidate-exclude", ",".join(candidate_exclude)])
        if force_include:
            cmd.extend(["--force-include", ",".join(force_include)])
        if force_exclude:
            cmd.extend(["--force-exclude", ",".join(force_exclude)])
        if interaction_terms:
            cmd.extend(["--interaction-terms", ",".join(interaction_terms)])
        if tier_interaction_vars:
            cmd.extend(["--tier-interaction-vars", ",".join(tier_interaction_vars)])

        try:
            subprocess.Popen(
                cmd,
                cwd=str(settings.BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            messages.success(request, f"Regression experiment '{name}' launched.")
        except OSError as exc:
            messages.error(request, f"Failed to launch experiment: {exc}")
            experiment.status = ExperimentRun.STATUS_FAILED
            experiment.error_message = str(exc)
            experiment.save(update_fields=["status", "error_message"])

        return redirect("regression_control")

    experiments = ExperimentRun.objects.order_by("-created_at")[:100]
    status_counts = {
        "all": ExperimentRun.objects.count(),
        "completed": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_COMPLETED).count(),
        "running": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_RUNNING).count(),
        "failed": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_FAILED).count(),
        "pending": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_PENDING).count(),
    }

    return render(
        request,
        "openskagit/regression/control_center.html",
        {
            "experiments": experiments,
            "status_counts": status_counts,
            "predictor_profiles": predictor_profiles,
            "interaction_bundles": interaction_bundles,
            "form_defaults": form_defaults,
            "locked_mode": locked_mode,
            "segmentation_options": segmentation_options,
            "has_running": status_counts["running"] > 0,
            "core_predictor_options": core_predictor_options,
            "candidate_predictor_options": candidate_predictor_options,
            "interaction_term_options": interaction_term_options,
            "recipe_candidate_rows": recipe_candidate_rows,
        },
    )


@regression_gate_required
def experiment_list(request):
    status_filter = request.GET.get("status")
    starred_filter = request.GET.get("starred")
    search = request.GET.get("search")

    qs = ExperimentRun.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    if starred_filter == "true":
        qs = qs.filter(starred=True)
    if search:
        qs = qs.filter(name__icontains=search)

    experiments = qs.order_by("-created_at")[:200]
    status_counts = {
        "all": ExperimentRun.objects.count(),
        "completed": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_COMPLETED).count(),
        "running": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_RUNNING).count(),
        "failed": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_FAILED).count(),
        "pending": ExperimentRun.objects.filter(status=ExperimentRun.STATUS_PENDING).count(),
    }
    return render(
        request,
        "openskagit/experiments/list.html",
        {
            "experiments": experiments,
            "status_filter": status_filter,
            "starred_filter": starred_filter,
            "search": search,
            "status_counts": status_counts,
            "compare_candidates": ExperimentRun.objects.order_by("-created_at")[:50],
        },
    )


@regression_gate_required
def experiment_create(request):
    predictor_profiles = list(PREDICTOR_PROFILES.keys())
    interaction_bundles = list(INTERACTION_BUNDLES.keys())
    regression_modes = REGRESSION_MODES

    if request.method == "POST":
        name = request.POST.get("name") or "Untitled Experiment"
        mode = request.POST.get("mode") or "sfr"
        predictor_profile = request.POST.get("predictor_profile") or "baseline"
        interaction_bundle = request.POST.get("interaction_bundle") or "standard"
        countywide = request.POST.get("countywide") == "on"
        no_interactions = request.POST.get("no_interactions") == "on"
        market_group_col = request.POST.get("market_group_col") or "valuation_area"
        notes = request.POST.get("notes") or ""
        tags = _parse_tags(request.POST.get("tags", ""))

        experiment = ExperimentRun.objects.create(
            name=name,
            mode=mode,
            predictor_profile=predictor_profile,
            interaction_bundle=interaction_bundle,
            countywide=countywide,
            market_group_col=market_group_col,
            notes=notes,
            tags=tags,
            full_config={
                "mode": mode,
                "predictor_profile": predictor_profile,
                "interaction_bundle": interaction_bundle,
                "no_interactions": no_interactions,
                "countywide": countywide,
                "market_group_col": market_group_col,
                "tags": tags,
            },
        )

        manage_py = Path(settings.BASE_DIR) / "manage.py"
        cmd = [
            sys.executable,
            str(manage_py),
            "regression_masterparcel",
            "--experiment",
            "--experiment-id",
            str(experiment.id),
            "--mode",
            mode,
            "--predictor-set",
            predictor_profile,
            "--interactions",
            interaction_bundle,
            "--market-group-col",
            market_group_col,
        ]
        if no_interactions:
            cmd.append("--no-interactions")
        if countywide:
            cmd.append("--countywide")

        try:
            subprocess.Popen(
                cmd,
                cwd=str(settings.BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            messages.success(request, f"Experiment '{name}' launched.")
        except OSError as exc:
            messages.error(request, f"Failed to launch experiment: {exc}")
            experiment.status = ExperimentRun.STATUS_FAILED
            experiment.error_message = str(exc)
            experiment.save(update_fields=["status", "error_message"])

        return redirect(experiment.get_absolute_url())

    return render(
        request,
        "openskagit/experiments/create.html",
        {
            "predictor_profiles": predictor_profiles,
            "interaction_bundles": interaction_bundles,
            "regression_modes": regression_modes,
        },
    )


def _build_experiment_market_readouts(diagnostics: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    diagnostics = diagnostics or {}
    segments_raw = diagnostics.get("segments") or []
    coefficient_groups_raw = diagnostics.get("coefficients") or []

    coefficients_by_segment: Dict[str, List[Dict[str, Any]]] = {}
    for group in coefficient_groups_raw:
        if not isinstance(group, dict):
            continue
        segment_label = group.get("market_group")
        if not segment_label:
            continue
        rows = group.get("coefficients") or []
        coefficients_by_segment[segment_label] = [row for row in rows if isinstance(row, dict)]

    tier_rank = {
        "ALL": 0,
        "T1_LOW": 1,
        "T2_MID": 2,
        "T3_HIGH": 3,
    }

    grouped: Dict[str, Dict[str, Any]] = {}
    market_order: List[str] = []

    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue

        market_group = str(seg.get("market_group") or "UNKNOWN")
        segment_label = str(seg.get("segment") or f"{market_group}__{seg.get('value_tier') or 'ALL'}")
        performance = seg.get("performance") if isinstance(seg.get("performance"), dict) else {}
        predictors = seg.get("predictors") if isinstance(seg.get("predictors"), dict) else {}
        ratio_distribution = seg.get("ratio_distribution") if isinstance(seg.get("ratio_distribution"), dict) else {}
        calibration = seg.get("calibration") if isinstance(seg.get("calibration"), dict) else {}
        predictors_all = predictors.get("all") if isinstance(predictors.get("all"), list) else []
        predictors_mandatory = predictors.get("mandatory") if isinstance(predictors.get("mandatory"), list) else []
        predictors_added = predictors.get("added") if isinstance(predictors.get("added"), list) else []
        calibration_bands = calibration.get("bands") if isinstance(calibration.get("bands"), list) else []
        flags = seg.get("flags") if isinstance(seg.get("flags"), list) else []
        errors = seg.get("errors") if isinstance(seg.get("errors"), list) else []

        vif_raw = seg.get("vif") if isinstance(seg.get("vif"), dict) else {}
        vif_rows: List[Dict[str, Any]] = []
        for term, value in vif_raw.items():
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            vif_rows.append({"term": term, "value": round(float(numeric_value), 3)})
        vif_rows.sort(key=lambda row: row["value"], reverse=True)

        segment_entry = {
            "segment_label": segment_label,
            "value_tier": str(seg.get("value_tier") or "ALL"),
            "performance": performance,
            "ratio_distribution": ratio_distribution,
            "predictors_all": predictors_all,
            "predictors_mandatory": predictors_mandatory,
            "predictors_added": predictors_added,
            "coefficients": coefficients_by_segment.get(segment_label, []),
            "vif_rows": vif_rows,
            "calibration_bands": calibration_bands,
            "calibration_prb": calibration.get("prb"),
            "flags": flags,
            "errors": errors,
            "time_trend": seg.get("time_trend") if isinstance(seg.get("time_trend"), dict) else None,
        }

        if market_group not in grouped:
            grouped[market_group] = {
                "market_group": market_group,
                "segments": [],
                "segment_count": 0,
                "observation_total": 0,
            }
            market_order.append(market_group)

        grouped[market_group]["segments"].append(segment_entry)
        grouped[market_group]["segment_count"] += 1
        grouped[market_group]["observation_total"] += int(performance.get("n") or 0)

    market_groups: List[Dict[str, Any]] = []
    for market_group in market_order:
        group_entry = grouped[market_group]
        group_entry["segments"].sort(
            key=lambda row: (tier_rank.get(row.get("value_tier"), 99), row.get("segment_label", ""))
        )
        market_groups.append(group_entry)

    return market_groups


@regression_gate_required
def experiment_detail(request, experiment_id):
    experiment = get_object_or_404(ExperimentRun, id=experiment_id)
    diagnostics = _load_diagnostics(experiment.diagnostics_path)
    segments = diagnostics.get("segments", []) if diagnostics else []
    stats = diagnostics.get("stats", []) if diagnostics else []
    coefficients = diagnostics.get("coefficients", []) if diagnostics else []

    methodology_context: Dict[str, Any] = {}
    diagnostics_warning = ""
    if diagnostics:
        try:
            methodology_context = _build_methodology_context_from_diagnostics(diagnostics)
        except Exception as exc:  # pragma: no cover - defensive fallback for historical payloads
            logger.exception("Failed to build methodology context for experiment %s: %s", experiment_id, exc)
            diagnostics_warning = "Diagnostics loaded, but parts of this run use an older format and could not be fully rendered."

    global_metrics = diagnostics.get("global_metrics") if isinstance(diagnostics, dict) else {}
    if not isinstance(global_metrics, dict):
        global_metrics = {}

    predictor_inventory = diagnostics.get("predictor_inventory") if isinstance(diagnostics, dict) else {}
    if not isinstance(predictor_inventory, dict):
        predictor_inventory = {}

    predictor_overrides = diagnostics.get("predictor_overrides") if isinstance(diagnostics, dict) else {}
    if not isinstance(predictor_overrides, dict):
        predictor_overrides = {}

    market_group_readouts = _build_experiment_market_readouts(diagnostics)

    return render(
        request,
        "openskagit/experiments/detail.html",
        {
            "experiment": experiment,
            "diagnostics": diagnostics,
            "segments": segments,
            "stats": stats,
            "coefficients": coefficients,
            "diagnostics_warning": diagnostics_warning,
            "global_metrics": global_metrics,
            "predictor_inventory": predictor_inventory,
            "predictor_overrides": predictor_overrides,
            "market_group_readouts": market_group_readouts,
            **methodology_context,
        },
    )


@regression_gate_required
def experiment_status_json(request, experiment_id):
    experiment = get_object_or_404(ExperimentRun, id=experiment_id)
    progress = None
    if experiment.status == ExperimentRun.STATUS_RUNNING:
        progress = 0.1  # placeholder for future estimate
    elif experiment.status == ExperimentRun.STATUS_COMPLETED:
        progress = 1.0
    return JsonResponse(
        {
            "status": experiment.status,
            "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
            "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
            "error_message": experiment.error_message,
            "run_id": experiment.run_id,
            "progress": progress,
        }
    )


@regression_gate_required
def experiment_compare(request):
    exp1_id = request.GET.get("exp1")
    exp2_id = request.GET.get("exp2")
    exp1 = exp2 = None
    diag1 = diag2 = None

    if exp1_id:
        exp1 = ExperimentRun.objects.filter(id=exp1_id).first()
        diag1 = _load_diagnostics(exp1.diagnostics_path) if exp1 else None
    if exp2_id:
        exp2 = ExperimentRun.objects.filter(id=exp2_id).first()
        diag2 = _load_diagnostics(exp2.diagnostics_path) if exp2 else None

    return render(
        request,
        "openskagit/experiments/compare.html",
        {
            "exp1": exp1,
            "exp2": exp2,
            "diag1": diag1,
            "diag2": diag2,
            "all_experiments": ExperimentRun.objects.order_by("-created_at")[:50],
        },
    )
FLAVOR_DIMENSIONS = [
    "sweet",
    "salty",
    "sour",
    "bitter",
    "umami",
    "spicy",
    "smoky",
    "fatty",
    "acidic",
    "herbal",
]
HERO_FLAVORS = ["sweet", "umami", "fatty", "herbal", "spicy"]
MIN_CITY_ITEMS_FOR_LEADER = 15
FLAVOR_EMOJIS = {
    "sweet": "🍓",
    "salty": "🧂",
    "sour": "🍋",
    "bitter": "🌿",
    "umami": "🍄",
    "spicy": "🌶️",
    "smoky": "🔥",
    "fatty": "🥧",
    "acidic": "🍊",
    "herbal": "🌱",
}
