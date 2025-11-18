from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, Iterable, Iterator, List, Optional
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from . import llm
from .llm import MissingCredentials, MissingDependency, OpenAIError

logger = logging.getLogger(__name__)

CHAT_SESSION_KEY = "rag_conversations"
CHAT_ACTIVE_KEY = "rag_active_conversation"


def _timestamp() -> float:
    return timezone.now().timestamp()


def _create_conversation_record() -> Dict[str, Any]:
    now_ts = _timestamp()
    return {
        "title": "New conversation",
        "created_ts": now_ts,
        "updated_ts": now_ts,
        "messages": [],
    }


class ConversationManager:
    """
    Lightweight session-backed conversation store shared across templates and widgets.
    """

    def __init__(self, request) -> None:
        self.request = request

    @property
    def active_id(self) -> Optional[str]:
        cid = self.request.session.get(CHAT_ACTIVE_KEY)
        store = self._store()
        if cid and cid in store:
            return cid
        return None

    def _store(self) -> Dict[str, Any]:
        store = self.request.session.get(CHAT_SESSION_KEY)
        if not isinstance(store, dict):
            store = {}
            self.request.session[CHAT_SESSION_KEY] = store
            self.request.session.modified = True
        return store

    def _persist(self) -> None:
        self.request.session.modified = True

    def ensure(self, conversation_id: Optional[str] = None) -> str:
        """
        Return an existing conversation id, creating one if needed.
        """

        store = self._store()
        cid = conversation_id
        if cid and cid in store:
            self._set_active(cid)
            return cid

        if cid and cid not in store:
            cid = None

        if cid is None:
            active = self.active_id
            if active:
                return active
            if store:
                cid = max(store.items(), key=lambda item: item[1].get("updated_ts", 0))[0]
            else:
                cid = self.new()
        self._set_active(cid)
        return cid

    def new(self) -> str:
        """
        Create a new empty conversation and set it active.
        """

        store = self._store()
        conversation_id = uuid4().hex
        store[conversation_id] = _create_conversation_record()
        self.request.session[CHAT_SESSION_KEY] = store
        self._set_active(conversation_id)
        return conversation_id

    def _set_active(self, conversation_id: str) -> None:
        self.request.session[CHAT_ACTIVE_KEY] = conversation_id
        self._persist()

    def _get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        store = self._store()
        conversation = store.get(conversation_id)
        if conversation is None:
            conversation = _create_conversation_record()
            store[conversation_id] = conversation
            self.request.session[CHAT_SESSION_KEY] = store
        return conversation

    def list_conversations(self) -> List[Dict[str, Any]]:
        store = self._store()
        conversations: List[Dict[str, Any]] = []
        for cid, data in store.items():
            title = (data.get("title") or "").strip() or "New conversation"
            if len(title) > 60:
                title = f"{title[:57]}…"
            conversations.append(
                {
                    "id": cid,
                    "title": title,
                    "updated_ts": data.get("updated_ts") or data.get("created_ts") or 0,
                }
            )
        conversations.sort(key=lambda item: item["updated_ts"], reverse=True)
        return conversations

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        conversation = self._get_conversation(conversation_id)
        messages = conversation.get("messages") or []
        return [copy.deepcopy(message) for message in messages]

    def model_history(self, conversation_id: str) -> List[Dict[str, str]]:
        conversation = self._get_conversation(conversation_id)
        history: List[Dict[str, str]] = []
        for message in conversation.get("messages", []):
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content})
        return history

    def _update_title(self, conversation: Dict[str, Any], prompt: str) -> None:
        current_title = (conversation.get("title") or "").strip()
        if not current_title or current_title.startswith("New conversation"):
            trimmed = prompt.strip()[:60]
            conversation["title"] = f"{trimmed}…" if len(prompt.strip()) > 60 else (trimmed or "New conversation")

    def append_user_message(self, conversation_id: str, prompt: str) -> Dict[str, Any]:
        conversation = self._get_conversation(conversation_id)
        message = {"role": "user", "content": prompt}
        conversation.setdefault("messages", []).append(message)
        conversation["updated_ts"] = _timestamp()
        self._update_title(conversation, prompt)
        self._persist()
        return copy.deepcopy(message)

    def append_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        sources: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        conversation = self._get_conversation(conversation_id)
        message = {
            "role": "assistant",
            "content": content,
        }
        if sources:
            message["sources"] = sources
        if model:
            message["model"] = model
        conversation.setdefault("messages", []).append(message)
        conversation["updated_ts"] = _timestamp()
        self._persist()
        return copy.deepcopy(message)

    def bootstrap(self, conversation_id: str, *, initial_prompt: str | None = None) -> Dict[str, Any]:
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
        self.model_name = model or getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4.1-mini")
        self.sources: List[Dict[str, Any]] = []
        self.full_text: str = ""

    def _stream_events(self) -> Iterator[str]:
        query_vector = llm.embed_text(self.prompt)
        parcels = llm.search_similar_parcels(query_vector, limit=5)
        self.sources = [parcel.to_metadata() for parcel in parcels]
        context_rows = llm.build_context_rows(parcels)

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
    "CHAT_ACTIVE_KEY",
    "CHAT_SESSION_KEY",
    "ConversationManager",
    "MissingCredentials",
    "MissingDependency",
    "OpenAIError",
    "StreamingCompletion",
    "render_stream_event",
]
