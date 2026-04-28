import re
from html import unescape
from typing import Dict, List

from bs4 import Tag

_INLINE_WS_RE = re.compile(r"\s+")


def normalize_inline_text(text: str) -> str:
    if not text:
        return ""
    normalized = unescape(text).replace("\xa0", " ")
    return _INLINE_WS_RE.sub(" ", normalized).strip()


def normalize_multiline_text(text: str) -> str:
    if not text:
        return ""
    lines = [normalize_inline_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def extract_table_rows(table: Tag) -> List[Dict[str, List[str]]]:
    rows: List[Dict[str, List[str]]] = []
    for tr in table.find_all("tr"):
        cells = [normalize_inline_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append({"cells": cells})
    return rows
