import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from dotenv import load_dotenv

from agent.services.competition_analysis import CompetitionAnalysisService


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class Command(BaseCommand):
    help = "Run a grounded competition analysis for a Google Places subject."

    def add_arguments(self, parser):
        parser.add_argument("--place-id", help="Google Place ID for the subject.")
        parser.add_argument(
            "--skip-scout",
            action="store_true",
            help="Skip the run_scout_and_enrich phase. Requires alternative data.",
        )
        parser.add_argument(
            "--skip-deep",
            action="store_true",
            help="Skip the deep competitor enrichment phase.",
        )
        parser.add_argument(
            "--grounded-name", help="Business name for a focused grounded intel request."
        )
        parser.add_argument(
            "--grounded-location", help="Location for the focused grounded intel request."
        )
        parser.add_argument(
            "--grounded-type", help="Business type for the focused grounded intel request."
        )
        parser.add_argument(
            "--output-file",
            default="competition_analysis_payload.json",
            help="File path where final JSON payload is written (overwrites).",
        )

    def handle(self, *args, **options):
        place_id = options.get("place_id")
        if not options["skip_scout"] and not place_id:
            raise CommandError("--place-id is required unless --skip-scout is passed.")

        try:
            service = CompetitionAnalysisService(
                google_api_key=getattr(settings, "GOOGLE_PLACES_API_KEY", ""),
                genai_api_key=getattr(settings, "GENAI_API_KEY", ""),
                outscraper_api_key=getattr(settings, "OUTSCRAPER_API_KEY", None),
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        output: Dict[str, Any] = {
            "request": {
                "place_id": place_id,
                "skip_scout": options["skip_scout"],
                "skip_deep": options["skip_deep"],
            },
            "results": {},
        }

        subject_payload: Optional[Dict[str, Any]] = None
        vetted: List[Dict[str, Any]] = []

        if not options["skip_scout"]:
            subject_payload, vetted = service.run_scout_and_enrich(place_id)
            output["results"]["scout_and_enrich"] = {
                "subject": subject_payload,
                "vetted_competitors": vetted,
            }

        if not options["skip_deep"] and subject_payload and vetted:
            deep_result = service.run_deep_competitor_analysis(subject_payload, vetted)
            output["results"]["deep_competitors"] = deep_result

        if options.get("grounded_name") and options.get("grounded_location") and options.get("grounded_type"):
            custom_grounded = service.get_grounded_intel(
                options["grounded_name"],
                options["grounded_location"],
                options["grounded_type"],
            )
            output["results"]["grounded_intel"] = {
                "input": {
                    "business_name": options["grounded_name"],
                    "location": options["grounded_location"],
                    "business_type": options["grounded_type"],
                },
                "intel": custom_grounded,
            }

        serialized = json.dumps(output, indent=2)
        self.stdout.write(serialized)

        output_path = options["output_file"]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        self.stdout.write(f"Saved competition analysis payload to {output_path}")
