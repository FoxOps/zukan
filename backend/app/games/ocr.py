"""Helpers shared by game providers to read OCR text from card photos."""

import re
import unicodedata
from functools import cache

from opencc import OpenCC

from app.games.base import OcrLine

_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_CJK = re.compile(r"[一-鿿]")
_THAI = re.compile(r"[\u0e00-\u0e7f]")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def clean(text: str) -> str:
    """Normalize width (full-width digits from Asian cards) and collapse spaces."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def has_cjk(text: str) -> bool:
    """Japanese, Korean or Chinese characters (names without spaces, few trigrams)."""
    return bool(_KANA.search(text) or _HANGUL.search(text) or _CJK.search(text))


def script_language(lines: list[OcrLine]) -> str | None:
    """Language implied by the writing system (Japanese, Korean, Chinese, Thai), if any."""
    text = " ".join(line.text for line in lines)
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _THAI.search(text):
        return "th"
    if _CJK.search(text):
        return chinese_script(text)
    return None


def chinese_script(text: str) -> str:
    """Simplified or Traditional, by majority: characters only Traditional writes
    (Simplified spells them otherwise) against characters only Simplified writes. One
    misread glyph must not turn a mainland card into a Taiwan one; most characters are
    shared by both and count for neither."""
    traditional = sum(
        1 for c, s in zip(text, _converter("t2s").convert(text), strict=False) if c != s
    )
    simplified = sum(
        1 for c, t in zip(text, _converter("s2t").convert(text), strict=False) if c != t
    )
    return "zh-hant" if traditional > simplified else "zh-hans"


@cache
def _converter(config: str) -> OpenCC:
    return OpenCC(config)


def chinese_variants(names: list[str]) -> list[str]:
    """The names, plus their Simplified and Traditional Chinese spellings: a card may be
    printed in either script, OCR models read both, catalogs store one."""
    out = list(names)
    for name in names:
        if not _CJK.search(name) or _KANA.search(name) or _HANGUL.search(name):
            continue
        for config in ("t2s", "s2t"):
            other = _converter(config).convert(name)
            if other not in out:
                out.append(other)
    return out


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
