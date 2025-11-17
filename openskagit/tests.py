import os
from decimal import Decimal

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.test import RequestFactory, TestCase

from . import cma
from .views import _merge_request_params


class CmaHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_merge_params_prioritizes_post(self):
        request = self.factory.post("/?limit=10", {"limit": "12", "sort_field": "distance"})
        merged = _merge_request_params(request)
        self.assertEqual(merged["limit"], "12")
        self.assertEqual(merged["sort_field"], "distance")


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
