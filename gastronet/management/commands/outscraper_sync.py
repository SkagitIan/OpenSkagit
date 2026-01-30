import json
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from gastronet.models import Restaurant

SKAGIT_VALLEY_CHAINS = [
    "Applebee's Grill + Bar",
    "Arby's",
    "Avenue Catering",
    "Baskin-Robbins",
    "Burger King",
    "Chipotle Mexican Grill",
    "Crumbl Cookies",
    "Dairy Queen",
    "Denny's",
    "Domino's Pizza",
    "Firehouse Subs",
    "Jack in the Box",
    "Jersey Mike's Subs",
    "Jimmy John's",
    "KFC",
    "Little Caesars Pizza",
    "McDonald's",
    "MOD Pizza",
    "Mountain Mike's Pizza",
    "Olive Garden",
    "Panda Express",
    "Panera Bread",
    "Papa Murphy's",
    "Pizza Hut",
    "Red Robin Gourmet Burgers",
    "Starbucks",
    "Subway",
    "Taco Bell",
    "Taco Time NW",
    "Wendy's",
    "Whidbey Coffee",
]
CHAIN_KEYWORDS = [name.casefold() for name in SKAGIT_VALLEY_CHAINS]
DEFAULT_PATH = Path("/home/django/django_project/data/outscraper12.29.json")
FILTER_KEYWORDS = ["hotel", "clarion", "friendship house", "willowbrook"]


def _truncate(value, max_length):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_length and len(text) > max_length:
        return text[:max_length]
    return text


def _parse_review_count(value):
    if value in (None, "", "null"):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _normalize_links(value):
    if not value:
        return None
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if item]
    else:
        cleaned = [part.strip() for part in str(value).split(",") if part.strip()]
    return cleaned or None


def _is_chain_name(name):
    if not name:
        return False
    normalized = name.casefold()
    normalized = normalized.split("|")[0].strip()
    return any(keyword in normalized for keyword in CHAIN_KEYWORDS)


def _should_skip_name(name: str):
    if not name:
        return False
    normalized = name.casefold()
    return any(keyword in normalized for keyword in FILTER_KEYWORDS)


class Command(BaseCommand):
    help = (
        "Discover or ingest new restaurants from an Outscraper JSON dump and flag chain locations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=str(DEFAULT_PATH),
            help="Path to an Outscraper JSON dump (defaults to the 12.29 data file).",
        )
        parser.add_argument(
            "--discover",
            action="store_true",
            help="List restaurants missing from the database without inserting them.",
        )
        parser.add_argument(
            "--ingest",
            action="store_true",
            help="Ingest restaurants that do not already exist in gastronet.models.restaurant.",
        )

    def handle(self, *args, **opts):
        discover = opts["discover"]
        ingest = opts["ingest"]
        if not (discover or ingest):
            raise CommandError("Select either --discover or --ingest to operate.")
        if discover and ingest:
            raise CommandError("Use only one of --discover or --ingest per run.")

        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"Outscraper file not found at {path}")

        raw_records = self._load_records(path)
        self.stdout.write(f"Loaded {len(raw_records)} records from {path}")

        existing_ids = set(Restaurant.objects.values_list("place_id", flat=True))
        created = 0
        skipped = 0
        chain_count = 0
        existing_skipped = 0
        filtered_skipped = 0

        for rec in raw_records:
            pid = rec.get("place_id")
            raw_name = (rec.get("name") or rec.get("name_for_emails") or "").strip()
            if not pid or not raw_name:
                skipped += 1
                continue
            if _should_skip_name(raw_name):
                filtered_skipped += 1
                continue
            if pid in existing_ids:
                existing_skipped += 1
                continue

            is_chain = _is_chain_name(raw_name)
            existing_ids.add(pid)
            city_raw = rec.get("city") or rec.get("state") or "Unknown"
            city = _truncate(city_raw, 100) or "Unknown"
            name = _truncate(raw_name, 255) or raw_name
            rating = rec.get("rating")
            chain_label = "chain" if is_chain else "local"

            cuisine = _truncate(rec.get("subtypes"), 100)

            if discover:
                self.stdout.write(
                    f"· {name} ({city}) rating={rating or 'n/a'} chain={chain_label}"
                )
                chain_count += int(bool(is_chain))
                created += 1
                continue

            review_count = _parse_review_count(rec.get("reviews"))
            lat = rec.get("latitude")
            lon = rec.get("longitude")
            location = None
            if lat is not None and lon is not None:
                try:
                    location = Point(float(lon), float(lat))
                except (TypeError, ValueError):
                    location = None

            Restaurant.objects.create(
                place_id=pid,
                name=name,
                address=rec.get("address"),
                city=city,
                website=rec.get("website") or rec.get("site"),
                phone=rec.get("phone"),
                category=rec.get("category") or rec.get("type"),
                rating=rec.get("rating"),
                review_count=review_count,
                summary=rec.get("description"),
                latitude=lat,
                longitude=lon,
                location=location,
                menu_url=rec.get("menu_link"),
                logo_url=rec.get("logo"),
                photo_url=rec.get("photo"),
                reviews_url=rec.get("reviews_link"),
                reservation_links=_normalize_links(rec.get("reservation_links")),
                order_links=_normalize_links(rec.get("order_links")),
                booking_appointment_link=rec.get("booking_appointment_link"),
                owner_link=rec.get("owner_link"),
                location_link=rec.get("location_link"),
                price_range=_truncate(rec.get("range"), 20),
                cuisine=cuisine,
                hours=rec.get("working_hours"),
                about=rec.get("about"),
                source="outscraper",
                is_chain=is_chain,
            )
            created += 1
            chain_count += int(bool(is_chain))
            self.stdout.write(
                f"➕ Ingested {name} ({city}) rating={rating or 'n/a'} chain={chain_label}"
            )

        summary = []
        if discover:
            summary.append(f"New restaurants listed: {created}")
        else:
            summary.append(f"Restaurants ingested: {created}")

        if chain_count:
            summary.append(f"Chain restaurants detected: {chain_count}")
        summary.append(f"Existing entries skipped: {existing_skipped}")
        summary.append(f"Filtered by name rules: {filtered_skipped}")
        summary.append(f"Records missing key data: {skipped}")

        self.stdout.write(self.style.SUCCESS(" — ".join(summary)))

    def _load_records(self, path: Path):
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Unable to parse JSON: {exc}") from exc

        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict) and "data" in payload:
            records = []
            for batch in payload["data"]:
                if isinstance(batch, list):
                    records.extend(batch)
                elif isinstance(batch, dict):
                    records.append(batch)
            return records

        raise CommandError("Outscraper JSON structure not recognized.")
