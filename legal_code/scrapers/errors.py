from typing import Any, Dict, Optional


class ScraperError(RuntimeError):
    default_code = "scraper_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code or self.default_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": self.code, "message": str(self)}
        if self.details:
            payload["details"] = self.details
        return payload


class NavigationError(ScraperError):
    default_code = "navigation_error"


class ScraperTimeoutError(ScraperError):
    default_code = "scraper_timeout"


class BlockedByChallengeError(ScraperError):
    default_code = "blocked_by_challenge"


class ParseError(ScraperError):
    default_code = "parse_error"
