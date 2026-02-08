import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from vanna.integrations.chromadb import ChromaAgentMemory
from vanna.integrations.openai import OpenAILlmService

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

@lru_cache(maxsize=1)
def get_vn():
    llm = OpenAILlmService(
        config={
            "api_key": os.environ["OPENAI_API_KEY"],
            "model": os.environ.get("VANNA_MODEL", "gpt-4o-mini"),
        }
    )
    mem = ChromaAgentMemory(config={"path": os.environ.get("VANNA_CHROMA_PATH", "/var/lib/vanna_chroma")})

    # attach memory -> llm (we'll pick the right method after introspection)
    for method in ("connect", "wrap", "attach"):
        if hasattr(mem, method):
            return getattr(mem, method)(llm)

    return llm
