"""Draw Zukan's own color symbols where no source has one: Lorcana inks, Sorcery colorless,
Pokémon "No type", Yu-Gi-Oh! Spell and Trap (fallback of Konami's). Written to `backend/app/games/<game>/symbols/<code>.svg`
(`ColorDef.icon_file`); existing files are kept.

    python scripts/draw_color_symbols.py
"""

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


def main() -> None:
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
