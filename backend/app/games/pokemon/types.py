"""Energy types of a card, as Zukan colors."""

from collections.abc import Iterable

# Trainers and special Energies have no type ("colorless" is a type of its own).
NO_TYPE = "none"
_TYPELESS = {"Trainer", "Energy"}


def card_colors(types: Iterable[str | None], category: str | None) -> list[str]:
    """Lowercase type codes; Trainers and Energies without one get `NO_TYPE`. A Pokémon
    without types is missing data and keeps none."""
    colors = [t.lower() for t in types if t]
    return colors or ([NO_TYPE] if category in _TYPELESS else [])
