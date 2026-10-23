"""Install Pokécardex's Pokémon rarity pictograms as Zukan's shipped ones.

Pictograms differ by region: international cards (English, French, German, Spanish,
Italian, Portuguese) show stars and circles, Japanese and Chinese cards print a code
("RR", "SAR", "CHR"). They are files of the site's own pages
(`pokecardex.b-cdn.net/assets/images/rarete/ids/rarete_<id>.png`); the ids below were
read from its set pages on 2026-10-23, one zone at a time (`/series`, `?zone=jp`,
`?zone=chn`). Written to `backend/app/games/pokemon/rarities/`:

- `<code>.png` (international, replacing Zukan's drawn SVG),
- `<code>.ja.png` and `<code>.zh.png` (both Chinese scripts) where those cards differ.

Run once by hand, politely (one download a second); the files are then shipped.

    python scripts/install_pokecardex_rarity_icons.py
"""

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "app" / "games" / "pokemon" / "rarities"
URL = "https://pokecardex.b-cdn.net/assets/images/rarete/ids/rarete_{id}.png"
USER_AGENT = "Zukan rarity pictograms (self-hosted collection manager)"

# Our rarity code: Pokécardex id, per zone ("" = international, the plain file).
ICONS: dict[str, dict[str, int]] = {
    "": {
        "common": 1,  # Commune
        "uncommon": 2,  # Unco
        "rare": 3,  # Rare
        "holo_rare": 4,  # Holographique
        "ultra_rare": 34,  # Ultra Rare (Scarlet & Violet and later)
        "secret_rare": 6,  # Secrète
        "promo": 7,  # Promo
        "double_rare": 32,  # Double Rare
        "illustration_rare": 33,  # Illustration Rare
        "special_illustration_rare": 35,  # Illustration Spéciale Rare
        "hyper_rare": 36,  # Hyper Rare
    },
    "ja": {
        "common": 8,  # C
        "uncommon": 9,  # U
        "rare": 10,  # R
        "double_rare": 11,  # RR
        "triple_rare": 12,  # RRR
        "secret_rare": 13,  # SR
        "hyper_rare": 14,  # HR
        "ultra_rare": 15,  # UR
        "promo": 20,  # PR
        "shiny_rare": 27,  # Shiny (S)
        "illustration_rare": 30,  # AR
        "special_illustration_rare": 31,  # SAR
        "ace_spec": 37,  # ACE
    },
    "zh": {
        "common": 8,  # C
        "uncommon": 9,  # U
        "rare": 10,  # R
        "double_rare": 11,  # RR
        "triple_rare": 12,  # RRR
        "secret_rare": 13,  # SR
        "hyper_rare": 14,  # HR
        "ultra_rare": 15,  # UR
        "character_rare": 22,  # CHR
        "character_super_rare": 28,  # CSR
        "radiant": 29,  # K
        "illustration_rare": 30,  # AR
        "special_illustration_rare": 31,  # SAR
    },
}


def main() -> int:
    written = 0
    for zone, icons in ICONS.items():
        for code, icon_id in icons.items():
            name = f"{code}.{zone}.png" if zone else f"{code}.png"
            request = urllib.request.Request(
                URL.format(id=icon_id), headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            if not body.startswith(b"\x89PNG"):
                print(f"{name}: not a PNG, skipped", file=sys.stderr)
                continue
            (OUT / name).write_bytes(body)
            if not zone:
                # The drawn stand-in is replaced.
                (OUT / f"{code}.svg").unlink(missing_ok=True)
            written += 1
            time.sleep(1)
    print(f"{written} pictograms written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
