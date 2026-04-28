from django.test import TestCase
from django.urls import reverse


class PageReferrerPolicyTests(TestCase):
    def test_sedro_woolley_map_uses_cross_origin_referrer_policy(self):
        response = self.client.get(reverse("sedro-woolley-zoning-map"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertContains(response, 'referrerPolicy: "strict-origin-when-cross-origin"')
