from typing import Dict, List, Optional

JURISDICTIONS: List[Dict[str, object]] = [
    {
        "slug": "sedro_woolley",
        "name": "City of Sedro-Woolley",
        "publisher": "codepublishing",
        "aliases": ["sedro", "sw"],
        "base_url": "https://www.codepublishing.com/WA/SedroWoolley/",
        "search_form": "/WA/SedroWoolley/search_form.html",
        "orig_search_form": "/WA/SedroWoolley/search_form.html",
        "search_index": "/WA/SedroWoolley",
    },
    {
        "slug": "mount_vernon",
        "name": "City of Mount Vernon",
        "publisher": "codepublishing",
        "aliases": ["mv", "mountvernon"],
        "base_url": "https://www.codepublishing.com/WA/MountVernon/",
        "search_form": "/WA/MountVernon/search_form.html",
        "orig_search_form": "/WA/MountVernon/search_form.html",
        "search_index": "/WA/MountVernon",
    },
    {
        "slug": "la_conner",
        "name": "Town of La Conner",
        "publisher": "codepublishing",
        "aliases": ["laconner", "la-conner", "lc"],
        "base_url": "https://www.codepublishing.com/WA/LaConner/",
        "search_form": r"D:\inetpub\wwwroot\public_html\WA\LaConner\LaConner_formSML.html",
        "orig_search_form": r"D:\inetpub\wwwroot\public_html\WA\LaConner\LaConner_formSML.html",
        "search_index": r"D:\Program Files\dtSearch\UserData\WA\LaConner_index",
    },
    {
        "slug": "skagit_county",
        "name": "Skagit County",
        "publisher": "codepublishing",
        "aliases": ["skagit", "county"],
        "base_url": "https://www.codepublishing.com/WA/SkagitCounty/",
        "search_form": r"D:\inetpub\wwwroot\public_html\WA\SkagitCounty\SkagitCounty_formSML.html",
        "orig_search_form": r"D:\inetpub\wwwroot\public_html\WA\SkagitCounty\SkagitCounty_formSML.html",
        "search_index": r"D:\Program Files\dtSearch\UserData\WA\SkagitCounty_index",
    },
    {
        "slug": "anacortes",
        "name": "City of Anacortes",
        "publisher": "municipal_codes",
        "aliases": ["ana"],
        "base_url": "https://anacortes.municipal.codes/",
    },
    {
        "slug": "burlington",
        "name": "City of Burlington",
        "publisher": "ecode360",
        "aliases": ["burl"],
        "base_url": "https://ecode360.com/BU4372",
    },
    {
        "slug": "washington_state",
        "name": "State of Washington (Laws and Rules)",
        "publisher": "wa_legislature",
        "aliases": ["wa", "state", "rcw"],
        "base_url": "https://search.leg.wa.gov/search.aspx",
    },
]

JURIS_BY_SLUG: Dict[str, Dict[str, object]] = {
    str(j["slug"]): j for j in JURISDICTIONS
}

JURIS_BY_ALIAS: Dict[str, str] = {}
for _jur in JURISDICTIONS:
    _slug = str(_jur["slug"])
    JURIS_BY_ALIAS[_slug] = _slug
    for _alias in _jur.get("aliases", []):
        JURIS_BY_ALIAS[str(_alias)] = _slug


def resolve_jurisdiction(raw: Optional[str]) -> Optional[Dict[str, object]]:
    key = (raw or "").strip().lower()
    if not key:
        return None
    slug = JURIS_BY_ALIAS.get(key)
    if not slug:
        return None
    return JURIS_BY_SLUG.get(slug)
