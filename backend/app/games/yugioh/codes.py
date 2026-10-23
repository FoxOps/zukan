"""Printed Yu-Gi-Oh! set codes ("LOB-EN001") and rarity names, as every source spells them."""

import re

# Printed set code: "LOB-EN001", "SDK-E001", "RA03-FR045", "BE2-JP001", "SR14-KR024".
CODE = re.compile(r"\b([A-Z0-9]{2,5})-([A-Z]{1,2})?([A-Z]?[0-9]{3})\b")
REGIONS = {
    "EN": "en",
    "E": "en",
    "FR": "fr",
    "F": "fr",
    "DE": "de",
    "G": "de",
    "IT": "it",
    "I": "it",
    "PT": "pt",
    "P": "pt",
    "SP": "es",
    "S": "es",
    "JP": "ja",
    "KR": "ko",
    "K": "ko",
    "SC": "zh-hans",
    "TC": "zh-hant",
    "AE": "en",
}
ASIAN_REGIONS = {"JP", "KR", "K", "SC", "TC"}
# Printed regions of the OCG game: Asian languages and Asian English ("AE").
OCG_REGIONS = ASIAN_REGIONS | {"AE"}


def tag(rarity: str | None) -> str:
    """Rarity part of a printing id: "Ultra Rare" -> "ultrarare"."""
    return re.sub(r"[^a-z0-9]", "", (rarity or "").casefold()) or "none"


def rarity_key(rarity: str | None) -> str:
    """One key for every spelling of a rarity: YGOPRODeck "Starlight Rare", YGOJSON
    "starlight", typos ("PLatinum Secret Rare") -> "starlight", "platinumsecret"."""
    key = tag(rarity)
    return key[: -len("rare")] if key.endswith("rare") and key != "rare" else key


_SPLIT = re.compile(r"^([A-Z0-9]+)-([A-Z]{2}(?=[A-Z]?[0-9])|[A-Z](?=[0-9]))?(.+)$")


def _split(number: str) -> tuple[str, str, str] | None:
    """Set, region and card part: "YS15-ENL22" -> ("YS15", "EN", "L22")."""
    match = _SPLIT.match(number.strip().upper())
    if match is None:
        return None
    region = match.group(2) or ""
    if region and region not in REGIONS:
        return match.group(1), "", region + match.group(3)
    return match.group(1), region, match.group(3)


def number_key(number: str) -> str:
    """A printed code without its region: "LOB-EN001", "LOB-E001", "LOB-001" -> "LOB-001"."""
    parts = _split(number)
    return f"{parts[0]}-{parts[2]}" if parts else number.strip().upper()


def base_code(number: str) -> str:
    """Set part of a printed code without its region: "BETB-KR024" -> "BETB"."""
    return number.split("-", 1)[0].strip().upper()


def region_of(number: str) -> str:
    """Region letters of a printed code: "BETB-KR024" -> "KR", "LOB-001" -> ""."""
    parts = _split(number)
    return parts[1] if parts else ""


def prefix_of(number: str) -> str:
    """Set part of a printed code: "YAC1-JP071" -> "YAC1-JP"."""
    return number.rstrip("0123456789") or number
