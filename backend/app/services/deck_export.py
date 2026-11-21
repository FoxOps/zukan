"""Plain-text decklists of the Decks module, in each game's usual format, read back by
`services.deck_import`:

- Magic (Moxfield, MTGO, Archidekt, MTG Arena): "Commander" / "Companion" / "Deck" /
  "Sideboard" blocks, "4 Lightning Bolt (M10) 146".
- Pokémon (Pokémon TCG Live, Limitless): "Pokémon: 12" / "Trainer: 30" / "Energy: 18"
  blocks, "4 Charmander PAF 7", "Total Cards: 60".
- Lorcana (Dreamborn, Inktable): "4 Elsa - Snow Queen", no set.
- Riftbound: "Legend:" / "Champion:" / "Main Deck:" / "Battlefields:" / "Runes:" /
  "Sideboard:" blocks.
- Yu-Gi-Oh!: "Main Deck:" / "Extra Deck:" / "Side Deck:" blocks.
- Sorcery (Curiosa): "Avatar:" / "Atlas:" / "Spellbook:" / "Collection:" blocks."""

from dataclasses import dataclass

# Headers of each game's sections, in order.
_MTG_SECTIONS = (
    ("commander", "Commander"),
    ("companion", "Companion"),
    ("main", "Deck"),
    ("sideboard", "Sideboard"),
)
_SECTIONS = {
    "riftbound": (
        ("legend", "Legend:"),
        ("champion", "Champion:"),
        ("main", "Main Deck:"),
        ("battlefields", "Battlefields:"),
        ("runes", "Runes:"),
        ("sideboard", "Sideboard:"),
    ),
    "yugioh": (("main", "Main Deck:"), ("extra", "Extra Deck:"), ("sideboard", "Side Deck:")),
    "sorcery": (
        ("avatar", "Avatar:"),
        ("atlas", "Atlas:"),
        ("main", "Spellbook:"),
        ("sideboard", "Collection:"),
    ),
}


@dataclass
class ExportLine:
    name: str
    section: str
    # Card type group shown in the deck (`api.decks._group`).
    group: str
    quantity: int
    set_code: str | None = None
    collector_number: str | None = None


def _card(line: ExportLine, sets: bool, pokemon: bool = False) -> str:
    text = f"{line.quantity} {line.name}"
    if not sets or not line.set_code:
        return text
    if pokemon:
        return f"{text} {line.set_code} {line.collector_number or ''}".rstrip()
    number = f" {line.collector_number}" if line.collector_number else ""
    return f"{text} ({line.set_code}){number}"


def export_text(game_id: str, lines: list[ExportLine], sets: bool = True) -> str:
    """The decklist (lines in the order shown), sets and numbers when `sets`."""
    if game_id == "lorcana":
        return "\n".join(_card(line, False) for line in lines if line.section == "main") + "\n"
    if game_id.startswith("pokemon"):
        return _pokemon(lines, sets)
    sections = _SECTIONS.get("yugioh" if game_id.startswith("yugioh") else game_id, _MTG_SECTIONS)
    blocks = []
    for section, header in sections:
        cards = [_card(line, sets) for line in lines if line.section == section]
        if cards:
            blocks.append("\n".join([header, *cards]))
    return "\n\n".join(blocks) + "\n"


def _pokemon(lines: list[ExportLine], sets: bool) -> str:
    main = [line for line in lines if line.section == "main"]
    blocks = [
        ("Pokémon", [line for line in main if line.group == "Pokémon"]),
        # Supporters, items, tools, stadiums (and cards of no known kind).
        ("Trainer", [line for line in main if line.group not in ("Pokémon", "Energy")]),
        ("Energy", [line for line in main if line.group == "Energy"]),
    ]
    text = [
        "\n".join(
            [
                f"{title}: {sum(line.quantity for line in cards)}",
                *(_card(line, sets, pokemon=True) for line in cards),
            ]
        )
        for title, cards in blocks
        if cards
    ]
    text.append(f"Total Cards: {sum(line.quantity for line in main)}")
    return "\n\n".join(text) + "\n"
