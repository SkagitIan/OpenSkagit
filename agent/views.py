import hashlib
import hmac
import json
import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, List

import requests
from django.conf import settings
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import stripe
from stripe import StripeError as StripeAPIError

from .models import (
    CompetitionAnalysisJob,
    JobStatus,
    PaymentRecord,
    PaymentStatus,
    RestaurantReport,
    RestaurantReportJob,
)
from .pipeline.tasks import run_report_job
from .services.competition_analysis import CompetitionAnalysisService

logger = logging.getLogger(__name__)


def competition_analysis_dashboard(request):
    description = "Build a competition analysis dossier for your restaurant and watch grounded intel arrive in JSON."
    context = {
        "service_ready": bool(settings.GOOGLE_PLACES_API_KEY and settings.GENAI_API_KEY),
        "meta_description": description,
        "og_description": description,
        "twitter_description": description,
        "og_url": request.build_absolute_uri(),
        "google_places_api_key": settings.GOOGLE_PLACES_API_KEY,
    }
    return render(request, "agent/competition_analysis.html", context)


@require_POST
def competition_analysis_search(request):
    query = (request.POST.get("query") or "").strip()
    place_id = (request.POST.get("place_id") or "").strip()
    if not query and not place_id:
        return render(
            request,
            "agent/partials/competition_search_results.html",
            {"error": "Tell me the restaurant name that you want to analyze.", "query": ""},
        )

    results = []
    if place_id:
        try:
            results = [_describe_place(place_id)]
        except ValueError as exc:
            return render(
                request,
                "agent/partials/competition_search_results.html",
                {"error": str(exc), "query": query},
            )
        except requests.RequestException as exc:
            return render(
                request,
                "agent/partials/competition_search_results.html",
                {"error": f"Google Places lookup failed: {exc}", "query": query},
            )
    else:
        try:
            results = _google_text_search(query)
        except ValueError as exc:
            return render(
                request,
                "agent/partials/competition_search_results.html",
                {"error": str(exc), "query": query},
            )
        except requests.RequestException as exc:
            return render(
                request,
                "agent/partials/competition_search_results.html",
                {"error": f"Google Places search failed: {exc}", "query": query},
            )

    return render(
        request,
        "agent/partials/competition_search_results.html",
        {"results": results, "query": query},
    )


@require_POST
def competition_analysis_select_subject(request):
    place_id = request.POST.get("place_id")
    if not place_id:
        return HttpResponseBadRequest("place_id is required to scope the subject.")

    job = CompetitionAnalysisJob.objects.create(place_id=place_id)
    job.append_log("Scouting subject details.")

    try:
        job = _run_scout_phase(job)
    except Exception as exc:
        context = {
            "error": str(exc),
            "job": job,
            "vetted_competitors": job.vetted_competitors or [],
            "subject_payload": job.subject_payload or {},
            "subject_json": json.dumps(job.subject_payload or {}, indent=2),
            "competitors_json": json.dumps(job.vetted_competitors or [], indent=2),
        }
        return render(request, "agent/partials/subject_preview.html", context)

    return render(
        request,
        "agent/partials/subject_preview.html",
        {
            "job": job,
            "vetted_competitors": job.vetted_competitors or [],
            "subject_payload": job.subject_payload or {},
            "subject_json": json.dumps(job.subject_payload or {}, indent=2),
            "competitors_json": json.dumps(job.vetted_competitors or [], indent=2),
        },
    )


@require_POST
def competition_analysis_start(request):
    job_id = request.POST.get("job_id")
    if not job_id:
        return HttpResponseBadRequest("Missing job_id.")

    job = get_object_or_404(CompetitionAnalysisJob, pk=job_id)
    if job.status in {job.STATUS_COMPLETED, job.STATUS_FAILED}:
        return _render_status_partial(request, job)

    if job.status == job.STATUS_READY:
        job.status = job.STATUS_DEEP_PENDING
        job.append_log("Deep competitor analysis queued.", save=False)
        job.save(update_fields=["status", "progress_log"])
        thread = threading.Thread(target=_run_deep_analysis_in_background, args=(str(job.id),), daemon=True)
        thread.start()

    return _render_status_partial(request, job)


@require_GET
def competition_analysis_status(request, job_id):
    job = get_object_or_404(CompetitionAnalysisJob, pk=job_id)
    return _render_status_partial(request, job)


def _run_scout_phase(job: CompetitionAnalysisJob) -> CompetitionAnalysisJob:
    try:
        service = _build_service()
    except ValueError as exc:
        job.status = job.STATUS_FAILED
        job.error_message = str(exc)
        job.append_log(f"Service misconfigured: {exc}", save=False)
        job.save(update_fields=["status", "error_message", "progress_log"])
        raise

    try:
        subject_payload, vetted = service.run_scout_and_enrich(job.place_id)
        job.subject_payload = subject_payload
        job.vetted_competitors = vetted
        job.name = subject_payload.get("name") or job.name
        job.address = subject_payload.get("address") or job.address
        job.status = job.STATUS_READY
        job.append_log("Subject scouting complete; vetted competitors ready.", save=False)
        job.save(
            update_fields=[
                "name",
                "address",
                "status",
                "subject_payload",
                "vetted_competitors",
                "progress_log",
            ]
        )
        return job
    except Exception as exc:
        job.status = job.STATUS_FAILED
        job.error_message = str(exc)
        job.append_log(f"Subject scouting failed: {exc}", save=False)
        job.save(update_fields=["status", "error_message", "progress_log"])
        raise


def _run_deep_analysis_in_background(job_id: str) -> None:
    try:
        job = CompetitionAnalysisJob.objects.get(pk=job_id)
    except CompetitionAnalysisJob.DoesNotExist:
        return

    job.status = job.STATUS_DEEP_RUNNING
    job.append_log("Deep competitor analysis started.", save=False)
    job.save(update_fields=["status", "progress_log"])

    try:
        service = _build_service()
    except ValueError as exc:
        job.status = job.STATUS_FAILED
        job.error_message = str(exc)
        job.append_log(f"Deep analysis aborted: {exc}", save=False)
        job.save(update_fields=["status", "error_message", "progress_log"])
        return

    if not job.subject_payload or job.vetted_competitors is None:
        job.status = job.STATUS_FAILED
        job.error_message = "Missing scout payload; deep analysis cannot continue."
        job.append_log("Deep analysis aborted: missing scout payload.", save=False)
        job.save(update_fields=["status", "error_message", "progress_log"])
        return

    try:
        result = service.run_deep_competitor_analysis(job.subject_payload, job.vetted_competitors)
        job.final_payload = result
        job.status = job.STATUS_COMPLETED
        job.append_log("Deep competitor analysis completed.", save=False)
    except Exception as exc:
        job.status = job.STATUS_FAILED
        job.error_message = str(exc)
        job.append_log(f"Deep analysis failed: {exc}", save=False)
    finally:
        job.save(
            update_fields=["status", "final_payload", "error_message", "progress_log"]
        )


def _build_service() -> CompetitionAnalysisService:
    return CompetitionAnalysisService(
        google_api_key=settings.GOOGLE_PLACES_API_KEY,
        genai_api_key=settings.GENAI_API_KEY,
        outscraper_api_key=getattr(settings, "OUTSCRAPER_API_KEY", None),
    )


def _google_text_search(query: str, max_result: int = 6) -> List[dict]:
    api_key = settings.GOOGLE_PLACES_API_KEY
    if not api_key:
        raise ValueError("Add GOOGLE_PLACES_API_KEY to .env before running the search.")

    url = "https://places.googleapis.com/v1/places:searchText"
    payload = {"textQuery": query, "maxResultCount": max_result}
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response.raise_for_status()
    return response.json().get("places", [])


def _describe_place(place_id: str) -> dict:
    service = _build_service()
    return service.fetch_place_summary(place_id)


def _render_status_partial(request, job: CompetitionAnalysisJob):
    final_payload = ""
    if job.final_payload:
        final_payload = json.dumps(job.final_payload, indent=2)

    context = {
        "job": job,
        "final_payload": final_payload,
    }
    return render(request, "agent/partials/competition_analysis_status.html", context)


@require_GET
def report_start(request):
    """Landing page where users select a restaurant."""

    context = {
        "google_places_api_key": settings.GOOGLE_PLACES_API_KEY,
        "status_page_url": reverse("agent-report-status-page", args=["JOB_ID"]),
    }
    return render(request, "agent/report_start.html", context)


@require_GET
def report_status_page(request, job_id: str):
    job = get_object_or_404(RestaurantReportJob, pk=job_id)
    return render(request, "agent/report_status.html", {"job": job})


@csrf_exempt
@require_POST
def report_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = _verify_stripe_signature(payload, sig_header)
    except ValueError as exc:
        logger.warning("Stripe webhook failed validation: %s", exc)
        return HttpResponseBadRequest(str(exc))

    session = event.get("data", {}).get("object", {})
    session_id = session.get("id")
    event_type = event.get("type")
    if not session_id:
        return HttpResponseBadRequest("Missing session id.")

    payment = PaymentRecord.objects.filter(stripe_session_id=session_id).first()
    if not payment:
        return HttpResponseBadRequest("Payment record not found.")

    job = payment.job
    if event_type == "checkout.session.completed":
        payment.status = PaymentStatus.PAID
        amount = session.get("amount_total")
        if amount:
            try:
                payment.amount_usd = Decimal(amount) / Decimal(100)
            except InvalidOperation:
                pass
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "amount_usd", "paid_at"])
        job.status = JobStatus.PAID
        job.log("Stripe webhook marked job paid.")
        job.save(update_fields=["status", "progress_log"])
        run_report_job.delay(job.id)
    return JsonResponse({"received": True})


def _verify_stripe_signature(payload: bytes, signature_header: str) -> dict:
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise ValueError("Stripe webhook secret not configured.")
    if not signature_header:
        raise ValueError("Missing signature header.")

    sig_parts = {}
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        sig_parts[key] = value

    timestamp = sig_parts.get("t")
    signature = sig_parts.get("v1")
    if not timestamp or not signature:
        raise ValueError("Incomplete Stripe signature header.")

    signed_payload = f"{timestamp}.{payload.decode('utf-8', 'ignore')}"
    expected_signature = hmac.new(
        secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise ValueError("Stripe signature mismatch.")

    if abs(time.time() - int(timestamp)) > 300:
        raise ValueError("Webhook timestamp outside tolerance.")

    return json.loads(payload)


def _ensure_stripe_ready() -> str:
    """Validate the Stripe configuration and return the price id."""

    secret_key = settings.STRIPE_SECRET_KEY
    price_id = settings.STRIPE_PRICE_ID
    if not secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID is not configured.")

    stripe.api_key = secret_key
    return price_id


def _create_checkout_session(request, job: RestaurantReportJob):
    """Build a Stripe Checkout session for the provided job."""

    price_id = _ensure_stripe_ready()
    stripe_module = stripe
    base_url = request.build_absolute_uri(reverse("agent-report-status-page", args=[job.id]))
    success_url = f"{base_url}?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = base_url

    session = stripe_module.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"job_id": job.id},
    )

    return session


def _parse_request_body(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


@require_POST
def report_create(request):
    data: Dict[str, str] = _parse_request_body(request)
    place_id = data.get("place_id")
    if not place_id:
        return JsonResponse({"error": "place_id is required."}, status=400)

    job = RestaurantReportJob.objects.create(
        place_id=place_id,
        place_name=data.get("place_name", ""),
        address=data.get("address", ""),
    )
    job.log("Report job created.")
    return JsonResponse({"job_id": job.id, "status": job.status})


@require_POST
def report_checkout(request):
    data: Dict[str, str] = _parse_request_body(request)
    job_id = data.get("job_id")
    if not job_id:
        return JsonResponse({"error": "job_id is required."}, status=400)

    job = get_object_or_404(RestaurantReportJob, pk=job_id)
    try:
        session = _create_checkout_session(request, job)
    except RuntimeError as exc:
        logger.warning("Stripe checkout configuration: %s", exc)
        return JsonResponse({"error": str(exc)}, status=400)
    except StripeAPIError:
        logger.exception("Stripe checkout session creation failed for job %s", job.id)
        return JsonResponse(
            {"error": "Unable to create Stripe checkout session at this time."},
            status=502,
        )

    amount = getattr(session, "amount_total", None) or session.get("amount_total")
    amount_usd = None
    if amount:
        try:
            amount_usd = Decimal(str(amount)) / Decimal(100)
        except (InvalidOperation, ValueError, TypeError):
            amount_usd = None

    checkout_url = getattr(session, "url", None) or session.get("url")
    if not checkout_url:
        logger.error("Stripe session %s missing url", session.id)
        return JsonResponse(
            {"error": "Stripe session is missing a redirect URL."}, status=502
        )

    PaymentRecord.objects.update_or_create(
        job=job,
        defaults={
            "stripe_session_id": session.id,
            "status": PaymentStatus.PENDING,
            "amount_usd": amount_usd,
            "note": f"Checkout session {session.id} created.",
        },
    )
    job.log("Stripe checkout session created.")
    return JsonResponse({"checkout_url": checkout_url, "session_id": session.id})


@require_GET
def report_status(request, job_id: str):
    job = get_object_or_404(RestaurantReportJob, pk=job_id)
    report_url = None
    try:
        slug = job.report.slug
    except RestaurantReport.DoesNotExist:
        slug = None

    if slug:
        report_url = request.build_absolute_uri(reverse("agent-report-view", args=[slug]))

    return JsonResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "progress_percent": job.progress_percent,
            "current_step": job.current_step,
            "report_url": report_url,
            "error_message": job.error_message,
        }
    )


@require_GET
def report_view(request, slug: str):
    report = get_object_or_404(RestaurantReport, slug=slug)
    try:
        payload = json.loads(report.payload)
    except json.JSONDecodeError:
        raise Http404("Malformed report payload.")
    return render(request, "agent/report_view.html", {"payload": payload})
