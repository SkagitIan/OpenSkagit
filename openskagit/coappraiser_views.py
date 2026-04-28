import csv
from typing import Optional

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from openskagit.models import CoAppraiserParcelSet, CoAppraiserParcelSetItem, CoAppraiserRoutePlan
from openskagit.services import coappraiser_routes
from openskagit.views import _basic_page_context


def _client_ip(request) -> Optional[str]:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip() or None


def _load_page_state(request):
    parcel_set_id = (request.GET.get("parcel_set") or "").strip()
    plan_id = (request.GET.get("plan") or "").strip()

    parcel_set = None
    if parcel_set_id:
        parcel_set = CoAppraiserParcelSet.objects.filter(id=parcel_set_id).first()

    plan = None
    if plan_id:
        plan = CoAppraiserRoutePlan.objects.filter(id=plan_id).first()
    elif parcel_set:
        plan = parcel_set.route_plans.order_by("-created_at").first()

    if plan and parcel_set is None:
        parcel_set = plan.parcel_set

    return parcel_set, plan


def _parcel_set_summary(parcel_set: CoAppraiserParcelSet) -> dict:
    missing_rows = list(
        parcel_set.items.filter(status=CoAppraiserParcelSetItem.STATUS_MISSING)
        .order_by("source_row", "parcel_number_normalized")
        .values("parcel_number_normalized", "source_row")[:25]
    )
    missing_geometry_rows = list(
        parcel_set.items.filter(status=CoAppraiserParcelSetItem.STATUS_MISSING_GEOMETRY)
        .order_by("source_row", "parcel_number_normalized")
        .values("parcel_number_normalized", "source_row")[:25]
    )
    ready_preview = list(
        parcel_set.items.filter(status=CoAppraiserParcelSetItem.STATUS_READY)
        .order_by("source_row", "parcel_number_normalized")
        .values("parcel_number_normalized", "situs_address")[:20]
    )
    return {
        "missing_rows": missing_rows,
        "missing_geometry_rows": missing_geometry_rows,
        "ready_preview": ready_preview,
    }


def _plan_map_payload(plan: Optional[CoAppraiserRoutePlan]) -> Optional[dict]:
    if not plan or plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        return None
    result = plan.result if isinstance(plan.result, dict) else {}
    if not isinstance(result, dict):
        return None
    return result


def _route_context(plan: CoAppraiserRoutePlan, cluster_id: str) -> dict:
    result = plan.result if isinstance(plan.result, dict) else {}
    routes = result.get("routes") if isinstance(result.get("routes"), list) else []
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        if str(route.get("cluster_id") or "") == str(cluster_id):
            return {
                "plan": plan,
                "route": route,
                "route_index": idx,
                "route_imagery_manual_modal_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/imagery/manual/modal/",
                "route_imagery_manual_draft_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/imagery/manual/draft/",
                "route_imagery_manual_continue_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/imagery/manual/continue/",
                "route_listing_start_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/listing/start/",
                "route_listing_tick_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/listing/tick/",
                "route_drive_start_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/drive/start/",
                "route_rows_url": f"/coappraiser/plan/{plan.id}/route/{cluster_id}/rows/",
            }
    raise coappraiser_routes.CoAppraiserError(f"Route '{cluster_id}' not found in plan.")


def _parse_post_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@require_http_methods(["GET", "POST"])
def coappraiser_page(request):
    if request.method == "POST":
        upload = request.FILES.get("csv_file")
        if upload is None:
            messages.error(request, "Choose a CSV file to upload.")
            return redirect("coappraiser-upload")
        try:
            parcel_set = coappraiser_routes.create_parcel_set_from_upload(
                upload,
                client_ip=_client_ip(request),
                display_name=(request.POST.get("name") or "").strip(),
            )
        except coappraiser_routes.CoAppraiserError as exc:
            messages.error(request, str(exc))
            return redirect("coappraiser-upload")
        messages.success(
            request,
            f"Uploaded {parcel_set.source_filename}. "
            f"Ready: {parcel_set.found_count}, missing: {parcel_set.missing_count}, "
            f"missing geometry: {parcel_set.missing_geometry_count}.",
        )
        return redirect(f"{request.path}?parcel_set={parcel_set.id}")

    parcel_set, plan = _load_page_state(request)
    context = _basic_page_context(
        "CO Appraiser Parcel Route Planner · OpenSkagit",
        "Upload parcel CSVs and generate day-sized geographic routes for field inspection planning.",
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    context["mode_presets"] = [
        {
            "value": key,
            **preset,
        }
        for key, preset in coappraiser_routes.MODE_PRESETS.items()
    ]
    context["parcel_set"] = parcel_set
    context["parcel_set_details"] = _parcel_set_summary(parcel_set) if parcel_set else None
    context["plan"] = plan
    context["plan_result"] = plan.result if plan and isinstance(plan.result, dict) else None
    context["plan_map_payload"] = _plan_map_payload(plan)
    context["recent_parcel_sets"] = CoAppraiserParcelSet.objects.order_by("-created_at")[:8]
    if parcel_set:
        context["recent_plans"] = parcel_set.route_plans.order_by("-created_at")[:8]
    else:
        context["recent_plans"] = []
    return render(request, "openskagit/coappraiser_upload.html", context)


@require_http_methods(["GET", "POST"])
def coappraiser_generate_plan(request, parcel_set_id):
    parcel_set = get_object_or_404(CoAppraiserParcelSet, id=parcel_set_id)
    if request.method == "GET":
        return redirect(f"/coappraiser/?parcel_set={parcel_set.id}")
    mode = (request.POST.get("mode") or CoAppraiserRoutePlan.MODE_DRIVING).strip()

    if coappraiser_routes.should_generate_plan_async(parcel_set):
        plan = None
        try:
            plan = coappraiser_routes.create_route_plan(parcel_set, mode=mode)
            coappraiser_routes.enqueue_route_plan_generation(plan)
        except coappraiser_routes.CoAppraiserError as exc:
            if plan is not None:
                plan.status = CoAppraiserRoutePlan.STATUS_FAILED
                plan.error_message = f"Queue failure: {exc}"
                plan.save(update_fields=["status", "error_message", "updated_at"])
            messages.error(request, str(exc))
            return redirect(f"/coappraiser/?parcel_set={parcel_set.id}")
        except Exception as exc:
            if plan is not None:
                plan.status = CoAppraiserRoutePlan.STATUS_FAILED
                plan.error_message = f"Queue failure: {exc}"
                plan.save(update_fields=["status", "error_message", "updated_at"])
            messages.error(request, f"Route generation queue failed: {exc}")
            return redirect(f"/coappraiser/?parcel_set={parcel_set.id}")

        messages.success(
            request,
            f"Queued route generation for {parcel_set.found_count} parcels. This page will refresh until it completes.",
        )
        return redirect(f"/coappraiser/?parcel_set={parcel_set.id}&plan={plan.id}")

    try:
        plan = coappraiser_routes.generate_route_plan(parcel_set, mode=mode)
    except coappraiser_routes.CoAppraiserError as exc:
        messages.error(request, str(exc))
        return redirect(f"/coappraiser/?parcel_set={parcel_set.id}")
    except Exception as exc:
        messages.error(request, f"Route generation failed: {exc}")
        latest_plan = parcel_set.route_plans.order_by("-created_at").first()
        if latest_plan:
            return redirect(f"/coappraiser/?parcel_set={parcel_set.id}&plan={latest_plan.id}")
        return redirect(f"/coappraiser/?parcel_set={parcel_set.id}")

    messages.success(
        request,
        f"Generated {plan.cluster_count} route(s) for {plan.routed_stop_count} parcels "
        f"in {plan.get_mode_display().lower()} mode.",
    )
    return redirect(f"/coappraiser/?parcel_set={parcel_set.id}&plan={plan.id}")


@require_POST
def coappraiser_move_plan_stop(request, plan_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    item_id_raw = (request.POST.get("item_id") or "").strip()
    target_cluster_id = (request.POST.get("target_cluster_id") or "").strip()
    try:
        item_id = int(item_id_raw)
    except (TypeError, ValueError):
        messages.error(request, "Invalid parcel move request (missing parcel id).")
        return redirect(f"/coappraiser/?parcel_set={plan.parcel_set_id}&plan={plan.id}")

    try:
        updated_plan = coappraiser_routes.move_plan_stop_to_route(
            plan,
            item_id=item_id,
            target_cluster_id=target_cluster_id,
        )
    except coappraiser_routes.CoAppraiserError as exc:
        messages.error(request, str(exc))
        return redirect(f"/coappraiser/?parcel_set={plan.parcel_set_id}&plan={plan.id}")
    except Exception as exc:
        messages.error(request, f"Move failed: {exc}")
        return redirect(f"/coappraiser/?parcel_set={plan.parcel_set_id}&plan={plan.id}")

    messages.success(request, "Parcel moved to the selected route.")
    return redirect(f"/coappraiser/?parcel_set={updated_plan.parcel_set_id}&plan={updated_plan.id}")


@require_GET
def coappraiser_export_plan_csv(request, plan_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="coappraiser_route_plan_{plan.id}.csv"'
    writer = csv.writer(response)
    writer.writerow(["day", "cluster_id", "stop_order", "parcel_number", "address", "lat", "lon", "eta_seconds"])
    for row in coappraiser_routes.route_plan_export_rows(plan):
        writer.writerow(row)
    return response


@require_GET
def coappraiser_route_imagery_manual_modal(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    try:
        plan, manual_imagery = coappraiser_routes.run_route_imagery_manual_modal_context(
            plan,
            cluster_id=cluster_id,
        )
        context = _route_context(plan, cluster_id)
        context["manual_imagery"] = manual_imagery
        context["include_panel_oob"] = False
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Manual imagery modal failed: {exc}", status=500)
    return render(request, "openskagit/partials/coappraiser_route_imagery_manual_modal.html", context)


@require_POST
def coappraiser_route_imagery_manual_draft(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    item_id_raw = (request.POST.get("item_id") or "").strip()
    try:
        item_id = int(item_id_raw)
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_item_id"}, status=400)
    flagged = _parse_post_bool(request.POST.get("flagged"), default=False)
    manual_comment = (request.POST.get("manual_comment") or "").strip()
    try:
        _, payload = coappraiser_routes.run_route_imagery_manual_draft(
            plan,
            cluster_id=cluster_id,
            item_id=item_id,
            flagged=flagged,
            manual_comment=manual_comment,
        )
    except coappraiser_routes.CoAppraiserError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": f"draft_failed: {exc}"}, status=500)
    return JsonResponse(
        {
            "ok": True,
            "item_id": payload.get("item_id"),
            "flagged": payload.get("flagged"),
            "manual_comment": payload.get("manual_comment"),
            "saved_at": payload.get("saved_at"),
            "saved_at_label": payload.get("saved_at_label"),
        }
    )


@require_POST
def coappraiser_route_imagery_manual_continue(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    item_id_raw = (request.POST.get("item_id") or "").strip()
    item_id = None
    if item_id_raw:
        try:
            item_id = int(item_id_raw)
        except (TypeError, ValueError):
            return HttpResponse("Invalid parcel id.", status=400)
    flagged = _parse_post_bool(request.POST.get("flagged"), default=False)
    manual_comment = request.POST.get("manual_comment")
    try:
        plan, manual_imagery = coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id=cluster_id,
            item_id=item_id,
            flagged=flagged,
            manual_comment=manual_comment,
        )
        context = _route_context(plan, cluster_id)
        context["manual_imagery"] = manual_imagery
        context["include_panel_oob"] = True
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Manual imagery continue failed: {exc}", status=500)
    return render(request, "openskagit/partials/coappraiser_route_imagery_manual_modal.html", context)


@require_POST
def coappraiser_route_listing_start(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    try:
        plan = coappraiser_routes.run_route_listing_scan_step(
            plan,
            cluster_id=cluster_id,
            reset=True,
        )
        context = _route_context(plan, cluster_id)
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Route listing start failed: {exc}", status=500)
    return render(request, "openskagit/partials/coappraiser_route_scan_fragment.html", context)


@require_GET
def coappraiser_route_listing_tick(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    try:
        plan = coappraiser_routes.run_route_listing_scan_step(
            plan,
            cluster_id=cluster_id,
            reset=False,
        )
        context = _route_context(plan, cluster_id)
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Route listing scan failed: {exc}", status=500)
    return render(request, "openskagit/partials/coappraiser_route_scan_fragment.html", context)


@require_POST
def coappraiser_route_drive_start(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    try:
        plan = coappraiser_routes.run_route_driving_line(
            plan,
            cluster_id=cluster_id,
        )
        context = _route_context(plan, cluster_id)
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Route driving line failed: {exc}", status=500)

    response = render(request, "openskagit/partials/coappraiser_route_scan_fragment.html", context)
    response["HX-Refresh"] = "true"
    return response


@require_GET
def coappraiser_route_stop_rows(request, plan_id, cluster_id):
    plan = get_object_or_404(CoAppraiserRoutePlan, id=plan_id)
    try:
        context = _route_context(plan, cluster_id)
    except coappraiser_routes.CoAppraiserError as exc:
        return HttpResponse(str(exc), status=400)
    except Exception as exc:
        return HttpResponse(f"Route rows load failed: {exc}", status=500)
    return render(request, "openskagit/partials/coappraiser_route_stop_body.html", context)
