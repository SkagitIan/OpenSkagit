import os
from decimal import Decimal

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.test import RequestFactory, TestCase

from . import cma
from .views import (
    CMA_SESSION_KEY,
    _manual_adjustments_from_state,
    _merge_request_params,
    _store_manual_adjustment,
)


class CmaHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_with_session(self, method="get"):
        request = getattr(self.factory, method)("/")
        # lazily create session store
        request.session = self.client.session
        return request

    def test_store_and_parse_manual_adjustment(self):
        request = self._request_with_session("post")
        _store_manual_adjustment(request, "P123", "P999", "condition", Decimal("5000"))
        parcel_state = request.session.get(CMA_SESSION_KEY, {}).get("P123")
        self.assertIsNotNone(parcel_state)
        manual = _manual_adjustments_from_state(parcel_state)
        self.assertIn("P999", manual)
        self.assertEqual(manual["P999"]["condition"], Decimal("5000"))

    def test_manual_adjustment_removal(self):
        request = self._request_with_session("post")
        _store_manual_adjustment(request, "P123", "P999", "view", Decimal("2500"))
        _store_manual_adjustment(request, "P123", "P999", "view", None)
        parcel_state = request.session.get(CMA_SESSION_KEY, {}).get("P123")
        manual = _manual_adjustments_from_state(parcel_state)
        self.assertNotIn("P999", manual)

    def test_merge_params_prioritizes_post(self):
        request = self.factory.post("/?limit=10", {"limit": "12", "sort_field": "gpa"})
        merged = _merge_request_params(request)
        self.assertEqual(merged["limit"], "12")
        self.assertEqual(merged["sort_field"], "gpa")


class CmaFilterTests(TestCase):
    def test_parse_filters_from_dict(self):
        payload = {
            "sale_date_min": "2023-01-01",
            "sale_date_max": "2023-12-31",
            "property_type": "Single Family",
            "min_price": "400000",
            "max_price": "750000",
            "bedrooms": "3",
            "bathrooms": "2",
            "bbox": "-123.1,48.1,-122.9,48.3",
        }
        filters = cma.filters_from_dict(payload)
        self.assertEqual(filters.property_type, "Single Family")
        self.assertEqual(filters.min_price, Decimal("400000"))
        self.assertEqual(filters.max_price, Decimal("750000"))
        self.assertEqual(filters.bedrooms, 3)
        self.assertEqual(filters.bathrooms, 2)
        self.assertIsNotNone(filters.sale_date_min)
        self.assertIsNotNone(filters.bbox)
