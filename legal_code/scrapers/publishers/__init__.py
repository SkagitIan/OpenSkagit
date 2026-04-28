from typing import Callable, Dict, List, Optional

from legal_code.scrapers.base import PlaywrightClient
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.errors import ParseError
from legal_code.scrapers.types import ScrapedSection

from . import codepublishing
from . import ecode360
from . import municipal_codes
from . import wa_legislature

PublisherScrapeFn = Callable[
    [PlaywrightClient, JurisdictionConfig],
    List[ScrapedSection],
]

PUBLISHER_SCRAPERS: Dict[str, Callable[..., List[ScrapedSection]]] = {
    "codepublishing": codepublishing.scrape,
    "municipal_codes": municipal_codes.scrape,
    "ecode360": ecode360.scrape,
    "wa_legislature": wa_legislature.scrape,
}


def scrape_jurisdiction(
    client: PlaywrightClient,
    jurisdiction: JurisdictionConfig,
    *,
    max_pages: Optional[int] = None,
) -> List[ScrapedSection]:
    scraper = PUBLISHER_SCRAPERS.get(jurisdiction.publisher)
    if scraper is None:
        raise ParseError(
            "publisher_scraper_missing",
            details={"jurisdiction": jurisdiction.slug, "publisher": jurisdiction.publisher},
        )
    return scraper(client, jurisdiction, max_pages=max_pages)


__all__ = [
    "PUBLISHER_SCRAPERS",
    "scrape_jurisdiction",
]
