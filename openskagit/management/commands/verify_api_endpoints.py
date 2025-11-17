from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse

from openskagit import appeals
from openskagit.models import Assessor, NeighborhoodMetrics


@dataclass
class EndpointContext:
    parcel_number: str
    parcel_address: str
    address_query: str
    appeal_query: str
    city_district: str
    neighborhood_code: str
    latitude: float
    longitude: float


class Command(BaseCommand):
    help = "Exercise every public API endpoint with live data and report detailed results."

    def __init__(self):
        super().__init__()
        self.client = Client()
        self.last_comparable: Optional[Dict[str, object]] = None

    def handle(self, *args, **options):
        context = self._build_context()
        checks = [
            ("Parcel Detail", lambda: self._test_parcel_detail(context)),
            ("Sales Leaderboard", self._test_sales_list),
            ("Parcel Search", lambda: self._test_parcel_search(context)),
            ("Parcel Summary", lambda: self._test_parcel_summary(context)),
            ("Semantic Search", lambda: self._test_semantic_search(context)),
            ("Nearby Parcels", lambda: self._test_nearby(context)),
            ("Neighborhood Stats", lambda: self._test_neighborhood_stats(context)),
            ("Appeal Analysis", lambda: self._test_appeal_analysis(context)),
            ("Appeal Search", lambda: self._test_appeal_search(context)),
            ("Appeal Subject", lambda: self._test_appeal_subject(context)),
            ("Appeal Comparables", lambda: self._test_appeal_comparables(context)),
            ("Comparable Improvements", lambda: self._test_comparable_improvements(context)),
        ]

        failures = 0
        for name, func in checks:
            start = time.perf_counter()
            try:
                detail = func()
                elapsed = time.perf_counter() - start
                self.stdout.write(self.style.SUCCESS(f"[PASS] {name:<24} {detail} ({elapsed:.2f}s)"))
            except Exception as exc:  # pragma: no cover
                failures += 1
                elapsed = time.perf_counter() - start
                self.stdout.write(self.style.ERROR(f"[FAIL] {name:<24} {exc} ({elapsed:.2f}s)"))

        if failures:
            raise CommandError(f"API verification failed for {failures} endpoint(s).")

        self.stdout.write(self.style.SUCCESS(f"Verified {len(checks)} endpoints with live data."))

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------
    def _base_assessor_qs(self):
        return (
            Assessor.objects.select_related("roll")
            .filter(property_type__isnull=False)
            .filter(property_type__iexact="R")
            .exclude(parcel_number__isnull=True)
            .exclude(parcel_number__exact="")
        )

    def _build_context(self) -> EndpointContext:
        subject = self._find_parcel_with_comparables()
        coords_record = (
            self._base_assessor_qs()
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .order_by("-roll__year")
            .first()
        )
        if not coords_record:
            raise CommandError("No assessor record with latitude/longitude for /api/nearby.")

        city_record = (
            self._base_assessor_qs()
            .exclude(city_district__isnull=True)
            .exclude(city_district__exact="")
            .order_by("-roll__year")
            .first()
        )
        if not city_record or not city_record.city_district:
            raise CommandError("Unable to locate a parcel with city_district for parcel summary.")

        metric = NeighborhoodMetrics.objects.order_by("-year").first()
        if not metric or not metric.neighborhood_code:
            raise CommandError("NeighborhoodMetrics is empty. Run update_neighborhood_metrics first.")

        if not self._base_assessor_qs().exclude(embedding__isnull=True).exists():
            raise CommandError("No embeddings detected. Run `generate_embeddings` before verifying semantic search.")

        parcel_number = subject.parcel_number.strip()
        parcel_address = (subject.address or "").strip()
        address_query = self._address_token(parcel_address, parcel_number)

        return EndpointContext(
            parcel_number=parcel_number,
            parcel_address=parcel_address,
            address_query=address_query,
            appeal_query=parcel_number,
            city_district=city_record.city_district.strip(),
            neighborhood_code=metric.neighborhood_code.strip(),
            latitude=float(coords_record.latitude),
            longitude=float(coords_record.longitude),
        )

    def _find_parcel_with_comparables(self) -> Assessor:
        candidate_qs = (
            self._base_assessor_qs()
            .exclude(address__isnull=True)
            .exclude(address__exact="")
            .order_by("-roll__year")[:200]
        )
        for record in candidate_qs:
            try:
                subject, _ = appeals.load_subject_with_roll_context(record.parcel_number)
                comparables, _ = appeals._comparable_candidates(subject, appeals.INITIAL_COMPARABLE_LIMIT)
                if comparables:
                    return record
            except Exception:
                continue
        raise CommandError("Unable to find a parcel with comparable sales; verify CMA data is loaded.")

    def _address_token(self, address: str, fallback: str) -> str:
        token = (address or "").strip().split(" ")[0]
        if len(token) >= 3:
            return token
        cleaned = fallback.strip()
        if len(cleaned) >= 3:
            return cleaned
        return "MAIN"

    # ------------------------------------------------------------------
    # Endpoint verifications
    # ------------------------------------------------------------------
    def _test_parcel_detail(self, context: EndpointContext) -> str:
        url = reverse("parcel-detail", kwargs={"parcel_number": context.parcel_number})
        payload = self._get_json(url)
        assessed = payload.get("valuation", {}).get("assessed")
        if assessed in (None, 0):
            raise AssertionError("Parcel detail missing assessed value.")
        address = payload.get("address") or context.parcel_address or "(unknown)"
        return f"address={address} assessed=${int(assessed):,}"

    def _test_sales_list(self) -> str:
        payload = self._get_json(reverse("sales-list"), {"limit": 5})
        results = payload.get("results", [])
        if not results:
            raise AssertionError("Sales endpoint returned zero records.")
        sale_price = results[0].get("sale", {}).get("sale_price")
        summary = f"records={len(results)}"
        if sale_price:
            summary += f" top_sale=${int(sale_price):,}"
        return summary

    def _test_parcel_search(self, context: EndpointContext) -> str:
        payload = self._get_json(reverse("parcel-search"), {"address": context.address_query, "page_size": 10})
        if not payload.get("results"):
            raise AssertionError("Parcel search returned zero rows.")
        return f"query='{context.address_query}' matches={len(payload['results'])}"

    def _test_parcel_summary(self, context: EndpointContext) -> str:
        params = {
            "group_by": "city_district",
            "metric": "avg_assessed_value",
            "district": context.city_district,
        }
        payload = self._get_json(reverse("parcel-summary"), params)
        results = payload.get("results", [])
        if not results:
            raise AssertionError("Parcel summary returned zero rows.")
        avg_value = results[0].get("average_assessed_value")
        city = results[0].get("group_value", context.city_district)
        summary = f"city={city}"
        if avg_value:
            summary += f" avg=${int(avg_value):,}"
        return summary

    def _test_semantic_search(self, context: EndpointContext) -> str:
        payload = self._post_json(reverse("semantic-search"), {"query": f"modern home in {context.city_district}", "limit": 3})
        results = payload.get("results", [])
        if not results:
            raise AssertionError("Semantic search returned zero matches.")
        return f"semantic_matches={len(results)}"

    def _test_nearby(self, context: EndpointContext) -> str:
        params = {"lat": context.latitude, "lon": context.longitude, "radius": 1000, "limit": 5}
        payload = self._get_json(reverse("parcel-nearby"), params)
        results = payload.get("results", [])
        if not results:
            raise AssertionError("Nearby endpoint returned zero parcels.")
        return f"nearby_count={len(results)} radius_m={payload.get('radius_meters', 0)}"

    def _test_neighborhood_stats(self, context: EndpointContext) -> str:
        stats = self._get_json(reverse("neighborhood-stats", kwargs={"neighborhood_code": context.neighborhood_code}))
        if stats.get("cod") in (None, 0):
            raise AssertionError("Neighborhood stats missing COD metric.")
        detail = self._get_json(reverse("neighborhood-detail", kwargs={"neighborhood_code": context.neighborhood_code}))
        if detail.get("code") != context.neighborhood_code:
            raise AssertionError("Neighborhood detail returned mismatched code.")
        return f"code={context.neighborhood_code} cod={stats.get('cod')}"

    def _test_appeal_analysis(self, context: EndpointContext) -> str:
        payload = self._get_json(reverse("appeal-analysis", kwargs={"parcel_number": context.parcel_number}))
        score = payload.get("appeal_likelihood")
        if score is None:
            raise AssertionError("Appeal analysis missing score.")
        return f"likelihood={score}% rating={payload.get('rating')}"

    def _test_appeal_search(self, context: EndpointContext) -> str:
        payload = self._get_json(reverse("appeal-search"), {"q": context.appeal_query})
        if not payload.get("result_count"):
            raise AssertionError("Appeal search returned zero matches.")
        return f"appeal_matches={payload['result_count']}"

    def _test_appeal_subject(self, context: EndpointContext) -> str:
        payload = self._get_json(reverse("appeal-subject", kwargs={"parcel_number": context.parcel_number}))
        assessment = payload.get("assessment", {})
        if not assessment.get("roll_year"):
            raise AssertionError("Appeal subject missing assessment roll year.")
        return f"assessment_year={assessment['roll_year']}"

    def _test_appeal_comparables(self, context: EndpointContext) -> str:
        payload = self._get_json(
            reverse("appeal-comparables", kwargs={"parcel_number": context.parcel_number}),
            {"count": appeals.INITIAL_COMPARABLE_LIMIT},
        )
        comparables = payload.get("comparables", [])
        if not comparables:
            raise AssertionError("Appeal comparables returned zero sales.")
        self.last_comparable = comparables[0]
        return f"comparables={len(comparables)} score={payload.get('score')}"

    def _test_comparable_improvements(self, context: EndpointContext) -> str:
        if not self.last_comparable:
            raise AssertionError("Comparable details unavailable. Run comparables test first.")
        metadata = self.last_comparable.get("metadata", {}) if isinstance(self.last_comparable, dict) else {}
        params = {}
        if metadata.get("roll_year"):
            params["roll_year"] = metadata["roll_year"]
        if metadata.get("roll_id"):
            params["roll_id"] = metadata["roll_id"]
        comp_parcel = self.last_comparable.get("parcel_number")
        payload = self._get_json(
            reverse(
                "appeal-comparable-improvements",
                kwargs={"parcel_number": context.parcel_number, "comp_parcel": comp_parcel},
            ),
            params,
        )
        improvements = payload.get("improvements", [])
        if not improvements:
            raise AssertionError("Comparable improvements endpoint returned zero records.")
        return f"improvements={len(improvements)}"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _get_json(self, url: str, params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        response = self.client.get(url, params or {}, HTTP_ACCEPT="application/json")
        if response.status_code != 200:
            raise AssertionError(f"{url} returned {response.status_code}: {response.content[:300]!r}")
        return json.loads(response.content.decode("utf-8") or "{}")

    def _post_json(self, url: str, payload: Dict[str, object]) -> Dict[str, object]:
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        if response.status_code != 200:
            raise AssertionError(f"POST {url} returned {response.status_code}: {response.content[:300]!r}")
        return json.loads(response.content.decode("utf-8") or "{}")
