"""Store rarity pictograms collected from Cardmarket as the games' rarity icons.

Cardmarket draws each rarity as an inline SVG in its product lists (the "Rarity"
column); Cloudflare refuses scripted downloads, so they are collected once from a browser
(Playwright: open a few product lists per game in list mode and keep every
`svg[aria-label]`, see PLAN.md) into a JSON file {cardmarket game: {rarity name: svg}}.

    python scripts/install_rarity_icons.py harvest.json

Each SVG is matched to the game's `RarityDef` by name or alias (`rarity_of`) and written
to `backend/app/games/<game>/rarities/<code>.svg` without Cardmarket's tooltip attributes.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.games.base import rarity_icon_file, rarity_of, registry  # noqa: E402

GAMES = {
    "Magic": "mtg",
    "Pokemon": "pokemon",
    "Sorcery": "sorcery",
    "Riftbound": "riftbound",
    "Lorcana": "lorcana",
    "YuGiOh": "yugioh",
}
_DROP = re.compile(r'\s(?:data-[\w-]+|aria-label|width|height|class|style)="[^"]*"')


def clean(svg: str) -> str:
    return _DROP.sub("", svg).strip() + "\n"


def main(path: str) -> None:
    harvest = json.loads(Path(path).read_text())
    if isinstance(harvest, str):
        harvest = json.loads(harvest)
    for market, svgs in harvest.items():
        game = GAMES.get(market)
        if game is None or game not in registry():
            continue
        provider = registry()[game]
        folder = Path(type(provider).__module__.replace(".", "/")).parent
        folder = ROOT / "backend" / folder / "rarities"
        for name, svg in sorted(svgs.items()):
            rarity = rarity_of(game, name)
            if rarity is None:
                print(f"{game}: no rarity for {name!r}")
                continue
            if rarity_icon_file(game, rarity.code) and rarity.name.casefold() != name.casefold():
                continue  # the rarity's own name wins over an alias
            folder.mkdir(exist_ok=True)
            (folder / f"{rarity.code}.svg").write_text(clean(svg))
            print(f"{game}: {name} -> {rarity.code}")
        missing = [r.code for r in provider.rarities if not rarity_icon_file(game, r.code)]
        if missing:
            print(f"{game}: no pictogram for {', '.join(missing)}")


if __name__ == "__main__":
    main(sys.argv[1])
