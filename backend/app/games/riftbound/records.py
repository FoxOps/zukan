"""Riftbound cards as read from any of its sources (Riot API, Riftcodex, official gallery),
before they become catalog data."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.text import plain_text
from app.games.cardmarket import name_key

__all__ = ["RiftCard", "plain_text"]


@dataclass
class RiftCard:
    # Riftbound id, lower case: `ogn-066a-298`, `unl-229*-219`, `ven-sp3-006`, `unl-t01`.
    # Variants sharing an id (Metal prints) get `~variant` appended.
    id: str
    set_code: str
    name: str
    set_name: str | None = None
    variant: str | None = None
    rarity: str | None = None
    type: str | None = None
    supertype: str | None = None
    domains: list[str] = field(default_factory=list)
    energy: int | None = None
    might: int | None = None
    power: int | None = None
    tags: list[str] = field(default_factory=list)
    text: str | None = None
    flavor: str | None = None
    artist: str | None = None
    image: str | None = None
    orientation: str | None = None
    tcgplayer_id: str | None = None
    flags: dict[str, Any] = field(default_factory=dict)


def normalize_id(value: str) -> str:
    """The gallery writes `ogn-299-star-298` what other sources write `ogn-299*-298`."""
    return value.strip().lower().replace("-star-", "*-")


def collector_number(card_id: str) -> str:
    """Printed number from the id: `ogn-066a-298` -> `066a`, `unl-t01` -> `t01`."""
    parts = card_id.split("~")[0].split("-")
    return parts[1] if len(parts) > 1 else parts[0]


def full_name(name: str, subtitle: str | None, separator: str = ", ") -> str:
    """Champions carry a subtitle: "Ahri" + "Alluring" = "Ahri, Alluring" (the name
    markets and players use)."""
    name, subtitle = name.strip(), (subtitle or "").strip()
    return f"{name}{separator}{subtitle}" if subtitle else name


_VARIANT = re.compile(r"\s*\(([^)]+)\)\s*$")


def split_variant(name: str) -> tuple[str, str | None]:
    """ "Ahri - Alluring (Alternate Art)" -> ("Ahri, Alluring", "Alternate Art")."""
    variant = None
    if match := _VARIANT.search(name):
        variant, name = match.group(1).strip(), name[: match.start()]
    head, sep, tail = name.partition(" - ")
    return (f"{head.strip()}, {tail.strip()}" if sep else name.strip()), variant


def card_key(name: str) -> str:
    """Card external id: the name without case, accents or punctuation."""
    return name_key(name).replace(" ", "-")


def as_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def dedupe(cards: list[RiftCard]) -> list[RiftCard]:
    """One record per printing. Sources list some cards twice under one id: the same
    card (kept once, missing fields filled from the other) or a variant sharing the id
    (Metal print), which gets `~variant`."""
    out: dict[str, RiftCard] = {}
    for card in cards:
        key = card.id
        same = out.get(key)
        if same is not None and (same.name, same.variant) != (card.name, card.variant):
            if card.variant:
                key = f"{card.id}~{card_key(card.variant)}"
            else:
                # The plain card came second: it takes the id, the variant moves.
                moved = out.pop(key)
                moved.id = f"{moved.id}~{card_key(moved.variant or 'variant')}"
                out[moved.id] = moved
            card.id = key
            same = out.get(key)
        if same is None:
            out[key] = card
            continue
        for name, value in vars(card).items():
            if getattr(same, name) in (None, [], {}) and value not in (None, [], {}):
                setattr(same, name, value)
    return list(out.values())
