from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

REQUIRED_ENV_VARS: Tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GOOGLE_PLACES_API_KEY",
    "GENAI_API_KEY",
)

RECOMMENDED_ENV_VARS: Tuple[str, ...] = (
    "OUTSCRAPER_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_ID",
    "REDIS_URL",
)

logger = logging.getLogger("config.bootstrap")


class ConfigError(RuntimeError):
    """Raised when the config bootstrapper cannot validate the environment."""


class MissingEnvError(ConfigError):
    """Raised when a required environment variable is missing."""


_loaded = False


def ensure_config(force_reload: bool = False) -> None:
    """Load dotenv and validate required environment variables exactly once."""
    global _loaded
    if _loaded and not force_reload:
        return

    load_dotenv(ENV_PATH)
    missing = _missing_required()
    if missing:
        raise MissingEnvError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    optional_missing = _missing_optional()
    if optional_missing:
        logger.debug(
            "Optional environment variables not set: %s", ", ".join(optional_missing)
        )

    _log_config_loaded()
    _loaded = True


def _missing_required() -> List[str]:
    return [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]


def _missing_optional() -> List[str]:
    return [name for name in RECOMMENDED_ENV_VARS if not os.getenv(name)]


def _log_config_loaded() -> None:
    message = f"config loaded (env={ENV_PATH})"
    logger.info(message)
    print(message)
