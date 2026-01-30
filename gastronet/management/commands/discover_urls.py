import requests
from urllib.parse import urlparse
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from gastronet.models import Restaurant  # adjust app name


SERP_API_ENDPOINT = "https://serpapi.com/search.json"


def _domain(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(url)
    host = parsed.netloc.lower() or parsed.path.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def infer_platform(url: str | None) -> str | None:
    host = _domain(url)
    if not host:
        return None

    if "toasttab.com" in host:
        return "toast"
    if "square.site" in host or "squareup.com" in host:
        return "square"
    if "clover.com" in host:
        return "clover"
    if "order.online" in host:
        return "order_online"
    if "ubereats.com" in host:
        return "ubereats"
    if "doordash.com" in host or "trycaviar.com" in host:
        return "doordash"
    if "grubhub.com" in host or "seamless.com" in host:
        return "grubhub"
    if "postmates.com" in host:
        return "postmates"
    if "chownow.com" in host:
        return "chownow"
    if "slice.life" in host or "slicelife.com" in host:
        return "slice"
    if "delivery.com" in host:
        return "delivery.com"
    if "ezcater.com" in host:
        return "ezcater"

    return host


class Command(BaseCommand):
    help = "Inspect SerpAPI results for a restaurant and persist menu links + profiles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--restaurant-id",
            type=int,
            help="Restaurant ID to inspect",
        )
        parser.add_argument(
            "--new",
            action="store_true",
            help="Target restaurants that do not have a website URL yet.",
        )
        parser.add_argument(
            "--menu",
            action="store_true",
            help="Target restaurants that do not have a menu_url yet.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Number of restaurants to process when using --new/--menu (default: 1).",
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, "SERP_API_KEY", None)
        if not api_key:
            self.stderr.write("SERP_API_KEY not set")
            return

        targets = []
        limit = max(1, options.get("limit") or 1)

        if options.get("restaurant_id"):
            try:
                restaurant = Restaurant.objects.get(id=options["restaurant_id"])
            except Restaurant.DoesNotExist:
                self.stderr.write(f"Restaurant {options['restaurant_id']} not found")
                return

            if getattr(restaurant, "is_chain", False):
                self.stdout.write(f"Skipping restaurant {restaurant.id} ({restaurant.name}): is_chain=True")
                return

            targets = [restaurant]
        else:
            qs = Restaurant.objects.filter(is_chain=False)

            if options.get("new"):
                qs = qs.filter(Q(website__isnull=True) | Q(website__exact=""))

            if options.get("menu"):
                qs = qs.filter(Q(menu_url__isnull=True) | Q(menu_url__exact=""))

            if not options.get("new") and not options.get("menu"):
                self.stderr.write("Provide --restaurant-id or use --new and/or --menu.")
                return

            targets = list(qs.order_by("id")[:limit])
            if not targets:
                self.stdout.write("No restaurants matched the provided filters.")
                return

        for restaurant in targets:
            params = {
                "engine": "google",
                "q": f"Online Menu for {restaurant.name} in {restaurant.address}",
                "hl": "en",
                "gl": "us",
                #"location":"Mount Vernon, WA",
                "ludocid": str(restaurant.place_id),
                "api_key": api_key,
            }

            resp = requests.get(SERP_API_ENDPOINT, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            kg = data.get("knowledge_graph", {})

            website = kg.get("website")
            website_domain = _domain(website)
            profiles = kg.get("profiles") or []

            ordering_urls = []

            # knowledge graph menu links
            for link in kg.get("menu_links", []):
                if link.get("link"):
                    ordering_urls.append(link["link"])

            # explicit "order online" link
            order_link = kg.get("links", {}).get("order_online")
            if order_link:
                ordering_urls.append(order_link)

            # organic results (own site + any third-party platforms)
            for r in data.get("organic_results", []):
                link = r.get("link", "")
                if not link:
                    continue
                domain = _domain(link)
                if website_domain and domain == website_domain:
                    ordering_urls.append(link)
                    continue
                ordering_urls.append(link)

            ordering_urls = list(dict.fromkeys(ordering_urls))  # de-dupe

            update_fields = []
            if website and not restaurant.website:
                restaurant.website = website
                update_fields.append("website")
            if ordering_urls:
                restaurant.order_links = ordering_urls
                update_fields.append("order_links")
                if not restaurant.menu_url:
                    restaurant.menu_url = ordering_urls[0]
                    update_fields.append("menu_url")
            if profiles:
                restaurant.profiles = profiles
                update_fields.append("profiles")

            if update_fields:
                restaurant.save(update_fields=sorted(set(update_fields)))

            self.stdout.write("")
            self.stdout.write("=" * 72)
            self.stdout.write(f"Restaurant: {restaurant.name}")
            self.stdout.write("-" * 72)

            self.stdout.write(f"Website URL: {restaurant.website or website or '—'}")

            self.stdout.write("")
            self.stdout.write("Ordering / Menu URLs:")
            if not ordering_urls:
                self.stdout.write("  — none found")
            else:
                for url in ordering_urls:
                    platform = infer_platform(url)
                    self.stdout.write(f"  - {url}")
                    self.stdout.write(f"    platform: {platform}")

            if profiles:
                self.stdout.write("")
                self.stdout.write("Profiles:")
                for p in profiles:
                    name = p.get("name") or "Profile"
                    link = p.get("link") or "—"
                    self.stdout.write(f"  - {name}: {link}")

            self.stdout.write("=" * 72)
            self.stdout.write("")
