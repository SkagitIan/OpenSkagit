"""Top-level package initialization for the Django project."""

from __future__ import annotations

from django.urls.resolvers import URLResolver


def _urlresolver_debug_name(self) -> str | None:
    """
    Make URLResolver expose a harmless ``name`` attribute so the debug 404
    template can reference it without raising when the pattern is an include.
    """
    return getattr(self, "namespace", None)


if not hasattr(URLResolver, "name"):
    URLResolver.name = property(_urlresolver_debug_name)
