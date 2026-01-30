# yourapp/management/commands/build_law_embeddings.py
import hashlib
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.db import transaction

from openai import OpenAI

from legal_code.models import LawSection, LawSectionChunk, Jurisdiction


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chunk_text(text: str, max_chars: int = 3200, overlap: int = 200) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, buf = [], ""

    for p in parts:
        if len(buf) + len(p) + 1 <= max_chars:
            buf = f"{buf}\n{p}".strip()
        else:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = f"{tail}\n{p}".strip()

    if buf:
        chunks.append(buf)
    return chunks


class Command(BaseCommand):
    help = "Chunk LawSection content and store embeddings in pgvector."

    def add_arguments(self, parser):
        parser.add_argument("--jurisdiction", type=str, default=None, help="Jurisdiction name filter (exact match).")
        parser.add_argument("--limit", type=int, default=0, help="Limit sections processed (0 = all).")
        parser.add_argument("--model", type=str, default="text-embedding-3-small")
        parser.add_argument("--batch-size", type=int, default=64)
        parser.add_argument("--rebuild", action="store_true", help="Re-embed even if content_hash matches.")
        parser.add_argument("--max-chars", type=int, default=3200)
        parser.add_argument("--overlap", type=int, default=200)

    def handle(self, *args, **opts):
        client = OpenAI()
        emb_model = opts["model"]
        batch_size = opts["batch_size"]

        qs = LawSection.objects.select_related(
            "chapter__document__jurisdiction",
            "chapter__document",
            "chapter",
        ).order_by("id")

        if opts["jurisdiction"]:
            qs = qs.filter(chapter__document__jurisdiction__name=opts["jurisdiction"])

        if opts["limit"]:
            qs = qs[: opts["limit"]]

        total_sections = 0
        to_embed = []  # list[(chunk_id, text)]

        with transaction.atomic():
            for s in qs.iterator(chunk_size=200):
                total_sections += 1
                j = s.chapter.document.jurisdiction

                chunks = chunk_text(s.content, max_chars=opts["max_chars"], overlap=opts["overlap"])
                if not chunks:
                    continue

                for idx, txt in enumerate(chunks):
                    # hash includes section content_hash so updates propagate even if chunking stays same
                    h = sha256(f"{s.content_hash}:{idx}:{txt}")

                    obj, created = LawSectionChunk.objects.update_or_create(
                        section=s,
                        chunk_index=idx,
                        embedding_model=emb_model,
                        defaults={
                            "jurisdiction": j,
                            "law_section_ref": s.section_id,
                            "heading": s.heading or "",
                            "source_url": s.source_url,
                            "content": txt,
                            "content_hash": h,
                        },
                    )

                    needs_embed = opts["rebuild"] or created or (obj.embedding is None) or (obj.content_hash != h)
                    if needs_embed:
                        to_embed.append((obj.id, txt))

        self.stdout.write(f"Prepared {len(to_embed)} chunks for embedding across {total_sections} sections.")

        # Embed in batches, then write back
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            ids = [cid for cid, _ in batch]
            texts = [t for _, t in batch]

            resp = client.embeddings.create(model=emb_model, input=texts)
            vectors = [d.embedding for d in resp.data]

            now = datetime.now(timezone.utc)
            with transaction.atomic():
                for cid, vec in zip(ids, vectors):
                    LawSectionChunk.objects.filter(id=cid).update(embedding=vec, embedded_at=now)

            self.stdout.write(f"Embedded {min(i+batch_size, len(to_embed))}/{len(to_embed)}")
