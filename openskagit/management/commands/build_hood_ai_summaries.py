import json
from django.core.management.base import BaseCommand, CommandError
from openskagit.models import NeighborhoodProfile
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
import os
class Command(BaseCommand):
    help = "Generate an AI-written neighborhood summary for a single hood."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hood",
            type=str,
            required=True,
            help="Neighborhood code to generate the summary for.",
        )

    def handle(self, *args, **options):
        hood = options["hood"]

        # Load profile
        try:
            profile = NeighborhoodProfile.objects.get(hood_id=hood)
        except NeighborhoodProfile.DoesNotExist:
            raise CommandError(f"No NeighborhoodProfile found for hood '{hood}'")

        data = profile.json_data
        if not data:
            raise CommandError(f"No JSON profile data found for hood '{hood}'")
        sales = data.get("sales", {})

        sale_count = sales.get("sale_count", 0)
        if sale_count < 15:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping {hood}: only {sale_count} sales (< 15 required)"
                )
            )
            return
    
        # Build prompt
        prompt = f"""
            **Role:** You are an expert Real Estate Market Analyst for Washington State.
                **Task:** Write a polished, consumer-facing neighborhood profile for a potential buyer or property owner.

                **Neighborhood Code:** {hood}

                **CRITICAL DATA HANDLING RULES:**
                1.  **Ignore Missing Data:** If a value is "0", "0.0", or an empty object ({{}}), **do not mention it**. Do not state "data is unavailable." Simply skip that topic.
                    * *Example:* The median price is 0. Do not mention price. Focus on the *volume* of sales (81 sales) instead.
                2.  **Unit Conversion:** Amenities are listed in **meters**. You MUST convert them to **miles** (Divide by 1609). Round to one decimal place.
                    * *Context:* If a school is >5 miles away, describe the location as "secluded" or "removed from city centers."
                3.  **Style Synthesis:** The 'styles' list contains duplicates/overlaps (e.g., "ONE STORY" vs "1 STRY"). Group these mentally. Identify the top 2-3 dominant specific architectural styles (e.g., Ramblers/One-Story) rather than listing generic terms like "Single Family Residence."
                4.  **Fair Housing:** Strictly no demographics (race, religion, etc). Focus on the physical assets.

                **Narrative Structure (3 Paragraphs):**

                **Paragraph 1: The Setting & Land**
                * Focus on the `lot_size` and `amenities`.
                * Describe the typical density based on the median acreage (e.g., 0.57 acres = "generous half-acre lots," "spacious suburban feel," or "rural residential" depending on context).
                * Mention proximity to parks/schools (in miles). If schools are far (like the 18km in the data), highlight the privacy/seclusion.

                **Paragraph 2: The Homes (Inventory Profile)**
                * Use `median_year_built` and `age_distribution` to describe the era (e.g., "Established in the early 1980s...").
                * Discuss the dominant `styles` found in the data.
                * Mention `living_area_stats` (median size) and bathroom counts to paint a picture of the "typical" home.

                **Paragraph 3: Market Activity & Composition**
                * Reference `sale_count` to indicate market activity (e.g., "With 81 recent transactions...").
                * Briefly mention the `land_use_mix` if relevant (mostly residential vs. mixed), but keep it simple.
                * Conclude with a summary of the lifestyle (e.g., "Ideal for those seeking room to breathe...").

                **Tone:** Warm, professional, and informative. Avoid negative phrasing about missing data.
                                ##JUST RETURN SUMMARY NOT INTRO OR COMMENTS FROM YOU.
            **Data:**
            {data}
            """

        self.stdout.write(f"Calling OpenAI for hood {hood}…")

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # OpenAI responses.create call
        response = client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
        )

        # Extract output text
        try:
            ai_text = response.output_text
        except AttributeError:
            # fallback
            ai_text = response.output[0].content[0].text

        # Save
        profile.ai_summary = ai_text
        profile.save()

        self.stdout.write(self.style.SUCCESS(f"✓ AI summary saved for {hood}"))
        self.stdout.write("")
        self.stdout.write(ai_text)
