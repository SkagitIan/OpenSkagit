from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OpenSkagitLegal/1.0"
)


@dataclass(frozen=True)
class ScrapeSettings:
    user_agent: str = DEFAULT_USER_AGENT
    wait_until: str = "domcontentloaded"
    navigation_timeout_ms: int = 30_000
    request_timeout_ms: int = 30_000
    challenge_wait_ms: int = 7_000
    max_retries: int = 2
    retry_backoff_seconds: float = 1.25


@dataclass(frozen=True)
class JurisdictionConfig:
    slug: str
    name: str
    publisher: str
    base_url: str
    aliases: Tuple[str, ...] = ()
    scrape_settings: ScrapeSettings = field(default_factory=ScrapeSettings)
    metadata: Mapping[str, str] = field(default_factory=dict)


JURISDICTIONS: Tuple[JurisdictionConfig, ...] = (
    JurisdictionConfig(
        slug="sedro_woolley",
        name="City of Sedro-Woolley",
        publisher="codepublishing",
        base_url="https://www.codepublishing.com/WA/SedroWoolley/",
        aliases=("sedro", "sw"),
    ),
    JurisdictionConfig(
        slug="mount_vernon",
        name="City of Mount Vernon",
        publisher="codepublishing",
        base_url="https://www.codepublishing.com/WA/MountVernon/",
        aliases=("mv", "mountvernon"),
    ),
    JurisdictionConfig(
        slug="la_conner",
        name="Town of La Conner",
        publisher="codepublishing",
        base_url="https://www.codepublishing.com/WA/LaConner/",
        aliases=("laconner", "la-conner", "lc"),
    ),
    JurisdictionConfig(
        slug="skagit_county",
        name="Skagit County",
        publisher="codepublishing",
        base_url="https://www.codepublishing.com/WA/SkagitCounty/",
        aliases=("skagit", "county"),
    ),
    JurisdictionConfig(
        slug="anacortes",
        name="City of Anacortes",
        publisher="municipal_codes",
        base_url="https://anacortes.municipal.codes/",
        aliases=("ana",),
    ),
    JurisdictionConfig(
        slug="burlington",
        name="City of Burlington",
        publisher="ecode360",
        base_url="https://ecode360.com/BU4372",
        aliases=("burl",),
    ),
    JurisdictionConfig(
        slug="washington_state",
        name="State of Washington (Laws and Rules)",
        publisher="wa_legislature",
        base_url="https://search.leg.wa.gov/search.aspx",
        aliases=("wa", "state", "rcw"),
        metadata={
            "search_endpoint": "https://search.leg.wa.gov/SearchTermHandler.ashx?MethodName=Search",
            "doc_base_url": "https://app.leg.wa.gov/",
            "law_docs_scope": "all",
        },
    ),
)

JURISDICTIONS_BY_SLUG: Dict[str, JurisdictionConfig] = {
    jurisdiction.slug: jurisdiction for jurisdiction in JURISDICTIONS
}

JURISDICTIONS_BY_ALIAS: Dict[str, JurisdictionConfig] = {}
for _jurisdiction in JURISDICTIONS:
    JURISDICTIONS_BY_ALIAS[_jurisdiction.slug] = _jurisdiction
    for _alias in _jurisdiction.aliases:
        JURISDICTIONS_BY_ALIAS[_alias] = _jurisdiction


def resolve_jurisdiction(raw: Optional[str]) -> Optional[JurisdictionConfig]:
    key = (raw or "").strip().lower()
    if not key:
        return None
    return JURISDICTIONS_BY_ALIAS.get(key)


def by_publisher(publisher: str) -> Tuple[JurisdictionConfig, ...]:
    key = publisher.strip().lower()
    return tuple(j for j in JURISDICTIONS if j.publisher == key)
