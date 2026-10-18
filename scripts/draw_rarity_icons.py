"""Draw Zukan's own rarity pictograms for the rarities that have none.

Cardmarket's pictograms (`install_rarity_icons.py`) win: this only writes missing files.
Shapes follow the cards where a game prints a rarity symbol (Pokémon: circle, diamond,
stars, black / silver / gold); other games get a colored gem per rarity tier.

    python scripts/draw_rarity_icons.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.games.base import registry, shipped_rarity_icon  # noqa: E402

BLACK, SILVER, GOLD = ("#1f2937", "#d1d5db"), ("#e5e7eb", "#4b5563"), ("#f5c542", "#8a6212")
STAR = "M8 .9l2.1 4.6 5 .5-3.8 3.4 1.1 4.9L8 11.8l-4.4 2.5 1.1-4.9L.9 6l5-.5Z"


def _svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">{body}</svg>\n'


def circle(colors=BLACK) -> str:
    fill, stroke = colors
    return _svg(f'<circle cx="8" cy="8" r="5.5" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')


def diamond(colors=BLACK) -> str:
    fill, stroke = colors
    return _svg(f'<path d="M8 1.5 14.5 8 8 14.5 1.5 8Z" fill="{fill}" stroke="{stroke}"/>')


def stars(count: int, colors=BLACK, sparkle: bool = False) -> str:
    fill, stroke = colors
    if count == 1:
        shapes = [(0, 0, 1)]
    elif count == 2:
        shapes = [(-3.4, 0, 0.6), (3.4, 0, 0.6)]
    else:
        shapes = [(-4.6, 1.2, 0.48), (0, -1.4, 0.48), (4.6, 1.2, 0.48)]
    body = "".join(
        f'<path d="{STAR}" fill="{fill}" stroke="{stroke}" stroke-width="{0.9 / s:.2f}" '
        f'stroke-linejoin="round" transform="translate({8 + dx - 8 * s:.2f} {8 + dy - 8 * s:.2f}) '
        f'scale({s})"/>'
        for dx, dy, s in shapes
    )
    if sparkle:
        body += '<path d="M13.5 1v3M12 2.5h3" stroke="#f59e0b" stroke-width="1.2"/>'
    return _svg(body)


def gem(fill: str, stroke: str, mark: str = "") -> str:
    """A cut gem in a tier color, with an optional light facet color."""
    facet = mark or "#ffffff"
    return _svg(
        f'<path d="M4 2h8l3 4-7 8.5L1 6Z" fill="{fill}" stroke="{stroke}" stroke-width="1" '
        f'stroke-linejoin="round"/><path d="M1 6h14M4 2l2 4 2-4 2 4 2-4M6 6l2 8.5L10 6" '
        f'fill="none" stroke="{facet}" stroke-opacity=".55" stroke-width=".8"/>'
    )


TIERS = {  # gem colors, low to high
    "gray": ("#9ca3af", "#4b5563"),
    "black": ("#1f2937", "#9ca3af"),
    "green": ("#34d399", "#047857"),
    "blue": ("#60a5fa", "#1d4ed8"),
    "silver": ("#e5e7eb", "#6b7280"),
    "gold": ("#f5c542", "#8a6212"),
    "orange": ("#fb923c", "#c2410c"),
    "purple": ("#a78bfa", "#6d28d9"),
    "pink": ("#f472b6", "#be185d"),
    "red": ("#f87171", "#b91c1c"),
    "rainbow": ("#67e8f9", "#7c3aed"),
}


def tier(name: str) -> str:
    return gem(*TIERS[name])


def lantern() -> str:
    """Lorcana Illumineer's Quest: a lit lantern (Cardmarket's logo could not be fetched)."""
    fill, stroke = GOLD
    return _svg(
        f'<path d="M6 3.2a2 2 0 0 1 4 0" fill="none" stroke="{stroke}" stroke-width="1"/>'
        f'<rect x="4.6" y="3.2" width="6.8" height="1.6" rx=".5" fill="{fill}" '
        f'stroke="{stroke}" stroke-width=".8"/>'
        f'<path d="M5.4 4.8h5.2l.9 6.6H4.5Z" fill="{fill}" stroke="{stroke}" stroke-width=".8" '
        f'stroke-linejoin="round"/>'
        '<ellipse cx="8" cy="8.1" rx="1.4" ry="2.1" fill="#fff7d6"/>'
        f'<rect x="3.8" y="11.4" width="8.4" height="1.8" rx=".5" fill="{fill}" '
        f'stroke="{stroke}" stroke-width=".8"/>'
    )


DRAWINGS = {
    "pokemon": {
        "common": circle(),
        "uncommon": diamond(),
        "rare": stars(1),
        "holo_rare": stars(1, SILVER),
        "double_rare": stars(2),
        "triple_rare": stars(3),
        "ace_spec": stars(1, ("#f472b6", "#9d174d")),
        "radiant": stars(1, ("#67e8f9", "#7c3aed")),
        "amazing": stars(1, ("#a7f3d0", "#7c3aed")),
        "illustration_rare": stars(1, GOLD),
        "character_rare": stars(1, GOLD, True),
        "ultra_rare": stars(2, SILVER),
        "character_super_rare": stars(2, GOLD, True),
        "special_illustration_rare": stars(2, GOLD),
        "shiny_rare": stars(1, GOLD, True),
        "shiny_ultra_rare": stars(2, GOLD, True),
        "secret_rare": stars(3, SILVER),
        "hyper_rare": stars(3, GOLD),
        "promo": stars(1, ("#ffffff", "#1f2937")),
    },
    "mtg": {
        "common": tier("black"),
        "uncommon": tier("silver"),
        "rare": tier("gold"),
        "mythic": tier("orange"),
        "special": tier("purple"),
    },
    "sorcery": {
        "ordinary": tier("gray"),
        "exceptional": tier("green"),
        "elite": tier("purple"),
        "unique": tier("orange"),
    },
    "yugioh": {
        "common": tier("gray"),
        "rare": tier("silver"),
        "super": tier("blue"),
        "ultra": tier("gold"),
        "secret": tier("rainbow"),
        "ultimate": tier("black"),
        "ghost": gem("#f8fafc", "#94a3b8"),
        "gold": tier("gold"),
        "parallel": gem("#c7d2fe", "#4338ca"),
        "prismatic": tier("pink"),
        "collectors": tier("purple"),
        "starlight": gem("#fde68a", "#7c3aed"),
        "platinum": gem("#f1f5f9", "#475569"),
        "starfoil": tier("green"),
        "millennium": gem("#d6a85c", "#5b3a12"),
        "extra_secret": tier("red"),
        "quarter_century": gem("#fbbf24", "#b91c1c"),
    },
    "lorcana": {"quest": lantern()},
    "riftbound": {"promo": tier("purple")},
}


def main() -> None:
    for game, drawings in DRAWINGS.items():
        provider = registry()[game]
        folder = ROOT / "backend" / Path(type(provider).__module__.replace(".", "/")).parent
        folder = folder / "rarities"
        for rarity in provider.rarities:
            if rarity.code in drawings and shipped_rarity_icon(game, rarity.code) is None:
                folder.mkdir(exist_ok=True)
                (folder / f"{rarity.code}.svg").write_text(drawings[rarity.code])
                print(f"{game}: drew {rarity.code}")


if __name__ == "__main__":
    main()
