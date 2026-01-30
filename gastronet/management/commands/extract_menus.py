import asyncio
import json
import logging
import os
import re
import random
import time
import hashlib
import psutil
from decimal import Decimal
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from asgiref.sync import sync_to_async

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Set

from bs4 import BeautifulSoup
from gastronet.models import Restaurant, MenuItem, CrawlLog

# Crawl4AI imports
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    LLMConfig,
    LLMExtractionStrategy,
)
from crawl4ai.processors.pdf import PDFContentScrapingStrategy

load_dotenv()
logger = logging.getLogger(__name__)

# ===========================
# Pydantic schema
# ===========================
class ExtractedMenuItem(BaseModel):
    name: str = Field(..., description="Food menu item name")
    description: Optional[str] = Field(default=None, description="Item description")
    price_text: Optional[str] = Field(default=None, description="Price as string")
    section: Optional[str] = Field(default=None, description="Menu category/section")
    dietary_tags: List[str] = Field(default_factory=list, description="Dietary tags")

class MenuSchema(BaseModel):
    items: List[ExtractedMenuItem]


# ===========================
# Enhanced Helpers
# ===========================
MENU_KEYWORDS = [
    "menu", "menus", "food", "eat", "drink", "dining",
    "dinner", "lunch", "brunch", "breakfast", "appetizers",
    "entrees", "entree", "main", "sides", "desserts",
    "takeout", "take-out", "order", "pickup", "delivery",
    "carta", "drinks", "beverage", "wine", "beer", "cocktail",
    "specials", "kids", "children", "catering"
]

ANTI_MENU_KEYWORDS = [
    "contact", "about", "team", "careers", "jobs", "press",
    "login", "signup", "register", "cart", "checkout", "privacy",
    "terms", "policy", "subscribe", "newsletter", "blog", "news"
]

CURRENCY_TOKENS = [
    "$", "€", "£", "¥", "₩", "₽", "₹",
    "usd", "eur", "gbp", "cad", "aud", "nzd", "mxn", "chf",
    "sek", "nok", "dkk", "pln", "hkd", "sgd", "inr", "jpy",
    "cny", "rmb", "krw", "zar", "brl"
]

PDF_EXTS = (".pdf",)
PRICE_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"[$€£¥₩₽₹]|"  # currency symbol
    r"(?:usd|eur|gbp|cad|aud|nzd|mxn|chf|sek|nok|dkk|pln|hkd|sgd|inr|jpy|cny|rmb|krw|zar|brl)\s*"
    r")?"
    r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?"
)

def _maybe_money_to_decimal(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    m = PRICE_PATTERN.search(s)
    if not m:
        return None

    raw_val = m.group(0)
    # Strip currency tokens/symbols and normalize decimal separators
    cleaned = raw_val
    cleaned = re.sub(r"(?i)[$€£¥₩₽₹]", "", cleaned)
    cleaned = re.sub(
        r"(?i)(usd|eur|gbp|cad|aud|nzd|mxn|chf|sek|nok|dkk|pln|hkd|sgd|inr|jpy|cny|rmb|krw|zar|brl)",
        "",
        cleaned,
    )
    cleaned = cleaned.replace("\u00a0", "").strip()
    # If comma is used as decimal separator, flip it to dot (only when dot missing)
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace(" ", "").replace(",", "")
    try:
        return Decimal(cleaned)
    except Exception:
        return None

def make_abs(base: str, link: str) -> str:
    try:
        return urljoin(base, link)
    except Exception:
        return link

def normalize_url(url: str) -> str:
    """Remove trailing slashes and fragments for deduplication."""
    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    if parsed.query:
        clean += f"?{parsed.query}"
    return clean

def default_menu_js_actions() -> List[str]:
    """Generic JS actions to reveal menus on modern sites."""
    return [
        # Click common menu/menu-toggle/order buttons
        """
        (() => {
            const triggers = Array.from(document.querySelectorAll('button, a, [role="button"], [aria-expanded]'));
            const keywords = ["menu", "view menu", "our menu", "order", "order now", "order online", "see menu"];
            for (const el of triggers) {
                const text = (el.innerText || el.textContent || "").toLowerCase();
                if (keywords.some(k => text.includes(k))) {
                    try { el.click(); } catch (e) {}
                }
            }
        })();
        """,
        # Ensure lazy content is loaded
        "window.scrollTo(0, document.body.scrollHeight);",
    ]

def looks_like_menu_link(link_text: str, href: str) -> bool:
    """Enhanced menu link detection with anti-pattern filtering."""
    ltext = (link_text or "").lower().strip()
    lhref = (href or "").lower()
    
    # Check for anti-patterns first
    if any(anti in lhref or anti in ltext for anti in ANTI_MENU_KEYWORDS):
        return False
    
    # Check for menu patterns
    has_menu_keyword = any(k in ltext or k in lhref for k in MENU_KEYWORDS)
    is_pdf = lhref.endswith(PDF_EXTS)
    
    return has_menu_keyword or is_pdf

def aggressive_html_cleanup(html: str, max_tokens: int = 15000) -> str:
    """Aggressively clean and reduce HTML size for LLM processing."""
    if not html:
        return ""
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove all non-content elements
    for tag in soup([
        "script", "style", "link", "meta", "noscript",
        "footer", "header", "nav", "aside", "form",
        "iframe", "svg", "canvas", "video", "audio",
        "button", "input", "select", "textarea",
        # Remove common bloat
        "advertisement", "ad", "banner", "cookie", "modal"
    ]):
        tag.decompose()
    
    # Remove elements by class/id patterns (ads, tracking, etc)
    bloat_patterns = [
        "cookie", "gdpr", "tracking", "analytics", "social",
        "share", "subscribe", "newsletter", "popup", "modal",
        "advertisement", "promo", "banner", "sidebar"
    ]
    
    for element in soup.find_all():
        attrs = " ".join([
            str(element.get("class", [])),
            str(element.get("id", ""))
        ]).lower()
        
        if any(pattern in attrs for pattern in bloat_patterns):
            element.decompose()
    
    # Try to isolate menu content
    menu_section = None
    
    # Strategy 1: Find sections with "menu" in attributes
    for tag in soup.find_all(["div", "section", "main", "article"]):
        tag_id = (tag.get("id") or "").lower()
        tag_classes = " ".join(tag.get("class", [])).lower()
        
        if "menu" in tag_id or "menu" in tag_classes:
            menu_section = tag
            break
    
    # Strategy 2: Find the section with most price indicators
    if not menu_section:
        candidates = soup.find_all(["div", "section", "main"])
        best_score = 0
        
        for candidate in candidates:
            text = candidate.get_text()
            score = text.count("$") + len(PRICE_PATTERN.findall(text))
            if score > best_score:
                best_score = score
                menu_section = candidate
    
    # Use menu section if found, otherwise use body
    content = menu_section if menu_section else soup.body or soup
    
    # Further simplification: extract only relevant elements
    simplified = BeautifulSoup("<div></div>", "html.parser")
    root = simplified.div
    
    for element in content.find_all(["h1", "h2", "h3", "h4", "p", "li", "span", "div"]):
        text = element.get_text(strip=True)
        
        if not text:
            continue
        
        keep = False
        lower_text = text.lower()
        # Keep if price-like or currency tokens
        if "$" in text or PRICE_PATTERN.search(text) or any(token in lower_text for token in CURRENCY_TOKENS):
            keep = True
        # Keep headings/lists to preserve item names even when price is elsewhere
        if element.name in ["h1", "h2", "h3", "h4", "h5", "h6", "li"]:
            if len(text) > 1:
                keep = True
        # Keep if it contains any menu keyword
        if any(kw in lower_text for kw in MENU_KEYWORDS):
            keep = True
        
        if keep:
            new_tag = simplified.new_tag(element.name)
            new_tag.string = text
            root.append(new_tag)
    
    cleaned_html = str(simplified)
    
    # Estimate tokens and truncate if needed (rough: 1 token ≈ 4 chars)
    estimated_tokens = len(cleaned_html) / 4
    if estimated_tokens > max_tokens:
        # Truncate to stay under limit
        max_chars = max_tokens * 4
        cleaned_html = cleaned_html[:max_chars]
        logger.warning(f"Truncated HTML from ~{estimated_tokens:.0f} to ~{max_tokens} tokens")
    
    return cleaned_html

def score_menu_content(html: str) -> int:
    """Score HTML content for menu-like characteristics."""
    if not html:
        return 0
    
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text().lower()
    score = 0
    
    # Count menu indicators
    score += text.count("$") * 2
    score += sum(text.count(kw) for kw in ["appetizer", "entree", "dessert", "side"])
    score += len(PRICE_PATTERN.findall(text))
    
    # Check for menu-specific structures
    if soup.find_all(class_=re.compile(r"menu|item|price|dish", re.I)):
        score += 10
    
    return score

def _coerce_menu_item_from_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Heuristic mapping from arbitrary JSON objects to menu item shape."""
    if not isinstance(data, dict):
        return None
    
    name = data.get("name") or data.get("title") or data.get("item") or data.get("label")
    if not name:
        return None
    name = str(name).strip()
    if len(name) < 2:
        return None
    
    price = (
        data.get("price")
        or data.get("price_text")
        or data.get("priceText")
        or data.get("amount")
        or data.get("cost")
    )
    desc = data.get("description") or data.get("desc")
    section = data.get("section") or data.get("category") or data.get("group")
    tags = data.get("dietary_tags") or data.get("tags") or data.get("labels") or []
    if tags and not isinstance(tags, list):
        tags = [str(tags)]
    
    return {
        "name": name,
        "description": str(desc).strip() if desc else None,
        "price_text": str(price).strip() if price is not None else None,
        "section": str(section).strip() if section else None,
        "dietary_tags": tags or [],
    }

def extract_items_from_structured_payload(payload: Any, seen: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Walk arbitrary nested JSON and pull out menu-like dicts."""
    seen = seen or set()
    items: List[Dict[str, Any]] = []
    
    def walk(node: Any):
        if isinstance(node, list):
            for el in node:
                walk(el)
        elif isinstance(node, dict):
            candidate = _coerce_menu_item_from_dict(node)
            if candidate:
                key = (candidate["name"].lower(), candidate.get("price_text") or "")
                if key not in seen:
                    seen.add(key)
                    items.append(candidate)
            for v in node.values():
                walk(v)
    
    walk(payload)
    return items

def parse_json_payload(raw: str) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

def candidate_api_urls_from_network(network_requests: Optional[List[Dict[str, Any]]], max_urls: int = 5) -> List[str]:
    """Pick promising XHR/fetch URLs that likely carry menu JSON."""
    if not network_requests:
        return []
    
    urls: List[str] = []
    for req in network_requests:
        if not isinstance(req, dict):
            continue
        resource = (req.get("resource_type") or "").lower()
        if resource not in {"xhr", "fetch", "api", "document"}:
            continue
        url = req.get("url") or ""
        if not url:
            continue
        lurl = url.lower()
        if any(bad in lurl for bad in [".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".svg"]):
            continue
        if any(k in lurl for k in ["menu", "menus", "food", "order", "dining", "api/menu", "restaurant"]):
            urls.append(url)
        elif "application/json" in json.dumps(req.get("headers") or {}).lower():
            urls.append(url)
    
    # Deduplicate while preserving order
    seen: Set[str] = set()
    deduped = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
        if len(deduped) >= max_urls:
            break
    return deduped

async def extract_menu_from_network_requests(
    crawler: AsyncWebCrawler,
    network_requests: Optional[List[Dict[str, Any]]],
    max_api_calls: int = 3
) -> List[Dict[str, Any]]:
    """Follow captured XHR/fetch calls and mine JSON for menu items."""
    api_urls = candidate_api_urls_from_network(network_requests, max_urls=max_api_calls)
    if not api_urls:
        return []
    
    items: List[Dict[str, Any]] = []
    api_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        scan_full_page=False,
        page_timeout=20000,
        wait_for=None,
        stream=False,
        css_selector=None,
        excluded_tags=["script", "style"],
    )
    
    for api_url in api_urls:
        try:
            api_result = await run_with_retry(lambda: crawler.arun(url=api_url, config=api_cfg), retries=2, delay=2)
            if not api_result.success:
                logger.warning(f"API follow-up failed for {api_url}: {api_result.error_message}")
                continue
            
            body = getattr(api_result, "html_content", None) or getattr(api_result, "cleaned_html", None)
            if not body and getattr(api_result, "markdown", None):
                body = api_result.markdown.raw_markdown
            payload = parse_json_payload(body or "")
            if not payload:
                continue
            items.extend(extract_items_from_structured_payload(payload))
        except Exception as e:
            logger.warning(f"Failed to parse API response from {api_url}: {e}")
            continue
    
    return items

def dedupe_preserve_order(urls: List[str]) -> List[str]:
    """Deduplicate while preserving order."""
    seen = set()
    out: List[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ===========================
# Async Helpers
# ===========================
async def run_with_retry(coro_fn, retries=3, delay=3, backoff=2):
    for i in range(retries):
        try:
            return await coro_fn()
        except Exception as e:
            if i == retries - 1:
                raise
            wait = delay * (backoff ** i) + random.uniform(0, 1)
            logger.warning(f"Retry {i+1}/{retries} after {wait:.1f}s due to {e}")
            await asyncio.sleep(wait)

async def throttle_if_overloaded(max_cpu=85, max_mem=85):
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory().percent
    if cpu > max_cpu or mem > max_mem:
        sleep_time = min(15, 5 + (cpu - max_cpu) * 0.1)
        logger.warning(f"System load: CPU={cpu}%, MEM={mem}%. Pausing {sleep_time:.1f}s")
        await asyncio.sleep(sleep_time)

@sync_to_async
def record_menu_snapshot(restaurant, url, html, json_data=None, method="llm"):
    from gastronet.models import MenuSnapshot
    h = hashlib.sha256((html or "").encode("utf-8")).hexdigest()
    return MenuSnapshot.objects.create(
        restaurant=restaurant,
        source_url=url,
        text=(html or "")[:50000],  # Increased storage
        hash=h,
        parsed_json=json_data or {},
        render_method=method,
    )

@sync_to_async
def create_menu_attempt(restaurant, url, source="discovery", status=None):
    from gastronet.models import MenuAttempt
    return MenuAttempt.objects.create(
        restaurant=restaurant,
        tried_url=url,
        source=source,
        status=status or "started",
    )

@sync_to_async
def update_crawl_log(log_obj, success=False, skipped=False, errored=False, api_calls=0, cost=0.0):
    if success:
        log_obj.success_count += 1
    if skipped:
        log_obj.skip_count += 1
    if errored:
        log_obj.error_count += 1
    log_obj.api_calls += api_calls
    log_obj.est_cost_usd += cost
    log_obj.save(update_fields=["success_count","skip_count","error_count","api_calls","est_cost_usd"])

def estimate_cost(data, model="gpt-4o-mini"):
    raw = json.dumps(data or {})
    tokens = len(raw) / 4
    pricing = {
        "gpt-4o-mini": 0.00015,
        "gpt-4o": 0.005,
        "deepseek-chat": 0.0001
    }
    rate = pricing.get(model, 0.0002)
    return (tokens / 1000) * rate

@sync_to_async
def should_reextract(restaurant, days=90):
    """Retained for backward compat; now always re-extract in process_restaurant."""
    return True

@sync_to_async
def urls_needing_refresh(restaurant, urls: List[str], days: int = 90) -> List[str]:
    """
    Return URLs that are missing or stale snapshots. If all URLs are fresh, returns [].
    """
    from gastronet.models import MenuSnapshot
    cutoff = timezone.now() - timedelta(days=days)
    existing = (
        MenuSnapshot.objects.filter(restaurant=restaurant, source_url__in=urls, fetched_at__gte=cutoff)
        .values_list("source_url", flat=True)
    )
    fresh = set(normalize_url(u) for u in existing)
    missing = [u for u in urls if normalize_url(u) not in fresh]
    return missing


# ===========================
# Crawl4AI Configs
# ===========================
def build_menu_llm_config(model_name: str = "gpt-4o-mini") -> LLMConfig:
    """Build LLM configuration for menu extraction."""
    if "deepseek" in model_name.lower():
        provider = f"deepseek/{model_name}"
        api_key = os.getenv("DEEPSEEK_API_KEY")
    else:
        provider = f"openai/{model_name}"
        api_key = os.getenv("OPENAI_API_KEY")
    
    return LLMConfig(provider=provider, api_token=api_key)

def build_discovery_config() -> CrawlerRunConfig:
    """Configuration optimized for link discovery."""
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=30000,
        wait_for="css:body",
        scan_full_page=False,  # Faster for discovery
        max_scroll_steps=3,  # Minimal scrolling
        stream=False,
        css_selector=None,
        excluded_tags=["script", "style"],  # Minimal cleanup for discovery
        magic=True,
    )

def build_simple_extraction_config(model_name: str = "gpt-4o-mini") -> CrawlerRunConfig:
    """Simplified extraction config for very large pages - single pass, no chunking."""
    llm_strategy = LLMExtractionStrategy(
        llm_config=build_menu_llm_config(model_name=model_name),
        schema=MenuSchema.model_json_schema(),
        extraction_type="schema",
        input_format="markdown",
        instruction=(
            "Extract menu items: name, price_text, description, section. "
            "Return JSON: {'items': [...]}. Extract all items you see."
        ),
        temperature=0.0,
        chunk_token_threshold=50000,  # Large single chunk
        overlap_rate=0.0,
        apply_chunking=False,  # No chunking
        verbose=False,
    )
    
    return CrawlerRunConfig(
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS,
        scan_full_page=False,  # Minimal rendering
        max_scroll_steps=5,
        page_timeout=45000,
        wait_for="css:body",
        stream=False,
        css_selector="#menu, .menu, [class*='menu'], main",
        excluded_tags=["script", "style", "nav", "footer", "header", "form", "iframe", "svg"],
        remove_overlay_elements=True,
        capture_network_requests=True,
    )

def build_pdf_menu_extraction_config(model_name: str = "gpt-4o-mini") -> CrawlerRunConfig:
    """PDF-aware configuration: scrape PDF then run menu schema extraction."""
    llm_strategy = LLMExtractionStrategy(
        llm_config=build_menu_llm_config(model_name=model_name),
        schema=MenuSchema.model_json_schema(),
        extraction_type="schema",
        input_format="markdown",
        instruction=(
            "Extract menu items from this PDF text: name, price_text, description, section, dietary_tags. "
            "Return JSON with an 'items' array."
        ),
        temperature=0.0,
        chunk_token_threshold=12000,
        overlap_rate=0.1,
        apply_chunking=True,
        verbose=False,
    )
    return CrawlerRunConfig(
        scraping_strategy=PDFContentScrapingStrategy(),
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS,
        scan_full_page=False,
        max_scroll_steps=0,
        page_timeout=60000,
        wait_for=None,
        stream=False,
        excluded_tags=["script", "style"],
        capture_network_requests=True,
    )

def build_menu_extraction_config(
    model_name: str = "gpt-4o-mini",
    use_css_selector: bool = False,
    js_actions: Optional[List[str]] = None,
    capture_network: bool = True
) -> CrawlerRunConfig:
    """Configuration optimized for menu content extraction."""
    llm_strategy = LLMExtractionStrategy(
        llm_config=build_menu_llm_config(model_name=model_name),
        schema=MenuSchema.model_json_schema(),
        extraction_type="schema",
        input_format="markdown",
        instruction=(
            "You are extracting menu items from a restaurant website. "
            "Find ALL food and drink items with their prices. "
            "For each item extract: name (required), description (if available), "
            "price_text (as shown, e.g. '$12.99'), section (category like 'Appetizers'), "
            "and dietary_tags (like 'vegan', 'gluten-free'). "
            "Return JSON with 'items' array. Ignore ads, headers, and footers. "
            "Be thorough - extract every menu item you find."
        ),
        temperature=0.1,
        chunk_token_threshold=8000,  # Reduced from 3000
        overlap_rate=0.1,  # Reduced overlap
        apply_chunking=True,
        verbose=True,
    )
    
    # Try to target menu content with CSS selector
    css_selector = None
    if use_css_selector:
        css_selector = "#menu, .menu, [class*='menu'], [id*='menu'], main, article"
    
    return CrawlerRunConfig(
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS,
        scan_full_page=True,
        max_scroll_steps=20,  # Reduced from 30
        page_timeout=60000,  # Reduced timeout
        wait_for="css:body",
        stream=False,
        css_selector=css_selector,
        # Add content filtering
        excluded_tags=["script", "style", "nav", "footer", "header", "form", "iframe"],
        remove_overlay_elements=True,
        js_code=js_actions or default_menu_js_actions(),
        capture_network_requests=capture_network,
        magic=True,
        simulate_user=True,
    )


# ===========================
# Enhanced Discovery
# ===========================
async def discover_menu_urls(crawler: AsyncWebCrawler, base_url: str, max_links: int = 10) -> List[str]:
    """Enhanced menu URL discovery with scoring."""
    logger.info(f"🔍 Discovering menu links from {base_url}")
    
    candidate_urls = set()
    candidate_urls.add(normalize_url(base_url))  # Always try homepage
    
    try:
        discovery_cfg = build_discovery_config()
        result = await run_with_retry(
            lambda: crawler.arun(url=base_url, config=discovery_cfg)
        )
        
        if not result.success:
            logger.warning(f"Discovery failed for {base_url}: {result.error_message}")
            return list(candidate_urls)
        
        # Extract and score all internal links
        scored_links = []
        internal_links = result.links.get("internal", [])
        external_links = result.links.get("external", [])
        
        logger.info(f"Found {len(internal_links)} internal links, {len(external_links)} external links")
        
        for link in internal_links + external_links:
            href = link.get("href", "")
            text = link.get("text", "")
            
            if not href:
                continue
            
            abs_url = normalize_url(make_abs(base_url, href))
            
            # Skip if already added or same domain check fails
            if abs_url in candidate_urls:
                continue
            
            # Check if it looks like a menu link
            if looks_like_menu_link(text, href):
                score = 10  # Base score for keyword match
                
                # Boost score for specific patterns
                if "menu" in href.lower():
                    score += 5
                if any(word in text.lower() for word in ["full menu", "view menu", "our menu"]):
                    score += 5
                if href.endswith(".pdf"):
                    score += 3
                
                scored_links.append((abs_url, score, text))
                logger.info(f"  ✓ Menu link found (score={score}): {text[:50]} -> {abs_url}")
        
        # Sort by score and add top candidates
        scored_links.sort(key=lambda x: x[1], reverse=True)
        for url, score, text in scored_links[:max_links]:
            candidate_urls.add(url)
        
        # Crawl menu-like pages to harvest nested/tab links (second-hop discovery)
        second_hop_sources = [u for u in list(candidate_urls) if "menu" in u.lower() and not u.lower().endswith(PDF_EXTS)]
        for menu_page in second_hop_sources:
            try:
                nested_result = await run_with_retry(
                    lambda: crawler.arun(url=menu_page, config=discovery_cfg)
                )
                if not nested_result.success:
                    continue
                nested_links = nested_result.links.get("internal", [])
                for link in nested_links:
                    href = link.get("href", "")
                    text = link.get("text", "")
                    if not href:
                        continue
                    abs_url = normalize_url(make_abs(menu_page, href))
                    if abs_url in candidate_urls:
                        continue
                    if looks_like_menu_link(text, href):
                        candidate_urls.add(abs_url)
                        logger.info(f"    ↳ Tab/submenu link: {text[:60]} -> {abs_url}")
                        if len(candidate_urls) >= max_links:
                            break
                if len(candidate_urls) >= max_links:
                    break
            except Exception as e:
                logger.debug(f"Second-hop discovery failed for {menu_page}: {e}")
        
        # Common menu URL patterns to try
        parsed = urlparse(base_url)
        common_paths = [
            "/menu", "/menus", "/food", "/dining",
            "/order", "/take-out", "/takeout",
            "/lunch", "/dinner", "/brunch"
        ]
        
        for path in common_paths:
            test_url = normalize_url(f"{parsed.scheme}://{parsed.netloc}{path}")
            if test_url not in candidate_urls and len(candidate_urls) < max_links:
                candidate_urls.add(test_url)
                logger.info(f"  + Adding common path: {test_url}")
    
    except Exception as e:
        logger.exception(f"Discovery exception for {base_url}: {e}")
    
    final_urls = dedupe_preserve_order(list(candidate_urls))
    logger.info(f"📋 Discovered {len(final_urls)} candidate URLs for menu extraction")
    return final_urls


# ===========================
# Core Extraction
# ===========================
async def process_restaurant(
    crawler: AsyncWebCrawler,
    restaurant: Restaurant,
    model_name: str,
    limit_pages: int,
    skip_discovery: bool = False,
    max_tokens: int = 15000,
    reextract_days: int = 90,
) -> int:
    """Process a single restaurant with enhanced extraction."""
    website = getattr(restaurant, "website", None) or getattr(restaurant, "website_url", None)
    if not website:
        logger.info(f"⊘ Skipping {restaurant.name}: no website")
        return 0
    
    # Normalize website URL
    if not website.startswith(("http://", "https://")):
        website = f"https://{website}"
    
    logger.info(f"\n{'='*60}\n🍽️  Processing: {restaurant.name}\n🌐 Website: {website}\n{'='*60}")
    
    crawl_log = await sync_to_async(CrawlLog.objects.create)(
        task="extract_menus",
        scope=restaurant.name
    )
    
    total_saved = 0
    
    # --- Enhanced Discovery Phase ---
    if skip_discovery:
        candidate_urls = [website]
        logger.info("⏭️  Skipping discovery, using homepage only")
    else:
        candidate_urls = await discover_menu_urls(crawler, website, max_links=limit_pages)
    
    if not candidate_urls:
        logger.warning(f"⚠️  No candidate URLs found for {restaurant.name}")
        candidate_urls = [website]
    
    # Filter out URLs that are already fresh; if all are fresh, skip restaurant
    urls_to_crawl = dedupe_preserve_order(
        await urls_needing_refresh(restaurant, candidate_urls, days=reextract_days)
    )
    if not urls_to_crawl:
        logger.info(f"⏭️  Skipping {restaurant.name}: all candidate URLs have fresh snapshots within {reextract_days} days")
        crawl_log.ended_at = timezone.now()
        await sync_to_async(crawl_log.save)(update_fields=["ended_at"])
        return 0
    
    logger.info(f"📝 Processing {len(urls_to_crawl)} URLs for {restaurant.name} (from {len(candidate_urls)} candidates)")
    
    for idx, url in enumerate(urls_to_crawl, 1):
        logger.info(f"\n--- URL {idx}/{len(urls_to_crawl)}: {url} ---")
        
        attempt = await create_menu_attempt(restaurant, url, source="discovery")
        
        try:
            is_pdf = url.lower().endswith(PDF_EXTS)
            
            result = None
            fetch_result = None
            filtered_html = ""
            
            if is_pdf:
                menu_cfg = build_pdf_menu_extraction_config(model_name)
                result = await run_with_retry(lambda: crawler.arun(url=url, config=menu_cfg))
                filtered_html = getattr(result, "cleaned_html", "") or ""
            else:
                # PHASE 1: FETCH
                # Use config optimized for fetching (JS, Network, Anti-bot)
                fetch_cfg = build_menu_extraction_config(
                    model_name, 
                    use_css_selector=True, 
                    js_actions=default_menu_js_actions(), 
                    capture_network=True
                )
                fetch_cfg.extraction_strategy = None  # Disable extraction for fetch phase
                
                fetch_result = await run_with_retry(lambda: crawler.arun(url=url, config=fetch_cfg))
                
                if not fetch_result.success:
                    result = fetch_result  # Propagate failure
                else:
                    # PHASE 2: CLEAN
                    raw_html = fetch_result.cleaned_html or fetch_result.html or ""
                    filtered_html = aggressive_html_cleanup(raw_html, max_tokens=max_tokens)
                    
                    # PHASE 3: EXTRACT
                    # Use config optimized for extraction (No JS, No Wait, Markdown input)
                    extract_cfg = build_menu_extraction_config(model_name)
                    extract_cfg.js_code = None
                    extract_cfg.wait_for = None
                    extract_cfg.scan_full_page = False
                    extract_cfg.magic = False
                    extract_cfg.simulate_user = False
                    
                    # Pass cleaned HTML via raw:// scheme
                    result = await crawler.arun(url=f"raw://{filtered_html}", config=extract_cfg)
                    
                    # Restore context from fetch
                    result.network_requests = fetch_result.network_requests
                    result.url = url  # Restore original URL for logging/saving

            if not result.success:
                error_msg = result.error_message or "crawl_failed"
                
                # Check if it's a context window error
                if "context" in error_msg.lower() or "token" in error_msg.lower():
                    logger.warning(f"⚠️  Context window exceeded, trying simple extraction...")
                    
                    # Retry with simple extraction (no chunking)
                    try:
                        simple_cfg = build_simple_extraction_config(model_name)
                        if is_pdf:
                            result = await crawler.arun(url=url, config=simple_cfg)
                        else:
                            result = await crawler.arun(url=f"raw://{filtered_html}", config=simple_cfg)
                        
                        if not result.success:
                            raise Exception(f"Simple extraction failed: {result.error_message}")
                        
                        logger.info(f"✓ Simple extraction succeeded")
                    except Exception as e:
                        logger.error(f"❌ Simple extraction failed: {e}")
                        await sync_to_async(attempt.finish)(
                            found=False,
                            parsed=False,
                            status=f"context_error_all_methods_failed: {str(e)[:150]}"
                        )
                        await update_crawl_log(crawl_log, errored=True, api_calls=2)
                        continue
                else:
                    logger.warning(f"❌ Crawl failed: {error_msg}")
                    await sync_to_async(attempt.finish)(
                        found=False,
                        parsed=False,
                        status=error_msg[:255]
                    )
                    await update_crawl_log(crawl_log, errored=True, api_calls=1)
                    continue
            
            # Score the content
            # filtered_html is already set from Phase 2 or PDF result
            content_score = score_menu_content(filtered_html)
            logger.info(f"📊 Content score: {content_score} (after cleanup)")
            
            if content_score < 1:
                logger.info("⚠️  Low menu score – proceeding but results may be noisy")
            
            # Parse extraction results
            try:
                extracted = json.loads(result.extracted_content or "{}")
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from extraction")
                await sync_to_async(attempt.finish)(
                    found=True,
                    parsed=False,
                    status="json_parse_error"
                )
                await update_crawl_log(crawl_log, errored=True, api_calls=1)
                continue
            
            # Handle different response formats
            items = []
            if isinstance(extracted, list):
                items = extracted
            elif isinstance(extracted, dict):
                items = extracted.get("items", [])
            
            # If the main extraction found nothing, try captured XHR/JSON payloads
            if (not items or len(items) == 0) and getattr(result, "network_requests", None):
                xhr_items = await extract_menu_from_network_requests(
                    crawler, getattr(result, "network_requests", None)
                )
                if xhr_items:
                    logger.info(f"📡 Recovered {len(xhr_items)} items from XHR/fetch payloads")
                    items = xhr_items
            
            logger.info(f"📦 Extracted {len(items)} items")
            
            if not items or len(items) == 0:
                # Fallback: if this is an HTML page, look for PDF links to enqueue
                if not is_pdf:
                    pdf_links: List[str] = []
                    try:
                        link_dicts = []
                        if getattr(result, "links", None):
                            link_dicts.extend(result.links.get("internal", []))
                            link_dicts.extend(result.links.get("external", []))
                        if not link_dicts:
                            # As a fallback, re-run a quick discovery on this URL
                            discovery_cfg = build_discovery_config()
                            link_res = await run_with_retry(lambda: crawler.arun(url=url, config=discovery_cfg))
                            if link_res.success and getattr(link_res, "links", None):
                                link_dicts.extend(link_res.links.get("internal", []))
                                link_dicts.extend(link_res.links.get("external", []))
                        for link in link_dicts:
                            href = link.get("href", "")
                            if href and href.lower().endswith(PDF_EXTS):
                                abs_pdf = normalize_url(make_abs(url, href))
                                pdf_links.append(abs_pdf)
                    except Exception as e:
                        logger.debug(f"PDF fallback scanning failed on {url}: {e}")
                    
                    if pdf_links:
                        logger.info(f"📄 Found {len(pdf_links)} PDF links on page; enqueueing for processing")
                        urls_to_crawl = dedupe_preserve_order(urls_to_crawl + pdf_links)
                        await sync_to_async(attempt.finish)(
                            found=True,
                            parsed=False,
                            status="queued_pdf_links"
                        )
                        await update_crawl_log(crawl_log, skipped=True, api_calls=1)
                        continue
                
                logger.info(f"⊘ No items extracted")
                await sync_to_async(attempt.finish)(
                    found=True,
                    parsed=False,
                    status="no_items_extracted"
                )
                await update_crawl_log(crawl_log, skipped=True, api_calls=1)
                continue
            
            # Save items and snapshot
            cost = estimate_cost(extracted, model_name)
            saved = await save_menu_items(restaurant, url, items)
            await record_menu_snapshot(restaurant, url, filtered_html, json_data=extracted)
            
            total_saved += saved
            logger.info(f"✅ Saved {saved} menu items (${cost:.4f})")
            
            await sync_to_async(attempt.finish)(
                found=True,
                parsed=True,
                status="success"
            )
            await update_crawl_log(crawl_log, success=True, api_calls=1, cost=cost)
        
        except Exception as e:
            logger.exception(f"💥 Processing error for {url}: {e}")
            await sync_to_async(attempt.finish)(
                found=True,
                parsed=False,
                status=str(e)[:255]
            )
            await update_crawl_log(crawl_log, errored=True, api_calls=1)
    
    # Finalize log
    crawl_log.ended_at = timezone.now()
    await sync_to_async(crawl_log.save)(update_fields=["ended_at"])
    
    logger.info(f"\n{'='*60}\n✅ Completed {restaurant.name}: {total_saved} total items saved\n{'='*60}\n")
    return total_saved


# ===========================
# Save Items
# ===========================
@sync_to_async
def save_menu_items(restaurant, url, items):
    """Save extracted menu items to database."""
    logger.info(f"💾 Saving {len(items)} items from {url}")
    saved = 0
    # Deduplicate in-memory before DB upserts
    seen_keys = set()
    deduped_items = []
    for item in items:
        name = (item.get("name") or "").strip()
        section = (item.get("section") or "").strip()
        price_text = (item.get("price_text") or "").strip()
        key = (name.lower(), section.lower(), price_text)
        if not name or len(name) < 2:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_items.append(item)
    
    with transaction.atomic():
        for item in deduped_items:
            try:
                name = (item.get("name") or "").strip()
                if not name or len(name) < 2:
                    continue
                
                price_dec = _maybe_money_to_decimal(item.get("price_text"))
                
                obj, created = MenuItem.objects.update_or_create(
                    restaurant=restaurant,
                    source_url=url,
                    name=name[:255],
                    defaults={
                        "description": (item.get("description") or "").strip()[:1000],
                        "price": price_dec,
                        "section": (item.get("section") or "").strip()[:255],
                        "dietary_tags": item.get("dietary_tags") or [],
                        "currency": "USD",
                    },
                )
                saved += 1
                
                if created:
                    logger.debug(f"  + Created: {name}")
                else:
                    logger.debug(f"  ~ Updated: {name}")
            
            except Exception as e:
                logger.error(f"Failed to save item {item.get('name')}: {e}")
                continue
    
    return saved


# ===========================
# Runner
# ===========================
async def runner(
    qs,
    model_name: str,
    limit_pages: int,
    headless: bool,
    skip_discovery: bool,
    reextract_days: int,
    max_tokens: int
):
    """Main async runner for processing all restaurants."""
    browser_cfg = BrowserConfig(
        headless=headless,
        verbose=False,
        extra_args=["--disable-blink-features=AutomationControlled"]
    )
    
    total_saved = 0
    processed = 0
    skipped = 0
    
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for restaurant in qs:
            await throttle_if_overloaded()
            
            try:
                saved = await process_restaurant(
                    crawler=crawler,
                    restaurant=restaurant,
                    model_name=model_name,
                    limit_pages=limit_pages,
                    skip_discovery=skip_discovery,
                    max_tokens=max_tokens,
                    reextract_days=reextract_days,
                )
                total_saved += saved
                if saved == 0:
                    skipped += 1  # treated as skipped due to fresh coverage
                else:
                    processed += 1
                
                # Brief pause between restaurants
                await asyncio.sleep(2)
            
            except Exception as e:
                logger.exception(f"💥 Restaurant failed: {restaurant.name} - {e}")
                continue
    
    return total_saved, processed, skipped


# ===========================
# Django Command
# ===========================
class Command(BaseCommand):
    help = "Extract menu items using Crawl4AI + LLM (Enhanced & Rock Solid)"

    def add_arguments(self, parser):
        parser.add_argument("--model", type=str, default="gpt-4o-mini",
                          help="LLM model to use")
        parser.add_argument("--limit", type=int, default=5,
                          help="Max pages to crawl per restaurant")
        parser.add_argument("--headless", action="store_true", default=True,
                          help="Run browser in headless mode")
        parser.add_argument("--only", type=str, default=None,
                          help="Filter restaurants by name")
        parser.add_argument("--max", type=int, default=200,
                          help="Max number of restaurants to process")
        parser.add_argument("--skip-discovery", action="store_true",
                          help="Skip link discovery, use homepage only")
        parser.add_argument("--reextract-days", type=int, default=90,
                          help="Re-extract if last snapshot older than N days")
        parser.add_argument("--max-tokens", type=int, default=15000,
                          help="Max tokens for HTML cleanup (default: 15000)")
        parser.add_argument("--id", type=int, default=None,
                          help="Process a single restaurant by ID (overrides --only)")

    def handle(self, *args, **opts):
        model_name = opts["model"]
        limit_pages = max(1, opts["limit"])
        headless = opts["headless"]
        name_filter = opts["only"]
        id_filter = opts["id"]
        max_count = opts["max"]
        skip_discovery = opts["skip_discovery"]
        reextract_days = opts["reextract_days"]
        max_tokens = opts["max_tokens"]

        # Build queryset
        qs = Restaurant.objects.all().order_by("id")
        if id_filter:
            qs = qs.filter(id=id_filter)
        elif name_filter:
            qs = qs.filter(name__icontains=name_filter)
        qs = qs[:max_count]
        restaurants = list(qs)

        self.stdout.write(
            self.style.NOTICE(
                f"\n{'='*60}\n"
                f"🚀 Menu Extraction Started\n"
                f"{'='*60}\n"
                f"Restaurants: {len(restaurants)}\n"
                f"Model: {model_name}\n"
                f"Max pages/restaurant: {limit_pages}\n"
                f"Skip discovery: {skip_discovery}\n"
                f"Re-extract after: {reextract_days} days\n"
                f"{'='*60}\n"
            )
        )

        start = time.time()
        
        saved, processed, skipped = asyncio.run(
            runner(
                restaurants,
                model_name,
                limit_pages,
                headless,
                skip_discovery,
                reextract_days,
                max_tokens,
            )
        )

        elapsed = time.time() - start
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"✅ Extraction Complete!\n"
                f"{'='*60}\n"
                f"Total items saved: {saved}\n"
                f"Restaurants processed: {processed}\n"
                f"Restaurants skipped: {skipped}\n"
                f"Time elapsed: {elapsed:.1f}s\n"
                f"{'='*60}\n"
            )
        )
