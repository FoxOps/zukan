"""Pokémon China: Cardmarket product ids paired by English card name, card names."""

from app.games.cardmarket import pokemon_name_key
from app.games.pokemon.asia import chinese_card
from app.services.cardmarket_links import link

NAMES = ["Bulbasaur", "Ivysaur", "Venusaur ex", "Charmander", "Charmeleon", "Nidorina"]


def product(pid: int, name: str, expansion: int, added: str = "2025-01-16 18:13:25") -> dict:
    return {"idProduct": pid, "name": name, "idExpansion": expansion, "dateAdded": added}


def test_pokemon_name_key_drops_attacks():
    assert pokemon_name_key("Nidorina [Fetch Family | Sharp Fang]") == "nidorina"
    assert pokemon_name_key("Nidoran [F] [Poison Horn]") == pokemon_name_key("Nidoran♀")
    assert pokemon_name_key("Mew ex [Restart | Genome Hacking]") == "mew ex"


def test_link_pairs_chinese_expansion_by_names():
    ours = [("151C", f"{i:03}", name) for i, name in enumerate(NAMES, 1)]
    ours += [("151C", "025", "Pikachu"), ("151C", "099", "欧尼奥")]
    products = [
        # The Japanese set with the same cards: its products are other printings' ids.
        *(product(100 + i, f"{n} [Attack]", 5328, "2023-06-20") for i, n in enumerate(NAMES)),
        # An international expansion nothing links to yet, listed before Chinese cards.
        *(product(200 + i, n, 4000, "2021-11-12") for i, n in enumerate(NAMES)),
        # Collect 151 (Chinese), products out of collector number order.
        *(product(300 + i, f"{n} [Attack]", 6099) for i, n in enumerate(reversed(NAMES))),
        # Two Pikachu products for one printing: a promo would be a guess.
        product(400, "Pikachu [Charge]", 6099),
        product(401, "Pikachu [Charge]", 6099),
    ]
    found = link(ours, products, claimed={100})
    assert found[("151C", "006")] == 300  # Nidorina
    assert found[("151C", "001")] == 305  # Bulbasaur
    assert len(found) == len(NAMES)
    assert ("151C", "025") not in found


def test_link_needs_most_names_of_a_set():
    ours = [("CSV1C", f"{i:03}", name) for i, name in enumerate(NAMES, 1)]
    # Only two of six names: another set.
    products = [product(1, "Bulbasaur", 7000), product(2, "Ivysaur", 7000)]
    assert link(ours, products, claimed=set()) == {}
    # A small set sharing a few Pokémon with a big expansion of other cards.
    small = [("PROMO", f"{i:03}", name) for i, name in enumerate(NAMES, 1)]
    big = [product(10 + i, n, 7001) for i, n in enumerate(NAMES)]
    big += [product(100 + i, f"Code card {i}", 7001) for i in range(60)]
    assert link(small, big, claimed=set()) == {}


def chs(name: str, **details) -> dict:
    return {
        "name": name,
        "details": {
            "cardName": name,
            "collectionNumber": "100/151",
            "rarityText": "无标记",
            "cardTypeText": "训练家",
            "illustratorName": ["Someone"],
            **details,
        },
    }


def test_chinese_trainers_and_owners_pokemon_translated():
    ball = chinese_card(chs("精灵球", trainerTypeText="物品"), "151C")
    assert ball.names["en"] == "Poké Ball" and ball.names["zh-hans"] == "精灵球"
    marnie = chinese_card(
        chs("玛俐的长毛巨魔ex", cardTypeText="宝可梦", evolveText="2阶进化", hp=320), "CSV9C"
    )
    assert marnie.names["en"] == "Marnie's Grimmsnarl ex"
    energy = chinese_card(chs("基本水能量", cardTypeText="基本能量"), "151C")
    assert energy.names["en"] == "Water Energy"
