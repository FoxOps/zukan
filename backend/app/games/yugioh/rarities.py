"""Yu-Gi-Oh! rarities, lowest first, with the spellings of each source: YGOPRODeck names
and codes ("Ultra Rare", "(UR)"), YGOJSON slugs ("ultra") and the Konami database's
short codes ("UR", "SE")."""

from app.games.base import RarityDef

RARITIES = [
    RarityDef(
        "common",
        "Common",
        (
            "(C)",
            "C",
            "N",
            "KC Common",
            "Short Print",
            "(SP)",
            "SP",
            "shortprint",
            "Super Short Print",
            "(SSP)",
            "SSP",
        ),
    ),
    RarityDef("rare", "Rare", ("(R)", "R", "KC Rare")),
    RarityDef("super", "Super Rare", ("(SR)", "SR", "super")),
    RarityDef(
        "ultra", "Ultra Rare", ("(UR)", "UR", "ultra", "KC Ultra Rare", "Ultra Rare (Purple)")
    ),
    RarityDef(
        "secret",
        "Secret Rare",
        (
            "(ScR)",
            "ScR",
            "SE",
            "secret",
            "Ultra Secret Rare",
            "Secret Rare (Red)",
            "Secret Rare (Blue)",
        ),
    ),
    RarityDef("ultimate", "Ultimate Rare", ("(UtR)", "UtR", "UL", "ultimate")),
    RarityDef(
        "ghost", "Ghost Rare", ("(GR)", "HR", "Holographic Rare", "ghost", "Ghost/Gold Rare")
    ),
    RarityDef(
        "gold",
        "Gold Rare",
        (
            "(GUR)",
            "GUR",
            "gold",
            "Gold Secret Rare",
            "(GScR)",
            "goldsecret",
            "Premium Gold Rare",
            "(PG)",
            "premiumgold",
        ),
    ),
    RarityDef(
        "parallel",
        "Parallel Rare",
        (
            "Normal Parallel Rare",
            "(NPR)",
            "NPR",
            "P-N",
            "NP",
            "commonparallel",
            "Super Parallel Rare",
            "(SPR)",
            "P-SR",
            "superparallel",
            "Ultra Parallel Rare",
            "(UPR)",
            "P-UR",
            "ultraparallel",
            "Secret Parallel Rare",
            "P-SE",
            "secretparallel",
            "Extra Secret Parallel Rare",
            "extrasecretparallel",
            "Rare Parallel Rare",
            "Ghost Parallel Rare",
            "Duel Terminal Normal Parallel Rare",
            "Duel Terminal Rare Parallel Rare",
            "Duel Terminal Super Parallel Rare",
            "Duel Terminal Ultra Parallel Rare",
            "Duel Terminal Secret Parallel Rare",
            "Duel Terminal Normal Rare Parallel Rare",
            "(DNPR)",
            "(DRPR)",
            "(DSPR)",
            "(DUPR)",
            "(DScPR)",
        ),
    ),
    RarityDef("prismatic", "Prismatic Secret Rare", ("(PScR)", "PScR", "PSE", "prismaticsecret")),
    RarityDef("collectors", "Collector's Rare", ("(CR)", "CR", "collectors")),
    RarityDef(
        "starlight",
        "Starlight Rare",
        ("(StR)", "StR", "Starlight", "Ultra Rare (Pharaoh's Rare)", "(PhR)"),
    ),
    RarityDef("platinum", "Platinum Secret Rare", ("(PlScR)", "PlScR", "Platinum Rare", "(PlR)")),
    RarityDef(
        "starfoil",
        "Starfoil Rare",
        ("(SFR)", "SFR", "Starfoil", "Shatterfoil Rare", "(SHR)", "Mosaic Rare", "(MSR)"),
    ),
    RarityDef(
        "millennium",
        "Millennium Rare",
        (
            "(M)",
            "M",
            "millenium",
            "Millennium Secret Rare",
            "Millennium Ultra Rare",
            "milleniumultra",
            "Millennium Gold Rare",
            "milleniumgold",
        ),
    ),
    RarityDef(
        "extra_secret",
        "Extra Secret Rare",
        (
            "(EScR)",
            "ESE",
            "extrasecret",
            "Extra Secret",
            "10000 Secret Rare",
            "(10000ScR)",
            "10000secret",
            "20th Secret Rare",
            "(20ScR)",
            "20SE",
            "20thsecret",
        ),
    ),
    RarityDef(
        "quarter_century",
        "Quarter Century Secret Rare",
        ("(QCScR)", "QCScR", "QCSE", "25thsecret", "Quarter Century Ultra Rare"),
    ),
]

# YGOJSON rarity slugs whose rarity name the table above does not spell out.
SLUG_NAMES = {
    "common": "Common",
    "rare": "Rare",
    "super": "Super Rare",
    "ultra": "Ultra Rare",
    "secret": "Secret Rare",
    "ultimate": "Ultimate Rare",
    "ghost": "Ghost Rare",
    "gold": "Gold Rare",
    "goldsecret": "Gold Secret Rare",
    "premiumgold": "Premium Gold Rare",
    "commonparallel": "Normal Parallel Rare",
    "rareparallel": "Rare Parallel Rare",
    "superparallel": "Super Parallel Rare",
    "ultraparallel": "Ultra Parallel Rare",
    "secretparallel": "Secret Parallel Rare",
    "extrasecretparallel": "Extra Secret Parallel Rare",
    "ghostparallel": "Ghost Parallel Rare",
    "prismaticsecret": "Prismatic Secret Rare",
    "collectors": "Collector's Rare",
    "shortprint": "Short Print",
    "millenium": "Millennium Rare",
    "milleniumultra": "Millennium Ultra Rare",
    "milleniumgold": "Millennium Gold Rare",
    "extrasecret": "Extra Secret Rare",
    "20thsecret": "20th Secret Rare",
    "10000secret": "10000 Secret Rare",
    "25thsecret": "Quarter Century Secret Rare",
    "ultrasecret": "Ultra Secret Rare",
    "secret-red": "Secret Rare (Red)",
    "secret-blue": "Secret Rare (Blue)",
    "ultra-purple": "Ultra Rare (Purple)",
    "kcultra": "KC Ultra Rare",
    "kcrare": "KC Rare",
    "kccommon": "KC Common",
    "dtpc": "Duel Terminal Normal Parallel Rare",
    "dtpsp": "Duel Terminal Super Parallel Rare",
    "dtspr": "Duel Terminal Secret Parallel Rare",
    "dtupr": "Duel Terminal Ultra Parallel Rare",
    "dtscpr": "Duel Terminal Secret Parallel Rare",
    "dtrpr": "Duel Terminal Rare Parallel Rare",
}

# Konami database short codes (ja/ko pages) to rarity names.
KONAMI_CODES = {
    "N": "Common",
    "R": "Rare",
    "SR": "Super Rare",
    "UR": "Ultra Rare",
    "SE": "Secret Rare",
    "UL": "Ultimate Rare",
    "HR": "Holographic Rare",
    "GR": "Gold Rare",
    "CR": "Collector's Rare",
    "PSE": "Prismatic Secret Rare",
    "ESE": "Extra Secret Rare",
    "QCSE": "Quarter Century Secret Rare",
    "20SE": "20th Secret Rare",
    "M": "Millennium Rare",
    "P-N": "Normal Parallel Rare",
    "NP": "Normal Parallel Rare",
    "P-SR": "Super Parallel Rare",
    "P-UR": "Ultra Parallel Rare",
    "P-SE": "Secret Parallel Rare",
}


# YGOPRODeck rarity texts that are notes, not rarities.
NOT_RARITIES = {
    "new",
    "reprint",
    "new artwork",
    "2",
    "3",
    "european debut",
    "oceanian debut",
    "european & oceanian debut",
    "force-smw",
}


def clean_rarity(text: str | None) -> str | None:
    if not text or text.strip().casefold() in NOT_RARITIES:
        return None
    return text.strip()


def slug_name(slug: str | None) -> str | None:
    if not slug:
        return None
    return SLUG_NAMES.get(slug) or slug.replace("-", " ").title()
