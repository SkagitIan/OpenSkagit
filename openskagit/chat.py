from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, Iterable, Iterator, List, Optional
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from . import llm
from .llm import MissingCredentials, MissingDependency, OpenAIError
from .models import Conversation, ConversationMessage

logger = logging.getLogger(__name__)


def _create_conversation(session_key: Optional[str] = None, title: str = "New conversation") -> Conversation:
    """Create a new conversation in the database."""
    return Conversation.objects.create(
        session_key=session_key,
        title=title
    )


class ConversationManager:
    """
    Database-backed conversation manager that replaces session storage.
    """

    def __init__(self, request) -> None:
        self.request = request
        self.session_key = request.session.session_key or ""

    def _get_active_conversation_id(self) -> Optional[str]:
        """Get the active conversation ID from session."""
        return self.request.session.get("active_conversation_id")

    def _set_active_conversation_id(self, conversation_id: str) -> None:
        """Set the active conversation ID in session."""
        self.request.session["active_conversation_id"] = conversation_id
        self.request.session.modified = True

    @property
    def active_id(self) -> Optional[str]:
        """Return the currently active conversation ID if it exists."""
        cid = self._get_active_conversation_id()
        if cid:
            try:
                UUID(cid)
                if Conversation.objects.filter(id=cid).exists():
                    return cid
            except (ValueError, AttributeError):
                pass
        return None

    def ensure(self, conversation_id: Optional[str] = None) -> str:
        """
        Return an existing conversation id, creating one if needed.
        """
        if conversation_id:
            try:
                UUID(conversation_id)
                if Conversation.objects.filter(id=conversation_id).exists():
                    self._set_active_conversation_id(conversation_id)
                    return conversation_id
            except (ValueError, AttributeError):
                pass

        active = self.active_id
        if active:
            return active

        most_recent = (
            Conversation.objects.filter(session_key=self.session_key)
            .order_by("-updated_at")
            .first()
        )

        if most_recent:
            cid = str(most_recent.id)
        else:
            cid = self.new()

        self._set_active_conversation_id(cid)
        return cid

    def new(self) -> str:
        """
        Create a new empty conversation and set it active.
        """
        conversation = _create_conversation(session_key=self.session_key)
        cid = str(conversation.id)
        self._set_active_conversation_id(cid)
        return cid

    def _get_conversation(self, conversation_id: str) -> Conversation:
        """Get or create a conversation by ID."""
        try:
            UUID(conversation_id)
            conversation = Conversation.objects.get(id=conversation_id)
        except (ValueError, Conversation.DoesNotExist):
            conversation = _create_conversation(session_key=self.session_key)
            self._set_active_conversation_id(str(conversation.id))

        return conversation

    def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations for the current session."""
        conversations_qs = (
            Conversation.objects.filter(session_key=self.session_key)
            .order_by("-updated_at")[:50]
        )

        conversations: List[Dict[str, Any]] = []
        for conv in conversations_qs:
            title = (conv.title or "").strip() or "New conversation"
            if len(title) > 60:
                title = f"{title[:57]}…"
            conversations.append(
                {
                    "id": str(conv.id),
                    "title": title,
                    "updated_ts": conv.updated_at.timestamp(),
                }
            )
        return conversations

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a conversation."""
        conversation = self._get_conversation(conversation_id)
        messages = conversation.messages.all()

        result = []
        for msg in messages:
            result.append({
                "role": msg.role,
                "content": msg.content,
                "sources": msg.sources or [],
                "model": msg.model,
            })
        return result

    def model_history(self, conversation_id: str) -> List[Dict[str, str]]:
        """Get conversation history formatted for OpenAI."""
        conversation = self._get_conversation(conversation_id)
        messages = conversation.messages.filter(role__in=["user", "assistant"])

        history: List[Dict[str, str]] = []
        for msg in messages:
            content = (msg.content or "").strip()
            if content:
                history.append({"role": msg.role, "content": content})
        return history

    def _update_title(self, conversation: Conversation, prompt: str) -> None:
        """Update conversation title based on the first user message."""
        if not conversation.messages.exists() or conversation.title == "New conversation":
            trimmed = prompt.strip()[:60]
            conversation.title = f"{trimmed}…" if len(prompt.strip()) > 60 else (trimmed or "New conversation")
            conversation.save(update_fields=["title", "updated_at"])

    def append_user_message(self, conversation_id: str, prompt: str) -> Dict[str, Any]:
        """Append a user message to the conversation."""
        conversation = self._get_conversation(conversation_id)

        message = ConversationMessage.objects.create(
            conversation=conversation,
            role="user",
            content=prompt
        )

        self._update_title(conversation, prompt)
        conversation.save(update_fields=["updated_at"])

        return {
            "role": message.role,
            "content": message.content,
        }

    def append_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        sources: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append an assistant message to the conversation."""
        conversation = self._get_conversation(conversation_id)

        message = ConversationMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=content,
            sources=sources or [],
            model=model
        )

        conversation.save(update_fields=["updated_at"])

        return {
            "role": message.role,
            "content": message.content,
            "sources": message.sources,
            "model": message.model,
        }

    def bootstrap(self, conversation_id: str, *, initial_prompt: str | None = None) -> Dict[str, Any]:
        """Bootstrap conversation data for templates."""
        return {
            "conversation_id": conversation_id,
            "messages": self.get_messages(conversation_id),
            "conversations": self.list_conversations(),
            "initial_prompt": (initial_prompt or "").strip(),
        }


class StreamingCompletion:
    """
    Helper to stream OpenAI Responses output chunk-by-chunk.
    """

    def __init__(
        self,
        prompt: str,
        *,
        history: Iterable[Dict[str, Any]] | None = None,
        model: Optional[str] = None,
    ) -> None:
        self.prompt = prompt
        self.history = list(history or [])
        self.model_name = model or getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")
        self.sources: List[Dict[str, Any]] = []
        self.full_text: str = ""

    def _stream_events(self) -> Iterator[str]:
        parcels: List[llm.RetrievedParcel] = []
        context_rows = ""
        try:
            query_vector = llm.embed_text(self.prompt)
            parcels = llm.search_similar_parcels(query_vector, limit=5)
            self.sources = [parcel.to_metadata() for parcel in parcels]
            context_rows = llm.build_context_rows(parcels)
        except MissingDependency as exc:
            self.sources = []
            logger.warning(
                "Embedding model unavailable for streaming responses; continuing without retrieval context: %s",
                exc,
            )

        client = llm.get_openai_client()
        stream_manager = client.responses.stream(
            model=self.model_name,
            input=llm.build_response_input(self.prompt, context_rows, history=self.history),
            temperature=0.2,
        )

        chunks: List[str] = []
        with stream_manager as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        chunks.append(delta)
                        yield delta
                elif event_type == "error":
                    message = getattr(event, "message", "The model returned an error.")
                    raise OpenAIError(message)
                elif event_type == "response.failed":
                    raise OpenAIError("The model was unable to complete the response.")
            final_response = stream.get_final_response()
        aggregated = "".join(chunks).strip()
        fallback = getattr(final_response, "output_text", "").strip()
        self.full_text = aggregated or fallback

    def stream(self) -> Iterator[str]:
        """
        Yield streamed text deltas from OpenAI Responses.
        """
        yield from self._stream_events()


def render_stream_event(payload: Dict[str, Any]) -> bytes:
    """
    Convert dict payloads to newline-delimited JSON bytes for StreamingHttpResponse.
    """
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


__all__ = [
    "ConversationManager",
    "MissingCredentials",
    "MissingDependency",
    "OpenAIError",
    "StreamingCompletion",
    "render_stream_event",
]
