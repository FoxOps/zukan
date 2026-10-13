"""Regenerate backend/app/games/pokemon/species_names.json from PokeAPI's data.

    python3 scripts/pokemon_species.py

Pokémon species names per language (national Pokédex number -> {lang: name}), used to
show and search Pokémon card names in every language. Run again when new Pokémon come
out; cards of species missing here only keep the names TCGdex gives.
"""

import csv
import io
import json
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv"
# PokeAPI language ids -> ours. Japanese: katakana names (id 1), as printed on cards.
LANGUAGES = {
    1: "ja",
    3: "ko",
    4: "zh-hant",
    5: "fr",
    6: "de",
    7: "es",
    8: "it",
    9: "en",
    12: "zh-hans",
}
TARGET = Path(__file__).parent.parent / "backend/app/games/pokemon/species_names.json"


def main() -> None:
    with urllib.request.urlopen(URL) as response:
        rows = csv.DictReader(io.StringIO(response.read().decode()))
        species: dict[int, dict[str, str]] = {}
        for row in rows:
            lang = LANGUAGES.get(int(row["local_language_id"]))
            if lang:
                species.setdefault(int(row["pokemon_species_id"]), {})[lang] = row["name"]
    data = {str(k): dict(sorted(v.items())) for k, v in sorted(species.items())}
    TARGET.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(data)} species written to {TARGET}")


if __name__ == "__main__":
    main()
