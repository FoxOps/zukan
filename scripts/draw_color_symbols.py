"""Draw Zukan's own symbols where no source has one: Lorcana inks and text symbols, Riftbound text
symbols (exhaust, might, any rune, energy), Sorcery colorless,
Pokémon "No type", Yu-Gi-Oh! Spell and Trap (fallback of Konami's). Written to `backend/app/games/<game>/symbols/<code>.svg`
(`ColorDef.icon_file`); existing files are kept.

    python scripts/draw_color_symbols.py
"""

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "backend" / "app" / "games"
WHITE = 'fill="#fff" stroke="#111827" stroke-width="1.5" stroke-linejoin="round"'


def _svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{body}</svg>\n'


def ink(fill: str, stroke: str, glyph: str) -> str:
    """Lorcana: the ink hexagon of the card's cost, a glyph per ink."""
    hexagon = "M32 3 57.1 17.5V46.5L32 61 6.9 46.5V17.5Z"
    return _svg(
        f'<path d="{hexagon}" fill="{fill}" stroke="{stroke}" stroke-width="4" '
        f'stroke-linejoin="round"/>{glyph}'
    )


def disc(fill: str, stroke: str, glyph: str) -> str:
    return _svg(
        f'<circle cx="32" cy="32" r="28" fill="{fill}" stroke="{stroke}" stroke-width="4"/>{glyph}'
    )


DRAWINGS = {
    "lorcana": {
        # Drop of amber.
        "amber": ink(
            "#F2B32E",
            "#8A5A00",
            f'<path d="M32 13C32 13 19 29 19 38a13 13 0 0 0 26 0C45 29 32 13 32 13Z" {WHITE}/>',
        ),
        # Cut gem.
        "amethyst": ink(
            "#7E4A9C",
            "#3F1D55",
            f'<path d="M22 20H42L49 29 32 48 15 29Z" {WHITE}/>'
            '<path d="M15 29H49M26 20 32 48 38 20" fill="none" stroke="#111827" '
            'stroke-width="1.5"/>',
        ),
        # Leaf.
        "emerald": ink(
            "#2E8B57",
            "#14462A",
            f'<path d="M18 46C17 27 30 17 47 17 48 34 37 47 18 46Z" {WHITE}/>'
            '<path d="M18 46 39 25" fill="none" stroke="#111827" stroke-width="1.5"/>',
        ),
        # Faceted diamond.
        "ruby": ink(
            "#C8243B",
            "#650F1C",
            f'<path d="M32 14 47 32 32 50 17 32Z" {WHITE}/>'
            '<path d="M32 22 40 32 32 42 24 32Z" fill="none" stroke="#111827" '
            'stroke-width="1.5"/>',
        ),
        # Four-pointed star.
        "sapphire": ink(
            "#1F6FB5",
            "#0B355C",
            f'<path d="M32 12 36.5 27.5 52 32 36.5 36.5 32 52 27.5 36.5 12 32 27.5 27.5Z" '
            f"{WHITE}/>",
        ),
        # Shield.
        "steel": ink(
            "#8A949E",
            "#3B4249",
            f'<path d="M32 14 47 19V31C47 40 41 46.5 32 50.5 23 46.5 17 40 17 31V19Z" {WHITE}/>'
            '<path d="M32 14V50.5" fill="none" stroke="#111827" stroke-width="1.5"/>',
        ),
    },
    "pokemon": {
        # Trainers and special Energies: an empty set sign, apart from Colorless (a type).
        "none": disc(
            "#E5E7EB",
            "#6B7280",
            '<circle cx="32" cy="32" r="13" fill="none" stroke="#4B5563" stroke-width="4"/>'
            '<path d="M21 43 43 21" stroke="#4B5563" stroke-width="4" stroke-linecap="round"/>',
        ),
    },
    "sorcery": {
        # No element: a plain ring, apart from the four elemental triangles.
        "colorless": disc(
            "#9CA3AF",
            "#4B5563",
            '<circle cx="32" cy="32" r="13" fill="#E5E7EB" stroke="#4B5563" stroke-width="3"/>',
        ),
    },
    "yugioh": {
        # Spell: green disc, a spell's sparkle.
        "spell": disc(
            "#1D9A86",
            "#0B4D42",
            f'<path d="M32 11 36 27 52 22 39 32 52 42 36 37 32 53 28 37 12 42 25 32 12 22 '
            f'28 27Z" {WHITE}/>',
        ),
        # Trap: magenta disc, closing jaws.
        "trap": disc(
            "#B5307A",
            "#5C1239",
            f'<path d="M14 24H50L45 33 40 26 35 33 30 26 25 33 20 26Z" {WHITE}/>'
            f'<path d="M14 40H50L45 31 40 38 35 31 30 38 25 31 20 38Z" {WHITE}/>',
        ),
    },
}


DARK = "#1F2937"
GOLD = "#E8C66A"
GOLD_LINE = f'fill="none" stroke="{GOLD}" stroke-width="5" stroke-linejoin="round"'
WHITE_LINE = 'fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round"'


def number(value: int) -> str:
    """Riftbound energy: a number on a dark disc."""
    size = 34 if value < 10 else 28
    return disc(
        DARK,
        "#111827",
        f'<text x="32" y="33" font-family="Arial, Helvetica, sans-serif" font-weight="700" '
        f'font-size="{size}" fill="#fff" text-anchor="middle" dominant-baseline="central">'
        f"{value}</text>",
    )


def wedges(colors: list[str]) -> str:
    """Riftbound rune of any domain: one wedge per domain color."""
    paths = []
    for i, color in enumerate(colors):
        a, b = (2 * math.pi * k / len(colors) - math.pi / 2 for k in (i, i + 1))
        x1, y1 = 32 + 26 * math.cos(a), 32 + 26 * math.sin(a)
        x2, y2 = 32 + 26 * math.cos(b), 32 + 26 * math.sin(b)
        paths.append(
            f'<path d="M32 32L{x1:.1f} {y1:.1f}A26 26 0 0 1 {x2:.1f} {y2:.1f}Z" fill="{color}"/>'
        )
    return _svg(
        '<circle cx="32" cy="32" r="29" fill="#111827"/>'
        + "".join(paths)
        + '<circle cx="32" cy="32" r="9" fill="#111827"/>'
    )


# Symbols of card texts (`SymbolDef.icon_file`), written as tokens: dark backgrounds so they
# read on light and dark themes.
TEXT_DRAWINGS = {
    "lorcana": {
        # {I}: ink, the cost hexagon.
        "I": ink(
            DARK,
            GOLD,
            f'<path d="M32 17 45 24.5V39.5L32 47 19 39.5V24.5Z" {GOLD_LINE}/>',
        ),
        # {S}: strength, a burst.
        "S": disc(
            DARK,
            GOLD,
            f'<path d="M32 12 36 25 49 20 41 31 53 36 39 38 41 52 32 42 23 52 25 38 11 36 '
            f'23 31 15 20 28 25Z" fill="{GOLD}"/>',
        ),
        # {W}: willpower, a shield.
        "W": disc(
            DARK,
            GOLD,
            f'<path d="M32 13 47 18V30C47 39.5 41 46 32 50.5 23 46 17 39.5 17 30V18Z" {GOLD_LINE}/>',
        ),
        # {L}: lore, a diamond.
        "L": disc(DARK, GOLD, f'<path d="M32 12 47 32 32 52 17 32Z" fill="{GOLD}"/>'),
        # {E}: exert, a turning arrow.
        "E": disc(
            DARK,
            GOLD,
            f'<path d="M45 32A13 13 0 1 1 32 19" {GOLD_LINE} stroke-linecap="round"/>'
            f'<path d="M30 11 39 19 30 27Z" fill="{GOLD}"/>',
        ),
        # {IW}: inkwell, an ink drop in a ring.
        "IW": disc(
            DARK,
            GOLD,
            f'<circle cx="32" cy="32" r="17" {GOLD_LINE}/>'
            f'<path d="M32 21C32 21 25 30 25 35a7 7 0 0 0 14 0C39 30 32 21 32 21Z" fill="{GOLD}"/>',
        ),
    },
    "riftbound": {
        # {exhaust}: turned sideways, a quarter-turn arrow.
        "exhaust": disc(
            DARK,
            "#111827",
            f'<path d="M20 40A14 14 0 0 1 40 21" {WHITE_LINE}/>'
            '<path d="M36 13 47 21 37 30Z" fill="#fff"/>',
        ),
        # {might}: a blade.
        "might": disc(
            DARK,
            "#111827",
            '<path d="M32 11 38 21V40H26V21Z" fill="#fff"/>'
            '<path d="M21 42H43M32 42V53" ' + WHITE_LINE + "/>",
        ),
        # {rainbow}: a rune of any domain.
        "rainbow": wedges(
            ["#D7443E", "#4FA35B", "#3A7BD5", "#E08A2E", "#8E4BC2", "#E3C04B"]
        ),
        **{str(n): number(n) for n in range(13)},
    },
}


def main() -> None:
    for game, drawings in TEXT_DRAWINGS.items():
        DRAWINGS.setdefault(game, {}).update(drawings)
    for game, drawings in DRAWINGS.items():
        folder = GAMES / game / "symbols"
        folder.mkdir(exist_ok=True)
        for code, svg in drawings.items():
            path = folder / f"{code}.svg"
            if not path.exists():
                path.write_text(svg)
                print(f"{game}: drew {code}")


if __name__ == "__main__":
    main()
