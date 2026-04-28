from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from gis.constants import (
    QUALIFICATION_STATUS_APPROVED,
    QUALIFICATION_STATUS_DRAFT,
    SOURCE_TYPE_ARCGIS_FEATURE_LAYER,
)
from gis.models import GISDiscoveredLayer, GISLayerManifest, GISSourceSubmission
from gis.services.detect import detect_source_type
from gis.services.manifest import (
    bulk_approve_submission_layers,
    evaluate_layer_for_auto_approval,
    promote_layer_to_manifest,
)
from gis.services.normalize import normalize_url
from gis.services.qualify import qualify_layer


class GISNormalizeDetectTests(TestCase):
    def test_normalize_url_adds_https_and_strips_noise(self):
        normalized = normalize_url("example.com/arcgis/rest/services/Test/FeatureServer/0/?foo=1#frag")
        self.assertEqual(normalized, "https://example.com/arcgis/rest/services/Test/FeatureServer/0")

    def test_detect_source_type_feature_layer(self):
        result = detect_source_type("https://maps.example.com/arcgis/rest/services/Planning/Zoning/FeatureServer/2")
        self.assertEqual(result.source_type, SOURCE_TYPE_ARCGIS_FEATURE_LAYER)
        self.assertEqual(result.layer_id, 2)
        self.assertTrue(result.service_root_url.endswith("/FeatureServer"))


class GISTigerwebScopeQueryTests(TestCase):
    @patch("gis.services.qualify._fetch_json")
    def test_qualify_layer_applies_skagit_attribute_filter_when_fields_exist(self, mock_fetch_json):
        layer_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0"
        query_url = f"{layer_url}/query"

        def fake_fetch(url, params):
            where = str(params.get("where") or "")
            if url == layer_url and params.get("f") == "json":
                return (
                    {
                        "id": 0,
                        "name": "Census Tracts",
                        "fields": [
                            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                            {"name": "GEOID", "type": "esriFieldTypeString"},
                            {"name": "NAME", "type": "esriFieldTypeString"},
                            {"name": "STATE", "type": "esriFieldTypeString"},
                            {"name": "COUNTY", "type": "esriFieldTypeString"},
                        ],
                        "geometryType": "esriGeometryPolygon",
                    },
                    "",
                )

            if url == query_url and params.get("returnCountOnly") == "true":
                if "STATE='53'" in where and "COUNTY='057'" in where:
                    return ({"count": 12}, "")
                return ({"count": 1}, "")

            if url == query_url and params.get("f") == "geojson":
                if "STATE='53'" in where and "COUNTY='057'" in where:
                    return (
                        {
                            "type": "FeatureCollection",
                            "features": [{"type": "Feature", "geometry": None, "properties": {"GEOID": "53057960100"}}],
                        },
                        "",
                    )
                return (
                    {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {"id": 1}}]},
                    "",
                )

            if url == query_url:
                return ({"features": [{"attributes": {"OBJECTID": 1}}]}, "")

            return ({}, "")

        mock_fetch_json.side_effect = fake_fetch

        result = qualify_layer(
            {
                "layer_url": layer_url,
                "service_root_url": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer",
                "service_type": "MapServer",
                "layer_id": 0,
                "layer_name": "Census Tracts",
                "source_org": "U.S. Census Bureau",
            }
        )

        payload = result["qualification_payload"]
        scope_tests = payload.get("scope_tests") or {}
        self.assertTrue(scope_tests.get("applicable"))
        self.assertEqual(scope_tests.get("mode"), "attribute")
        self.assertIn("STATE='53'", scope_tests.get("where_clause", ""))
        self.assertIn("COUNTY='057'", scope_tests.get("where_clause", ""))
        self.assertTrue(scope_tests.get("filter_ok"))
        self.assertEqual(scope_tests.get("record_count"), 12)
        self.assertEqual(payload.get("relevance", {}).get("skagit_relevance"), "direct")


class GISManifestPromotionTests(TestCase):
    def test_promote_layer_to_manifest_sets_approved(self):
        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        layer = GISDiscoveredLayer.objects.create(
            source_submission=submission,
            discovered_from_url=submission.submitted_url,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            source_org="City of Example",
            service_type="FeatureServer",
            layer_id=0,
            layer_name="Zoning",
            category="zoning",
            geometry_type="esriGeometryPolygon",
            id_field="OBJECTID",
            auth_type="none",
            coverage="countywide",
            skagit_relevance="direct",
            usability="high",
            fields_json=[{"name": "OBJECTID"}, {"name": "ZONE"}],
            qualification_results_json={
                "metadata": {"max_record_count": 2000},
                "query_tests": {
                    "query_supported": True,
                    "return_geometry_ok": True,
                    "where_1_eq_1_ok": True,
                    "supports_pagination": True,
                    "ids_only_ok": True,
                    "count_only_ok": True,
                },
            },
        )

        manifest = promote_layer_to_manifest(
            discovered_layer=layer,
            key="example_zoning",
            label="Example Zoning",
            category="zoning",
            default_fields="OBJECTID,ZONE",
            canonical_for_category=True,
            notes="Approved in test",
        )

        layer.refresh_from_db()
        self.assertEqual(layer.qualification_status, QUALIFICATION_STATUS_APPROVED)
        self.assertEqual(manifest.key, "example_zoning")
        self.assertTrue(manifest.queryable)
        self.assertTrue(manifest.supports_geometry)
        self.assertEqual(manifest.default_fields_json, ["OBJECTID", "ZONE"])


class GISStaffViewAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="gis-staff",
            email="staff-gis@example.com",
            password="secret",
            is_staff=True,
        )
        self.non_staff_user = user_model.objects.create_user(
            username="gis-nonstaff",
            email="nonstaff-gis@example.com",
            password="secret",
            is_staff=False,
        )

    def test_submission_list_requires_staff(self):
        anonymous = self.client.get("/staff/gis/")
        self.assertEqual(anonymous.status_code, 302)

        self.client.force_login(self.non_staff_user)
        non_staff = self.client.get("/staff/gis/")
        self.assertEqual(non_staff.status_code, 302)

        self.client.force_login(self.staff_user)
        staff = self.client.get("/staff/gis/")
        self.assertEqual(staff.status_code, 200)
        self.assertContains(staff, "GIS Source Submissions")

    def test_staff_can_run_bulk_approve_endpoint(self):
        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        GISDiscoveredLayer.objects.create(
            source_submission=submission,
            discovered_from_url=submission.submitted_url,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            source_org="Skagit County",
            service_type="FeatureServer",
            layer_id=0,
            layer_name="Road Centerlines",
            category="roads",
            geometry_type="esriGeometryPolyline",
            id_field="OBJECTID",
            coverage="countywide",
            skagit_relevance="direct",
            usability="high",
            qualification_results_json={
                "identity": {"is_layer_endpoint": True},
                "metadata": {"metadata_fetch_ok": True},
                "query_tests": {
                    "query_supported": True,
                    "minimal_query_ok": True,
                    "where_1_eq_1_ok": True,
                    "return_geometry_ok": True,
                    "supports_pagination": True,
                    "ids_only_ok": True,
                    "count_only_ok": True,
                },
            },
        )

        self.client.force_login(self.staff_user)
        response = self.client.post(f"/staff/gis/submissions/{submission.id}/add-all/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GISLayerManifest.objects.filter(source_submission=submission).exists())

    def test_staff_can_add_single_layer_from_submission(self):
        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        layer = GISDiscoveredLayer.objects.create(
            source_submission=submission,
            discovered_from_url=submission.submitted_url,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/8",
            source_org="Skagit County",
            service_type="FeatureServer",
            layer_id=8,
            layer_name="Addresses",
            category="addresses",
            geometry_type="esriGeometryPoint",
            id_field="OBJECTID",
            coverage="countywide",
            skagit_relevance="direct",
            usability="high",
            qualification_results_json={
                "identity": {"is_layer_endpoint": True},
                "metadata": {"metadata_fetch_ok": True},
                "query_tests": {
                    "query_supported": True,
                    "minimal_query_ok": True,
                    "where_1_eq_1_ok": True,
                    "return_geometry_ok": True,
                    "supports_pagination": True,
                    "ids_only_ok": True,
                    "count_only_ok": True,
                },
            },
        )

        self.client.force_login(self.staff_user)
        response = self.client.post(f"/staff/gis/submissions/{submission.id}/layers/{layer.id}/add/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GISLayerManifest.objects.filter(layer_url=layer.layer_url).exists())


class GISBulkApprovalTests(TestCase):
    def setUp(self):
        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        self.submission = submission

        self.passing_layer = GISDiscoveredLayer.objects.create(
            source_submission=submission,
            discovered_from_url=submission.submitted_url,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            source_org="Skagit County",
            service_type="FeatureServer",
            layer_id=0,
            layer_name="Parcels",
            category="parcels",
            geometry_type="esriGeometryPolygon",
            id_field="OBJECTID",
            coverage="countywide",
            skagit_relevance="direct",
            usability="high",
            qualification_status=QUALIFICATION_STATUS_DRAFT,
            fields_json=[
                {"name": "OBJECTID"},
                {"name": "PARCEL_ID"},
                {"name": "OWNER_NAME"},
                {"name": "SITE_ADDRESS"},
            ],
            qualification_results_json={
                "identity": {"is_layer_endpoint": True},
                "metadata": {"metadata_fetch_ok": True, "max_record_count": 2000},
                "query_tests": {
                    "query_supported": True,
                    "minimal_query_ok": True,
                    "where_1_eq_1_ok": True,
                    "return_geometry_ok": True,
                    "supports_pagination": True,
                    "ids_only_ok": True,
                    "count_only_ok": True,
                },
            },
        )

        self.failing_layer = GISDiscoveredLayer.objects.create(
            source_submission=submission,
            discovered_from_url=submission.submitted_url,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/1",
            source_org="Skagit County",
            service_type="FeatureServer",
            layer_id=1,
            layer_name="Unstable Layer",
            category="other",
            geometry_type="",
            id_field="",
            coverage="unknown",
            skagit_relevance="contextual",
            usability="low",
            qualification_status=QUALIFICATION_STATUS_DRAFT,
            qualification_results_json={
                "identity": {"is_layer_endpoint": True},
                "metadata": {"metadata_fetch_ok": False},
                "query_tests": {"query_supported": False},
            },
        )

    def test_evaluate_layer_for_auto_approval(self):
        passing_ok, passing_reasons = evaluate_layer_for_auto_approval(self.passing_layer)
        failing_ok, failing_reasons = evaluate_layer_for_auto_approval(self.failing_layer)

        self.assertTrue(passing_ok)
        self.assertEqual(passing_reasons, [])
        self.assertFalse(failing_ok)
        self.assertIn("metadata_fetch_failed", failing_reasons)

    def test_bulk_approve_submission_layers(self):
        result = bulk_approve_submission_layers(self.submission)

        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(result["skipped_count"], 1)

        self.passing_layer.refresh_from_db()
        self.assertEqual(self.passing_layer.qualification_status, QUALIFICATION_STATUS_APPROVED)

        manifest = GISLayerManifest.objects.get(layer_url=self.passing_layer.layer_url)
        self.assertEqual(manifest.category, "parcels")
        self.assertTrue(manifest.default_fields_json)


class GISManifestSampleTests(TestCase):
    @patch("gis.services.manifest.requests.get")
    def test_manifest_detail_fetches_sample(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "features": [
                {"attributes": {"OBJECTID": 1, "NAME": "Sample A"}},
                {"attributes": {"OBJECTID": 2, "NAME": "Sample B"}},
            ]
        }
        mock_get.return_value = mock_response

        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        manifest = GISLayerManifest.objects.create(
            key="sample_layer",
            label="Sample Layer",
            source_submission=submission,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            category="other",
            default_fields_json=["OBJECTID", "NAME"],
            queryable=True,
        )

        user_model = get_user_model()
        staff_user = user_model.objects.create_user(
            username="manifest-sample-staff",
            email="manifest-sample@example.com",
            password="secret",
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.post(f"/staff/gis/manifest/{manifest.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Result JSON")
        self.assertContains(response, "Sample A")


class GISManifestListActionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="manifest-action-staff",
            email="manifest-action@example.com",
            password="secret",
            is_staff=True,
        )
        submission = GISSourceSubmission.objects.create(submitted_url="https://example.com/arcgis/rest/services/Test/FeatureServer")
        self.manifest = GISLayerManifest.objects.create(
            key="manifest_action_layer",
            label="Manifest Action Layer",
            source_submission=submission,
            service_root_url="https://example.com/arcgis/rest/services/Test/FeatureServer",
            layer_url="https://example.com/arcgis/rest/services/Test/FeatureServer/3",
            category="other",
            queryable=True,
        )

    @patch("gis.views.fetch_manifest_sample_data")
    def test_manifest_test_action(self, mock_fetch):
        mock_fetch.return_value = {"ok": True, "record_count": 2, "records": [{"id": 1}, {"id": 2}]}
        self.client.force_login(self.staff_user)
        response = self.client.post(f"/staff/gis/manifest/{self.manifest.id}/test/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GISLayerManifest.objects.filter(id=self.manifest.id).exists())

    def test_manifest_delete_action(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(f"/staff/gis/manifest/{self.manifest.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GISLayerManifest.objects.filter(id=self.manifest.id).exists())
