"""Helpers for OpenAI Responses authentication."""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

try:
    from openai import OpenAI, OpenAIError
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

    class OpenAIError(Exception):  # type: ignore
        pass

load_dotenv()


def get_openai_client():
    if OpenAI is None:
        raise MissingDependency("The openai package is not installed. Install openai>=1.0.0 to enable the API.")

    api_key = (
        os.getenv("OPENAI_API_KEY")
        or getattr(settings, "OPENAI_API_KEY", None)
        or getattr(settings, "OPENAI_API_KEY_FALLBACK", None)
    )
    if not api_key:
        raise MissingCredentials("OPENAI_API_KEY is not configured. Add it to your .env file.")

    return OpenAI(api_key=api_key)


class MissingCredentials(OpenAIError):
    pass


class MissingDependency(OpenAIError):
    pass


__all__ = [
    "MissingCredentials",
    "MissingDependency",
    "OpenAIError",
    "get_openai_client",
]
