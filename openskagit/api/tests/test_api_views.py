from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from openskagit import cma
from openskagit.api import views


class FakeCursor:
    """
    Minimal context manager that mimics a DB cursor for the raw SQL helpers.
    """

    def __init__(
        self,
        *,
        description: Optional[Iterable[str]] = None,
        row: Optional[Sequence] = None,
        rows: Optional[List[Sequence]] = None,
    ) -> None:
        self.description = [(col,) if not isinstance(col, tuple) else col for col in (description or [])]
        self._row = row
        self._rows = list(rows or [])
        self._row_consumed = False
        self.executed_sql: List[Tuple[str, Tuple]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Optional[Sequence] = None) -> None:
        self.executed_sql.append((sql, tuple(params or ())))

    def fetchone(self) -> Optional[Sequence]:
        if self._row_consumed:
            return None
        self._row_consumed = True
        if self._row is not None:
            return self._row
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Sequence]:
        return list(self._rows)


class BaseAPITestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        views._load_embedding_model.cache_clear()


class ParcelDetailViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    def test_parcel_detail_returns_expected_payload(self, mock_cursor):
        land_segments = [
            {"size_acres": 1.2, "market_value": 95000, "land_type": "Primary"},
            {"size_acres": 0.3, "market_value": 15000, "land_type": "Secondary"},
        ]
        improvements = [{"type": "Structure", "description": "Barn"}]
        sales = [
            {"sale_price": 250000, "sale_date": date(2023, 5, 1)},
            {"sale_price": 200000, "sale_date": date(2020, 3, 15)},
        ]
        detail_row = (
            "P123456",
            "123 Main St",
            Decimal("180000"),
            Decimal("220000"),
            Decimal("175000"),
            3,
            2.5,
            1900,
            1995,
            2000,
            Decimal("1.5"),
            "City District",
            "School District",
            "Fire District",
            Decimal("48.512345"),
            Decimal("-122.345678"),
            land_segments,
            improvements,
            sales,
        )
        mock_cursor.return_value = FakeCursor(
            description=[
                "parcel_number",
                "address",
                "assessed_value",
                "total_market_value",
                "taxable_value",
                "bedrooms",
                "bathrooms",
                "living_area",
                "year_built",
                "eff_year_built",
                "acres",
                "city_district",
                "school_district",
                "fire_district",
                "latitude",
                "longitude",
                "land_segments",
                "improvements",
                "sales",
            ],
            row=detail_row,
        )

        url = reverse("parcel-detail", kwargs={"parcel_number": "P123456"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parcel_number"], "P123456")
        self.assertAlmostEqual(payload["valuation"]["assessed"], 180000.0)
        self.assertEqual(payload["land"]["total_acres"], 1.5)
        self.assertEqual(payload["land"]["segments"][0]["land_type"], "Primary")
        self.assertEqual(payload["sales"]["total_records"], 2)
        self.assertEqual(payload["sales"]["latest"]["sale_price"], 250000)
        self.assertEqual(len(payload["sales"]["recent_valid"]), 2)

    @patch("openskagit.api.views.connection.cursor")
    def test_parcel_detail_missing_parcel_returns_404(self, mock_cursor):
        mock_cursor.return_value = FakeCursor(description=["parcel_number"], row=None)

        url = reverse("parcel-detail", kwargs={"parcel_number": "UNKNOWN"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


class ParcelSearchViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    def test_search_supports_all_filters(self, mock_cursor):
        count_cursor = FakeCursor(description=["count"], row=(25,))
        records_cursor = FakeCursor(
            description=[
                "parcel_number",
                "address",
                "assessed_value",
                "total_market_value",
                "acres",
                "city_district",
                "year_built",
                "last_sale_price",
                "last_sale_date",
            ],
            rows=[
                (
                    "P100",
                    "100 Test Ave",
                    Decimal("350000"),
                    Decimal("420000"),
                    Decimal("1.75"),
                    "Central",
                    1985,
                    Decimal("275000"),
                    date(2022, 7, 4),
                )
            ],
        )
        mock_cursor.side_effect = [count_cursor, records_cursor]

        params = {
            "page": 2,
            "page_size": 10,
            "address": "Test",
            "parcel_number": "P100",
            "min_value": "200000",
            "max_value": "500000",
            "district": "Central",
            "min_year": "1970",
            "max_year": "2023",
            "min_acres": "0.5",
            "max_acres": "5.0",
            "min_sale_price": "150000",
            "max_sale_price": "450000",
        }

        response = self.client.get(reverse("parcel-search"), params)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 25)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 10)
        self.assertEqual(len(payload["results"]), 1)
        record = payload["results"][0]
        self.assertEqual(record["parcel_number"], "P100")
        self.assertAlmostEqual(record["assessed_value"], 350000.0)
        self.assertEqual(record["last_sale_price"], 275000.0)
        self.assertEqual(record["last_sale_date"], "2022-07-04")


class SalesListViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    def test_sales_list_returns_expected_payload(self, mock_cursor):
        count_cursor = FakeCursor(description=["count"], row=(2,))
        sales_row = (
            101,
            "P0001",
            "ACCT-0001",
            "Seller Name",
            "Buyer Name",
            Decimal("450000"),
            date(2023, 9, 15),
            "valid sale",
            "REC123",
            "Warranty",
            date(2023, 9, 10),
            Decimal("12.0"),
            Decimal("456789.0"),
            "123 Main St",
            "NE12",
            "11",
            "Single Family",
            "Mount Vernon",
            "SD201",
            "F01",
            Decimal("400000"),
            Decimal("420000"),
            Decimal("398000"),
            Decimal("0.5"),
            2005,
            2010,
            3,
            Decimal("2.5"),
            1800,
            [{"size_acres": 0.5, "market_value": 220000}],
            [{"improvement_id": 1, "improvement_value": 200000}],
        )
        data_cursor = FakeCursor(
            description=[
                "sale_id",
                "parcel_number",
                "account_number",
                "seller_name",
                "buyer_name",
                "sale_price",
                "sale_date",
                "sale_type",
                "recording_number",
                "deed_type",
                "deed_date",
                "revaluation_area",
                "excise_number",
                "address",
                "neighborhood_code",
                "land_use_code",
                "property_type",
                "city_district",
                "school_district",
                "fire_district",
                "assessed_value",
                "total_market_value",
                "taxable_value",
                "acres",
                "year_built",
                "eff_year_built",
                "bedrooms",
                "bathrooms",
                "living_area",
                "land_segments",
                "improvements",
            ],
            rows=[sales_row],
        )
        mock_cursor.side_effect = [count_cursor, data_cursor]

        response = self.client.get(reverse("sales-list"), {"limit": 5, "sort": "sale_price"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["limit"], 5)
        self.assertEqual(payload["sort"]["field"], "sale_price")
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["parcel_number"], "P0001")
        self.assertEqual(result["sale"]["sale_type"], "valid sale")
        self.assertEqual(result["sale"]["sale_price"], 450000.0)
        self.assertEqual(result["parcel"]["neighborhood_code"], "NE12")
        self.assertEqual(result["land"]["total_acres"], 0.5)
        self.assertEqual(result["land"]["segments"][0]["market_value"], 220000)
        self.assertEqual(result["improvements"][0]["improvement_value"], 200000)
        executed_sql = " ".join(count_cursor.executed_sql[0][0].lower().split())
        self.assertIn("lower(trim(s.sale_type)) = 'valid sale'", executed_sql)

    @patch("openskagit.api.views.connection.cursor")
    def test_sales_list_rejects_unknown_sort(self, mock_cursor):
        response = self.client.get(reverse("sales-list"), {"sort": "unknown"})

        self.assertEqual(response.status_code, 400)
        mock_cursor.assert_not_called()


class ParcelSummaryViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    def test_summary_with_all_filters(self, mock_cursor):
        mock_cursor.return_value = FakeCursor(
            description=["group_value", "metric_value", "parcel_count"],
            rows=[
                ("Central", Decimal("400000"), 12),
                ("North", Decimal("350000"), 8),
            ],
        )

        params = {
            "group_by": "city_district",
            "metric": "avg_assessed_value",
            "limit": "25",
            "min_value": "200000",
            "max_value": "600000",
            "district": "Central",
            "min_year": "1980",
            "max_year": "2023",
            "min_acres": "0.25",
            "max_acres": "4.0",
            "min_sale_price": "150000",
            "max_sale_price": "550000",
        }

        response = self.client.get(reverse("parcel-summary"), params)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["group_by"], "city_district")
        self.assertEqual(payload["metric"], "avg_assessed_value")
        self.assertEqual(len(payload["results"]), 2)
        self.assertAlmostEqual(payload["results"][0]["average_assessed_value"], 400000.0)
        self.assertEqual(payload["results"][0]["parcel_count"], 12)

    def test_summary_with_invalid_group_by_returns_400(self):
        response = self.client.get(
            reverse("parcel-summary"),
            {"group_by": "invalid", "metric": "parcel_count"},
        )
        self.assertEqual(response.status_code, 400)


class SemanticSearchViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    @patch("openskagit.api.views._load_embedding_model")
    def test_semantic_search_returns_similarity_scores(self, mock_load_model, mock_cursor):
        mock_model = MagicMock()
        vector = MagicMock()
        vector.tolist.return_value = [0.1, 0.2, 0.3]
        mock_model.encode.return_value = [vector]
        mock_load_model.return_value = mock_model

        mock_cursor.return_value = FakeCursor(
            description=[
                "parcel_number",
                "address",
                "assessed_value",
                "total_market_value",
                "acres",
                "city_district",
                "last_sale_price",
                "last_sale_date",
                "distance",
            ],
            rows=[
                (
                    "P200",
                    "200 Lakeside Dr",
                    Decimal("500000"),
                    Decimal("650000"),
                    Decimal("2.1"),
                    "Lakeside",
                    Decimal("450000"),
                    date(2021, 10, 20),
                    Decimal("0.25"),
                )
            ],
        )

        payload = {"query": "Waterfront home", "limit": 5}
        response = self.client.post(
            reverse("semantic-search"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_payload = response.json()
        self.assertEqual(response_payload["query"], "Waterfront home")
        self.assertEqual(len(response_payload["results"]), 1)
        result = response_payload["results"][0]
        self.assertEqual(result["parcel_number"], "P200")
        self.assertAlmostEqual(result["similarity"], 1 / (1 + 0.25))
        mock_model.encode.assert_called_once_with(["Waterfront home"], normalize_embeddings=True)

    def test_semantic_search_requires_query(self):
        response = self.client.post(
            reverse("semantic-search"),
            data=json.dumps({"limit": 3}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class NearbyParcelsViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.connection.cursor")
    def test_nearby_parcels_with_all_filters(self, mock_cursor):
        mock_cursor.return_value = FakeCursor(
            description=[
                "parcel_number",
                "address",
                "assessed_value",
                "total_market_value",
                "acres",
                "city_district",
                "distance_meters",
            ],
            rows=[
                (
                    "P300",
                    "300 Valley Rd",
                    Decimal("275000"),
                    Decimal("320000"),
                    Decimal("1.1"),
                    "Valley",
                    Decimal("350.5"),
                )
            ],
        )

        params = {
            "lat": "48.1234",
            "lon": "-122.9876",
            "radius": "750",
            "limit": "10",
            "min_value": "200000",
            "max_value": "400000",
            "min_acres": "0.5",
            "max_acres": "2.0",
        }
        response = self.client.get(reverse("parcel-nearby"), params)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertAlmostEqual(payload["center"]["lat"], 48.1234)
        self.assertAlmostEqual(payload["center"]["lon"], -122.9876)
        self.assertEqual(payload["radius_meters"], 750.0)
        self.assertEqual(len(payload["results"]), 1)
        self.assertAlmostEqual(payload["results"][0]["distance_meters"], 350.5)

    def test_nearby_requires_coordinates(self):
        response = self.client.get(reverse("parcel-nearby"), {"lon": "-122.0"})
        self.assertEqual(response.status_code, 400)


class AppealParcelSearchViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.appeals.current_assessment_year", return_value=2024)
    @patch("openskagit.api.views.AppealParcelSearchView._base_queryset")
    def test_address_search_returns_results(self, mock_queryset, _mock_year):
        class DummyQuery(list):
            def filter(self, *args, **kwargs):  # pragma: no cover - trivial passthrough
                return self

            def exclude(self, *args, **kwargs):  # pragma: no cover - trivial passthrough
                return self

            def order_by(self, *args, **kwargs):  # pragma: no cover - trivial passthrough
                return self

        record = SimpleNamespace(
            parcel_number="P12345",
            address="123 Main St",
            city_district="Central",
            assessed_value=350000,
            sale_price=325000,
            sale_date=date(2023, 5, 1),
            bedrooms=3,
            bathrooms=2,
            living_area=1800,
            acres=0.25,
            roll=SimpleNamespace(year=2024),
        )
        mock_queryset.return_value = DummyQuery([record])

        response = self.client.get(reverse("appeal-search"), {"q": "123 Main"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["query_too_short"])
        self.assertEqual(payload["result_count"], 1)
        record_payload = payload["results"][0]
        self.assertEqual(record_payload["parcel_number"], "P12345")
        self.assertEqual(record_payload["assessment_year"], 2024)
        self.assertEqual(record_payload["city_district"], "Central")

    @patch("openskagit.api.views.AppealParcelSearchView._base_queryset")
    def test_short_query_is_rejected(self, mock_queryset):
        response = self.client.get(reverse("appeal-search"), {"q": "ab"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["query_too_short"])
        self.assertEqual(payload["result_count"], 0)
        mock_queryset.assert_not_called()


class AppealSubjectViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.appeals.get_subject_neighborhood_snapshot")
    @patch("openskagit.api.views.appeals.load_subject_with_roll_context")
    def test_returns_subject_snapshot(self, mock_load_subject, mock_neighborhood):
        snapshot = cma.PropertySnapshot(
            parcel_number="P100",
            address="100 River Rd",
            sale_price=None,
            sale_date=None,
            property_type="R",
            living_area=Decimal("1800"),
            bedrooms=Decimal("3"),
            bathrooms=Decimal("2"),
            year_built=1990,
            effective_year_built=1995,
            garage_sqft=None,
            acres=Decimal("0.30"),
            assessed_value=Decimal("425000"),
            geom=None,
            metadata={
                "assessment_roll_year": 2024,
                "assessed_value": 425000,
                "assessor": {
                    "prior_assessment_year": 2023,
                    "prior_assessed_value": 390000,
                },
                "assessed_change_pct": 9.0,
            },
        )
        mock_load_subject.return_value = (snapshot, 2024)
        mock_neighborhood.return_value = {"code": "20ASKY", "cod": 12.5}

        response = self.client.get(reverse("appeal-subject", kwargs={"parcel_number": "P100"}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject"]["parcel_number"], "P100")
        self.assertEqual(payload["assessment"]["roll_year"], 2024)
        self.assertEqual(payload["assessment"]["prior_roll_year"], 2023)
        self.assertIn("neighborhood", payload)
        mock_load_subject.assert_called_once_with("P100")


class AppealComparablesViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.appeals.citizen_assessment_summary")
    @patch("openskagit.api.views.appeals._comparable_candidates")
    @patch("openskagit.api.views.appeals.load_subject_with_roll_context")
    def test_returns_comparables_payload(self, mock_load_subject, mock_candidates, mock_summary):
        subject = cma.PropertySnapshot(
            parcel_number="P200",
            address="200 Mountain Dr",
            sale_price=None,
            sale_date=None,
            property_type="R",
            living_area=Decimal("2200"),
            bedrooms=Decimal("4"),
            bathrooms=Decimal("3"),
            year_built=2005,
            effective_year_built=2006,
            garage_sqft=None,
            acres=Decimal("0.45"),
            assessed_value=Decimal("550000"),
            geom=None,
            metadata={"assessed_change_pct": 8.0},
        )
        mock_load_subject.return_value = (subject, 2024)

        comp_snapshot = cma.PropertySnapshot(
            parcel_number="P300",
            address="300 Mountain Dr",
            sale_price=None,
            sale_date=None,
            property_type="R",
            living_area=Decimal("2100"),
            bedrooms=Decimal("3"),
            bathrooms=Decimal("2.5"),
            year_built=2004,
            effective_year_built=2004,
            garage_sqft=None,
            acres=Decimal("0.40"),
            assessed_value=Decimal("520000"),
            geom=None,
            metadata={"roll_year": 2024, "roll_id": 1},
        )
        comparable = cma.ComparableResult(
            snapshot=comp_snapshot,
            sale_price=Decimal("600000"),
            assessed_value=Decimal("520000"),
            sale_date=date(2023, 7, 1),
            distance_meters=500,
            distance_miles=Decimal("0.3"),
            difference_flags={},
            inclusion_rank=1,
        )
        mock_candidates.return_value = ([comparable], 3218)
        mock_summary.return_value = {
            "comparables": [comparable],
            "over_assessment_pct": 12.0,
            "comp_count": 1,
            "neighborhood": {"avg_increase_pct": 5.0},
            "score": 70,
            "rating": "Strong",
            "reasons": ["Assessed value ~7–12% above comps."],
            "neigh_diff_pct": None,
        }

        response = self.client.get(reverse("appeal-comparables", kwargs={"parcel_number": "P200"}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score"], 70)
        self.assertEqual(len(payload["comparables"]), 1)
        self.assertTrue(payload["soft_stop"])
        self.assertIn("comparables", payload)
        mock_candidates.assert_called_once()


class AppealComparableImprovementsViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.cma.get_improvement_rollup")
    def test_returns_improvement_rollup(self, mock_rollup):
        mock_rollup.return_value = [
            {"description": "Residence", "improvement_value": 400000},
        ]

        url = reverse(
            "appeal-comparable-improvements",
            kwargs={"parcel_number": "P200", "comp_parcel": "P300"},
        )
        response = self.client.get(url, {"roll_year": "2024", "roll_id": "5"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parcel_number"], "P300")
        self.assertEqual(payload["improvements"][0]["description"], "Residence")
        mock_rollup.assert_called_once()


class NeighborhoodStatsViewTests(BaseAPITestCase):
    @patch("openskagit.api.views.get_neighborhood_snapshot")
    def test_returns_snapshot_payload(self, mock_snapshot):
        mock_snapshot.return_value = {"code": "20ASKY", "cod": 12.3}

        response = self.client.get(reverse("neighborhood-stats", kwargs={"neighborhood_code": "20ASKY"}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], "20ASKY")
        self.assertAlmostEqual(payload["cod"], 12.3)
        mock_snapshot.assert_called_once()
