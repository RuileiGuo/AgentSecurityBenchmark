import re
import unicodedata
from typing import Any

from config import ACCOUNT_RE, EMAIL_RE, URL_RE, WHITESPACE_RE, ZERO_WIDTH_RE


def normalize_external_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def split_text_into_spans(text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    spans: list[str] = []
    for block in blocks:
        pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", block) if piece.strip()]
        if not pieces:
            continue
        if len(pieces) == 1 and len(pieces[0]) <= 280:
            spans.append(pieces[0])
        else:
            spans.extend(pieces)
    return spans or ([text] if text else [])


def extract_entities(text: str) -> list[str]:
    entities = set(EMAIL_RE.findall(text))
    entities.update(URL_RE.findall(text))
    entities.update(ACCOUNT_RE.findall(text))
    return sorted(entities)


def iter_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(iter_string_values(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(iter_string_values(item))
        return strings
    return []
