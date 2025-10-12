"""
Centralized helpers for embedding, retrieval, and LLM calls.

This module wraps:
  • Loading environment variables via python-dotenv.
  • Lazy initialization of the SentenceTransformer embedder used across the app.
  • Convenience helpers for running pgvector similarity search on the assessor table.
  • A single OpenAI Responses client for generating answers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Sequence

from django.conf import settings
from django.db.models import QuerySet
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        """Fallback no-op if python-dotenv is not installed."""
        return False

try:
    from openai import OpenAI, OpenAIError
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

    class OpenAIError(Exception):  # type: ignore
        """Fallback error so callers can catch a consistent base class."""

        pass

from pgvector.django import L2Distance
try:
    from sentence_transformers import SentenceTransformer
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore

from .models import Assessor

# Load environment variables once when Django starts.
load_dotenv()


@dataclass
class RetrievedParcel:
    parcel_number: str
    address: str | None
    distance: float
    raw: Assessor

    def to_metadata(self) -> Dict[str, Any]:
        estimate = {
            "parcel_number": self.parcel_number,
            "address": self.address,
            "distance": round(self.distance, 4),
        }
        if getattr(self.raw, "assessed_value", None) is not None:
            estimate["assessed_value"] = float(self.raw.assessed_value)
        if getattr(self.raw, "sale_price", None) is not None:
            estimate["sale_price"] = float(self.raw.sale_price)
        return estimate


class MissingCredentials(OpenAIError):
    """
    Raised when the OpenAI API key has not been configured locally.
    """

    pass


class MissingDependency(OpenAIError):
    """
    Raised when the OpenAI Python client library is unavailable.
    """

    pass


def get_openai_client() -> OpenAI:
    """
    Return a singleton OpenAI client configured with API key from .env or settings.
    """

    if OpenAI is None:
        raise MissingDependency("The openai package is not installed. Install openai>=1.0.0 to enable chat.")

    api_key = (
        os.getenv("OPENAI_API_KEY")
        or getattr(settings, "OPENAI_API_KEY", None)
        or getattr(settings, "OPENAI_API_KEY_FALLBACK", None)
    )
    if not api_key:
        raise MissingCredentials("OPENAI_API_KEY is not configured. Add it to your .env file.")

    return OpenAI(api_key=api_key)


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """
    Lazy-load the sentence transformer used for generating query embeddings.
    """

    if SentenceTransformer is None:
        raise MissingDependency(
            "sentence-transformers is not installed. Install sentence-transformers to enable embeddings."
        )

    model_name = getattr(settings, "EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    return SentenceTransformer(model_name)


def embed_text(text: str) -> List[float]:
    """
    Generate a pgvector-compatible embedding for the provided string.
    """

    model = get_embedder()
    embedding = model.encode([text], normalize_embeddings=True)[0]
    return embedding.tolist()


def build_context_rows(parcels: Sequence[RetrievedParcel]) -> str:
    """
    Render the retrieved parcels into a prompt-friendly textual context block.
    """

    blocks: List[str] = []
    for item in parcels:
        assessor = item.raw
        lines = [
            f"Parcel: {assessor.parcel_number}",
            f"Address: {assessor.address or 'Unknown'}",
        ]
        if assessor.property_type:
            lines.append(f"Property type: {assessor.property_type}")
        if assessor.acres:
            lines.append(f"Acreage: {assessor.acres}")
        if assessor.total_market_value:
            lines.append(f"Total market value: {assessor.total_market_value}")
        if assessor.assessed_value:
            lines.append(f"Assessed value: {assessor.assessed_value}")
        if assessor.sale_price:
            lines.append(f"Latest sale price: {assessor.sale_price}")
        if assessor.sale_date:
            lines.append(f"Latest sale date: {assessor.sale_date}")
        if assessor.building_style:
            lines.append(f"Building style: {assessor.building_style}")
        if assessor.bedrooms:
            lines.append(f"Bedrooms: {assessor.bedrooms}")
        if assessor.bathrooms:
            lines.append(f"Bathrooms: {assessor.bathrooms}")
        if assessor.neighborhood_code:
            lines.append(f"Neighborhood: {assessor.neighborhood_code}")
        if assessor.school_district:
            lines.append(f"School district: {assessor.school_district}")

        block = "\n".join(lines)
        blocks.append(block)
    return "\n\n".join(blocks)


def search_similar_parcels(query_vector: Sequence[float], limit: int = 5) -> List[RetrievedParcel]:
    """
    Run a pgvector similarity search against assessor embeddings.
    """

    qs: QuerySet[Assessor] = (
        Assessor.objects.exclude(embedding__isnull=True)
        .annotate(distance=L2Distance("embedding", list(query_vector)))
        .order_by("distance")[:limit]
    )

    return [
        RetrievedParcel(parcel_number=record.parcel_number, address=record.address, distance=record.distance, raw=record)
        for record in qs
    ]


def build_response_input(
    prompt: str,
    context_rows: str,
    history: Iterable[Dict[str, Any]] | None = None,
    system_prompt: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Construct the OpenAI Responses API-compatible conversation payload.
    """

    system_prompt = system_prompt or (
        "You are a parcel intelligence assistant for Skagit County. "
        "Ground every answer in the provided assessor data. "
        "If the context is insufficient, explain what other research is needed."
    )

    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
    ]

    for msg in history or []:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            conversation.append({"role": role, "content": [{"type": "text", "text": content}]})

    fused_prompt = f"Context:\n{context_rows or 'No related parcels found.'}\n\nQuestion:\n{prompt}"
    conversation.append({"role": "user", "content": [{"type": "text", "text": fused_prompt}]})
    return conversation


def generate_rag_response(
    prompt: str,
    *,
    history: Iterable[Dict[str, Any]] | None = None,
    limit: int = 5,
    model: str | None = None,
) -> Dict[str, Any]:
    """
    1. Embed the user prompt.
    2. Retrieve the nearest assessor parcels.
    3. Call OpenAI Responses API with context and history.
    4. Return assistant text plus metadata for UI rendering.
    """

    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    query_vector = embed_text(prompt)
    parcels = search_similar_parcels(query_vector, limit=limit)
    context_rows = build_context_rows(parcels)

    client = get_openai_client()
    model_name = model or getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4.1-mini")

    response = client.responses.create(
        model=model_name,
        input=build_response_input(prompt, context_rows, history=history),
        temperature=0.2,
    )

    answer_text = getattr(response, "output_text", "").strip()

    metadata = [parcel.to_metadata() for parcel in parcels]

    return {
        "answer": answer_text,
        "model": model_name,
        "sources": metadata,
        "context_rows": context_rows,
    }
