"""Helpers shared by game providers to read OCR text from card photos."""

import re
import unicodedata

from app.games.base import OcrLine

_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_CJK = re.compile(r"[一-鿿]")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def clean(text: str) -> str:
    """Normalize width (full-width digits from Asian cards) and collapse spaces."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def script_language(lines: list[OcrLine]) -> str | None:
    """Language implied by the writing system (Japanese, Korean, Chinese), if any."""
    text = " ".join(line.text for line in lines)
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _CJK.search(text):
        return "zh-hant" if any(c in text for c in "對與為們這個") else "zh-hans"
    return None


def by_position(lines: list[OcrLine]) -> list[OcrLine]:
    """Lines top to bottom when boxes are known, else in the order received."""
    if lines and all(line.top is not None for line in lines):
        return sorted(lines, key=lambda line: (round(line.top or 0, 2), line.left or 0))
    return list(lines)


def bottom_part(lines: list[OcrLine], fraction: float = 0.25) -> list[OcrLine]:
    """Lines in the bottom of the card (collector info). Without boxes, the last lines,
    at most half of them so a short read still leaves the name."""
    if lines and all(line.top is not None for line in lines):
        return [line for line in lines if (line.top or 0) >= 1 - fraction]
    return lines[len(lines) - min(4, len(lines) // 2) :]


def letter_ratio(text: str) -> float:
    stripped = text.replace(" ", "")
    return len(_LETTERS.findall(stripped)) / len(stripped) if stripped else 0


def strip_number(number: str) -> str:
    """Printed numbers are often zero padded ("0168"); catalogs store "168"."""
    return number.lstrip("0") or "0"
