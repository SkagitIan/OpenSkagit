import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import ScrapeSettings
from .errors import BlockedByChallengeError, NavigationError, ScraperTimeoutError

LOGGER = logging.getLogger(__name__)
LOG_CONTEXT_FIELDS = ("jurisdiction", "publisher", "document", "section_id", "url")


def make_log_context(
    *,
    jurisdiction: Optional[str] = None,
    publisher: Optional[str] = None,
    document: Optional[str] = None,
    section_id: Optional[str] = None,
    url: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    if jurisdiction:
        context["jurisdiction"] = jurisdiction
    if publisher:
        context["publisher"] = publisher
    if document:
        context["document"] = document
    if section_id:
        context["section_id"] = section_id
    if url:
        context["url"] = url
    context.update(extra)
    return context


def detect_challenge(html: str, title: str = "") -> bool:
    title_probe = (title or "").strip().lower()
    if title_probe == "just a moment..." or title_probe.startswith("attention required"):
        return True

    body_probe = (html or "")[:12000].lower()
    markers = (
        "/cdn-cgi/challenge-platform/",
        "cf-chl-",
        "challenge-form",
        "turnstile",
        "hcaptcha",
        "g-recaptcha",
    )
    return any(marker in body_probe for marker in markers)


@dataclass(frozen=True)
class BrowserRuntimeConfig:
    headless: bool = True
    slow_mo_ms: int = 0


class PlaywrightClient:
    def __init__(
        self,
        *,
        settings: Optional[ScrapeSettings] = None,
        runtime: Optional[BrowserRuntimeConfig] = None,
    ):
        self.settings = settings or ScrapeSettings()
        self.runtime = runtime or BrowserRuntimeConfig()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._owned_context: Optional[BrowserContext] = None

    def __enter__(self) -> "PlaywrightClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._browser is not None:
            return

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.runtime.headless,
            slow_mo=self.runtime.slow_mo_ms,
        )

    def stop(self) -> None:
        if self._owned_context is not None:
            self._owned_context.close()
            self._owned_context = None

        if self._browser is not None:
            self._browser.close()
            self._browser = None

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def new_context(self, *, user_agent: Optional[str] = None) -> BrowserContext:
        if self._browser is None:
            self.start()
        assert self._browser is not None
        return self._browser.new_context(user_agent=user_agent or self.settings.user_agent)

    def fetch_html(
        self,
        url: str,
        *,
        wait_until: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        context: Optional[BrowserContext] = None,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        active_context = context or self._get_or_create_owned_context()
        max_attempts = max(1, self.settings.max_retries + 1)
        context_payload = log_context or {}
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            page = active_context.new_page()
            try:
                self.navigate(
                    page,
                    url=url,
                    wait_until=wait_until,
                    timeout_ms=timeout_ms,
                    log_context=context_payload,
                )
                return page.content()
            except BlockedByChallengeError:
                raise
            except PlaywrightTimeoutError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise ScraperTimeoutError(
                        f"timed out navigating to {url}",
                        details={"attempts": attempt, **context_payload},
                    ) from exc
                self._sleep_backoff(attempt)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= max_attempts:
                    raise NavigationError(
                        f"failed navigating to {url}",
                        details={"attempts": attempt, "reason": str(exc), **context_payload},
                    ) from exc
                self._sleep_backoff(attempt)
            finally:
                page.close()

        if last_error:
            raise NavigationError(
                f"failed navigating to {url}",
                details={"reason": str(last_error), **context_payload},
            ) from last_error
        raise NavigationError(f"failed navigating to {url}", details=context_payload)

    def request_text(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
        context: Optional[BrowserContext] = None,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        active_context = context or self._get_or_create_owned_context()
        effective_timeout = timeout_ms or self.settings.request_timeout_ms
        payload = log_context or {}

        request = active_context.request
        method_upper = method.upper()
        try:
            response = request.fetch(
                url,
                method=method_upper,
                data=data,
                headers=headers,
                timeout=effective_timeout,
            )
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"timed out requesting {url}",
                details={**payload, "method": method_upper, "url": url},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise NavigationError(
                f"request failed for {url}",
                details={**payload, "method": method_upper, "reason": str(exc)},
            ) from exc

        if not response.ok:
            raise NavigationError(
                f"request_http_{response.status}",
                details={**payload, "method": method_upper, "url": url},
            )
        return response.text()

    def request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
        context: Optional[BrowserContext] = None,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = self.request_text(
            url,
            method=method,
            data=data,
            headers=headers,
            timeout_ms=timeout_ms,
            context=context,
            log_context=log_context,
        )
        try:
            import json

            return json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise NavigationError(
                "request_non_json_response",
                details={**(log_context or {}), "url": url},
            ) from exc

    def navigate(
        self,
        page: Page,
        *,
        url: str,
        wait_until: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = log_context or {}
        effective_wait = wait_until or self.settings.wait_until
        effective_timeout = timeout_ms or self.settings.navigation_timeout_ms

        LOGGER.debug(
            "playwright_navigate",
            extra={"event": "playwright_navigate", **payload, "url": url},
        )
        page.goto(url, wait_until=effective_wait, timeout=effective_timeout)
        page.wait_for_load_state(state="domcontentloaded", timeout=effective_timeout)

        title = page.title()
        html = page.content()
        if detect_challenge(html, title):
            page.wait_for_timeout(self.settings.challenge_wait_ms)
            title = page.title()
            html = page.content()
        if detect_challenge(html, title):
            raise BlockedByChallengeError(
                f"challenge detected at {url}",
                details={**payload, "url": url, "title": title},
            )

    def _get_or_create_owned_context(self) -> BrowserContext:
        if self._owned_context is None:
            self._owned_context = self.new_context()
        return self._owned_context

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.settings.retry_backoff_seconds * attempt
        time.sleep(delay)
