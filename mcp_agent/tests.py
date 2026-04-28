import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import get_resolver

from mcp_agent.management.commands.generate_mcp_schema import _collect_mcp_routes
from mcp_agent import views as mcp_views
from mcp_agent.legal.adapters import db_legal
from mcp_agent.sql_guard import GuardConfig, validate_and_rewrite


class SqlGuardTests(SimpleTestCase):
    def setUp(self) -> None:
        self.cfg = GuardConfig(allow_schemas={"public"}, max_limit=50)

    def test_rejects_non_select(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("UPDATE public.sales SET city = 'X'", self.cfg)

    def test_forbids_select_star(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("SELECT * FROM public.sales LIMIT 5", self.cfg)

    def test_clamps_limit(self):
        sql = validate_and_rewrite("SELECT id FROM public.sales LIMIT 9999", self.cfg)
        self.assertIn("LIMIT 50", sql.upper())

    def test_schema_allowlist(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("SELECT id FROM secret.table_one", self.cfg)


class LegalApiTests(SimpleTestCase):
    def test_legal_jurisdictions_shape(self):
        response = self.client.get("/agent/legal/jurisdictions/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("jurisdictions", payload)
        self.assertEqual(len(payload["jurisdictions"]), 7)
        first = payload["jurisdictions"][0]
        self.assertEqual(
            sorted(first.keys()),
            ["aliases", "name", "publisher", "slug"],
        )

    def test_legal_search_missing_q(self):
        response = self.client.get("/agent/legal/search/?jurisdiction=sedro_woolley")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "missing_q"})

    @patch("mcp_agent.legal.views.db_legal.search")
    def test_legal_search_washington_state_success(self, mock_search):
        mock_search.return_value = [
            {
                "id": "wa:washington_state:abc",
                "cite": "RCW 22.09.045",
                "heading": "RCW 22.09.045",
                "snippet": "Application for grain dealer license.",
                "url": "https://app.leg.wa.gov/RCW/default.aspx?cite=22.09.045",
            }
        ]
        response = self.client.get("/agent/legal/search/?jurisdiction=washington_state&q=grain")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "washington_state")
        self.assertEqual(len(payload["hits"]), 1)
        mock_search.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.search")
    def test_legal_search_success(self, mock_search):
        mock_search.return_value = [
            {
                "id": "cp:sedro_woolley:abc",
                "cite": "Chapter 8.28",
                "heading": "Chapter 8.28 ACCESSORY DWELLING UNITS",
                "snippet": "Accessory dwelling units...",
                "url": "https://www.codepublishing.com/WA/SedroWoolley/html/SedroWoolley08/SedroWoolley0828.html",
            }
        ]

        response = self.client.get("/agent/legal/search/?jurisdiction=sedro&q=adu&limit=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "sedro_woolley")
        self.assertEqual(payload["q"], "adu")
        self.assertEqual(len(payload["hits"]), 1)
        mock_search.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.search")
    def test_legal_search_burlington_success(self, mock_search):
        mock_search.return_value = [
            {
                "id": "ec:burlington:abc",
                "cite": None,
                "heading": "Shoreline Master Program",
                "snippet": "Result preview",
                "url": "https://ecode360.com/46381611",
            }
        ]
        response = self.client.get("/agent/legal/search/?jurisdiction=burlington&q=shoreline")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "burlington")
        self.assertEqual(len(payload["hits"]), 1)
        mock_search.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.search")
    def test_legal_search_anacortes_success(self, mock_search):
        mock_search.return_value = [
            {
                "id": "mc:anacortes:abc",
                "cite": "19.47.030",
                "heading": "Ch. 19.47 Accessory Uses and Structures",
                "snippet": "Accessory use standards...",
                "url": "https://anacortes.municipal.codes/AMC/19.47.030",
            }
        ]
        response = self.client.get("/agent/legal/search/?jurisdiction=anacortes&q=adu")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "anacortes")
        self.assertEqual(len(payload["hits"]), 1)
        mock_search.assert_called_once()

    def test_legal_get_missing_id(self):
        response = self.client.get("/agent/legal/get/?jurisdiction=sedro_woolley")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "missing_id"})

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_success(self, mock_get):
        mock_get.return_value = {
            "cite": "8.28.100",
            "text": "8.28.100 Purpose. Accessory dwelling units are allowed.",
            "url": "https://www.codepublishing.com/WA/SedroWoolley/html/SedroWoolley08/SedroWoolley0828.html#8.28.100",
            "neighbors": {
                "prev": "cp:sedro_woolley:prev",
                "next": "cp:sedro_woolley:next",
            },
        }

        response = self.client.get("/agent/legal/get/?jurisdiction=sedro&id=cp:sedro_woolley:abc")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "sedro_woolley")
        self.assertEqual(payload["id"], "cp:sedro_woolley:abc")
        self.assertEqual(payload["cite"], "8.28.100")
        self.assertIn("neighbors", payload)
        mock_get.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_burlington_success(self, mock_get):
        mock_get.return_value = {
            "cite": None,
            "text": "Burlington section text.",
            "url": "https://ecode360.com/46381611",
        }
        response = self.client.get("/agent/legal/get/?jurisdiction=burlington&id=ec:burlington:abc")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "burlington")
        self.assertEqual(payload["text"], "Burlington section text.")
        mock_get.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_anacortes_success(self, mock_get):
        mock_get.return_value = {
            "cite": "19.47.030",
            "text": "Accessory use and structure standards.",
            "url": "https://anacortes.municipal.codes/AMC/19.47.030",
        }
        response = self.client.get("/agent/legal/get/?jurisdiction=anacortes&id=mc:anacortes:abc")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "anacortes")
        self.assertEqual(payload["cite"], "19.47.030")
        mock_get.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_washington_state_success(self, mock_get):
        mock_get.return_value = {
            "cite": "RCW 22.09.045",
            "text": "Application for grain dealer license.",
            "url": "https://app.leg.wa.gov/RCW/default.aspx?cite=22.09.045",
        }
        response = self.client.get(
            "/agent/legal/get/?jurisdiction=washington_state&id=wa:washington_state:abc"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jurisdiction"], "washington_state")
        self.assertEqual(payload["cite"], "RCW 22.09.045")
        mock_get.assert_called_once()

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_not_found(self, mock_get):
        mock_get.side_effect = db_legal.NotFoundError("id_not_found")
        response = self.client.get("/agent/legal/get/?jurisdiction=sedro&id=cp:sedro_woolley:abc")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "id_not_found"})

    @patch("mcp_agent.legal.views.db_legal.get")
    def test_legal_get_invalid_id_has_hint(self, mock_get):
        mock_get.side_effect = ValueError("invalid_id_payload")
        response = self.client.get("/agent/legal/get/?jurisdiction=sedro&id=cp:sedro_woolley:bad")
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "invalid_id_payload")
        self.assertIn("hint", payload.get("details", {}))


class LegalDbAdapterUnitTests(SimpleTestCase):
    def test_extract_citation_terms_numeric(self):
        terms = db_legal._extract_citation_terms("please fetch 14.16.710 accessory dwelling unit")
        self.assertEqual(terms, ["14.16.710"])

    def test_extract_citation_terms_wac(self):
        terms = db_legal._extract_citation_terms("wac 365-196-410 housing element")
        self.assertEqual(terms, ["365-196-410"])

    def test_extract_citation_terms_ignores_chapter_style(self):
        terms = db_legal._extract_citation_terms("chapter 14.16 adu")
        self.assertEqual(terms, [])

    def test_parse_legacy_id_with_hits_section(self):
        payload = {"u": "https://www.codepublishing.com/search/?cmd=getdoc&hits=14.18.106+"}
        token = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        parsed = db_legal._parse_id(f"cp:skagit_county:{token}")
        self.assertEqual(parsed, ("cp", "skagit_county", "ALL", "14.18", "14.18.106"))

    def test_parse_legacy_id_ambiguous_raises(self):
        payload = {"u": "https://www.codepublishing.com/search/?cmd=getdoc&DocId=SkagitCounty14.16"}
        token = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        with self.assertRaisesMessage(ValueError, "legacy_id_ambiguous"):
            db_legal._parse_id(f"cp:skagit_county:{token}")


class McpOpenApiCoverageTests(SimpleTestCase):
    def _load_openapi_paths(self):
        openapi_path = Path(__file__).resolve().parents[1] / "mcp_agent_openapi.json"
        payload = json.loads(openapi_path.read_text(encoding="utf-8"))
        return set(payload.get("paths", {}).keys())

    def test_openapi_covers_all_mcp_routes(self):
        documented_paths = self._load_openapi_paths()
        code_paths = _collect_mcp_routes(get_resolver().url_patterns)
        missing = sorted(code_paths - documented_paths)
        self.assertEqual(
            missing,
            [],
            f"mcp_agent_openapi.json is missing routes: {', '.join(missing)}",
        )

    def test_openapi_includes_sales_comps_v2_alias(self):
        documented_paths = self._load_openapi_paths()
        self.assertIn("/agent/parcel/{parcel_id}/sales-comps/v2/", documented_paths)

    def test_openapi_includes_neighborhood_analysis_alias(self):
        documented_paths = self._load_openapi_paths()
        self.assertIn("/agent/parcel/{parcel_id}/neighborhood-analysis/", documented_paths)

    def test_openapi_includes_legacy_agent_api_lookup(self):
        documented_paths = self._load_openapi_paths()
        self.assertIn("/agent/api/lookup/", documented_paths)

    def test_openapi_includes_gastronet_menu_items(self):
        documented_paths = self._load_openapi_paths()
        self.assertIn("/api/gastronet/menu-items/", documented_paths)


class ParcelImageryCompareHelpersTests(SimpleTestCase):
    def test_tile_math_matches_known_example(self):
        x, y = mcp_views._latlon_to_xyz_tile(48.523310386, -121.875992547, 19)
        self.assertEqual((x, y), (84649, 181105))

    def test_extract_sketch_relative_path(self):
        payload = {
            "d": (
                '<div>Improvements <a href="/assessor/images/photos/4582/3581958.jpg">'
                "View sketch</a></div>"
            )
        }
        self.assertEqual(
            mcp_views._extract_sketch_relative_path(payload),
            "/assessor/images/photos/4582/3581958.jpg",
        )

    def test_sanitizer_downgrades_contradictory_new_outbuilding_claim(self):
        parsed = {
            "summary": "A new outbuilding is detected, but it may have existed prior to 2019.",
            "overall_confidence": 0.9,
            "new_outbuilding": {
                "detected": True,
                "confidence": 0.9,
                "notes": "A small outbuilding appears new, but may have existed prior to 2019.",
            },
            "roof_change": {"detected": True, "confidence": 0.8, "notes": "Roof color appears darker."},
            "changes_noted": ["New outbuilding constructed."],
            "uncertainties": [],
        }

        sanitized, meta = mcp_views._sanitize_parcel_imagery_ai_result(parsed, tile_span=0)

        self.assertIsNotNone(sanitized)
        self.assertTrue(meta["applied"])
        self.assertFalse(sanitized["new_outbuilding"]["detected"])
        self.assertLessEqual(sanitized["new_outbuilding"]["confidence"], 0.35)
        self.assertGreater(len(sanitized["uncertainties"]), 0)
        self.assertIn("uncertain", " ".join(sanitized["changes_noted"]).lower())

    def test_tile_grid_returns_nine_tiles_for_3x3(self):
        grid = mcp_views._tile_grid(19, 84649, 181105, 1)
        self.assertEqual(len(grid), 9)
        self.assertTrue(any(tile["dx"] == 0 and tile["dy"] == 0 for tile in grid))


class ParcelListingHelpersTests(SimpleTestCase):
    def test_extracts_grounding_sources_and_deduplicates(self):
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    grounding_metadata=SimpleNamespace(
                        grounding_chunks=[
                            SimpleNamespace(web=SimpleNamespace(uri="https://www.redfin.com/home/1", title="Redfin")),
                            SimpleNamespace(web=SimpleNamespace(uri="https://www.redfin.com/home/1", title="Duplicate")),
                            {"web": {"uri": "https://www.zillow.com/homedetails/2", "title": "Zillow"}},
                        ]
                    )
                )
            ]
        )

        sources = mcp_views._extract_gemini_grounding_sources(response)

        self.assertEqual(
            sources,
            [
                {"url": "https://www.redfin.com/home/1", "title": "Redfin"},
                {"url": "https://www.zillow.com/homedetails/2", "title": "Zillow"},
            ],
        )


class ParcelListingApiTests(SimpleTestCase):
    @patch("mcp_agent.views._build_parcel_listing_payload")
    def test_endpoint_wires_query_params(self, mock_build):
        mock_build.return_value = ({"parcel_id": "P42711", "listing_research": {}}, 200)

        response = self.client.get(
            "/agent/parcel/P42711/listing/?site=realtor&model=gemini-2.5-flash&include_raw=1"
        )

        self.assertEqual(response.status_code, 200)
        mock_build.assert_called_once_with(
            "P42711",
            gemini_model="gemini-2.5-flash",
            site_hint="realtor",
            include_raw=True,
        )

    def test_endpoint_rejects_invalid_site(self):
        response = self.client.get("/agent/parcel/P42711/listing/?site=craigslist")
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "invalid_site")
        self.assertIn("allowed", payload.get("details", {}))


class ParcelImageryCompareApiTests(SimpleTestCase):
    @patch("mcp_agent.views._build_parcel_imagery_change_payload")
    def test_endpoint_wires_query_params(self, mock_build):
        mock_build.return_value = ({"parcel_id": "P42711", "ok": True}, 200)

        response = self.client.get("/agent/parcel/P42711/imagery-change/?analyze=0&z=19")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["parcel_id"], "P42711")
        mock_build.assert_called_once_with(
            "P42711",
            analyze=False,
            z=19,
            gemini_model="gemini-2.0-flash",
            tile_span=0,
        )

    def test_endpoint_rejects_invalid_z(self):
        response = self.client.get("/agent/parcel/P42711/imagery-change/?z=not-a-number")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_z"})

    @patch("mcp_agent.views._build_parcel_imagery_change_payload")
    def test_endpoint_accepts_tile_span(self, mock_build):
        mock_build.return_value = ({"parcel_id": "P42711", "ok": True}, 200)
        response = self.client.get("/agent/parcel/P42711/imagery-change/?tile_span=1")
        self.assertEqual(response.status_code, 200)
        mock_build.assert_called_once_with(
            "P42711",
            analyze=True,
            z=19,
            gemini_model="gemini-2.0-flash",
            tile_span=1,
        )

    def test_endpoint_rejects_invalid_tile_span(self):
        response = self.client.get("/agent/parcel/P42711/imagery-change/?tile_span=2")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_tile_span"})

    @patch("mcp_agent.views._build_parcel_imagery_change_payload")
    def test_endpoint_compact_profile_trims_debug_fields(self, mock_build):
        mock_build.return_value = (
            {
                "parcel_id": "P42711",
                "imagery": {
                    "layers": {
                        "historical_2019": {
                            "label": "2019",
                            "url": "https://example.com/2019.png",
                            "tiles": [{"z": 19, "x": 1, "y": 2, "dx": 0, "dy": 0}],
                        }
                    }
                },
                "sketch": {
                    "found": True,
                    "endpoint": "https://county.example/fillPage",
                    "relative_url": "/assessor/images/photos/example.jpg",
                    "url": "https://county.example/assessor/images/photos/example.jpg",
                },
                "ai_analysis": {
                    "status": "ok",
                    "input_strategy": {
                        "requested_tile_span": 1,
                        "images_2019_count": 9,
                        "images_2025_count": 9,
                        "ai_input_mode": "stitched_mosaic",
                        "mosaic_2019": {"bytes": 123},
                    },
                    "raw_text": "very long",
                },
                "ai_inputs": {
                    "strategy": {"tile_span": 1, "tiles_per_year_requested": 9},
                    "images": [{"label": "foo"}],
                },
            },
            200,
        )

        response = self.client.get("/agent/parcel/P42711/imagery-change/?compact=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("response_profile", payload)
        self.assertTrue(payload["response_profile"]["compact"])
        self.assertNotIn("raw_text", payload["ai_analysis"])
        self.assertEqual(payload["ai_inputs"], {"strategy": {"tile_span": 1, "tiles_per_year_requested": 9}})
        self.assertNotIn("endpoint", payload["sketch"])
        self.assertNotIn("relative_url", payload["sketch"])
        self.assertEqual(payload["imagery"]["layers"]["historical_2019"]["tile_count"], 1)
        self.assertNotIn("tiles", payload["imagery"]["layers"]["historical_2019"])

    @patch("mcp_agent.views._build_parcel_imagery_change_payload")
    def test_endpoint_compact_profile_can_reinclude_raw(self, mock_build):
        mock_build.return_value = ({"parcel_id": "P42711", "ai_analysis": {"raw_text": "x"}}, 200)
        response = self.client.get("/agent/parcel/P42711/imagery-change/?compact=1&include_raw_text=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai_analysis"]["raw_text"], "x")
