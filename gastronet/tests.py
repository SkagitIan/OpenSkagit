import json

from django.test import TestCase
from django.urls import reverse

from .models import MenuItem, Restaurant


class MenuIngestAPITest(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            place_id="test:manual:1",
            name="Test Restaurant",
        )
        self.url = reverse("gastronet:menu-items")

    def _payload(self):
        return {
            "restaurant": self.restaurant.pk,
            "menu_data": [
                {
                    "name": "Street Tacos",
                    "description": "Corn tortilla, lime, cilantro",
                    "price": 12.5,
                    "section": "Tacos",
                    "dietary_tags": ["gluten-free"],
                }
            ],
        }

    def test_creates_menu_items(self):
        response = self.client.post(
            self.url,
            json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["created"], 1)
        self.assertEqual(data["updated"], 0)
        menu_item = MenuItem.objects.get(restaurant=self.restaurant)
        self.assertEqual(menu_item.name, "Street Tacos")
        self.assertEqual(menu_item.section, "Tacos")
        self.assertEqual(str(menu_item.price), "12.50")
        self.assertEqual(menu_item.dietary_tags, ["gluten-free"])

    def test_updates_existing_menu_item(self):
        first_payload = self._payload()
        self.client.post(
            self.url,
            json.dumps(first_payload),
            content_type="application/json",
        )

        updated_payload = self._payload()
        updated_payload["menu_data"][0]["price"] = 14.75

        response = self.client.post(
            self.url,
            json.dumps(updated_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["updated"], 1)
        menu_item = MenuItem.objects.get(restaurant=self.restaurant)
        self.assertEqual(str(menu_item.price), "14.75")
