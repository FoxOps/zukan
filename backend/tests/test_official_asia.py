import json

import pytest
import respx

from app.core.budget import RequestBudget
from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import CardData, SetData
from app.games.pokemon import asia, official_asia
from app.games.pokemon.official_asia import Cache, OfficialCard
from app.games.pokemon.provider import join_asian_set

# Pages written like the sites' (only the parts read).
TH_SEARCH = """
<input id="checkbox84" type="checkbox" class="expansionCode" value="MA6" >
<label for="checkbox84">การ์ดชุดเสริม &quot;30th CELEBRATION&quot;</label>
<input id="checkbox1" type="checkbox" class="expansionCode" value="SV-P" >
<label for="checkbox1">โปรโมการ์ด</label>
"""
TH_LIST = {
    (
        "MA6",
        1,
    ): '<a href="/th/card-search/detail/14720/"></a><a href="?pageNo=2&expansionCodes=MA6">2</a>',
    (
        "MA6",
        2,
    ): '<a href="/th/card-search/detail/14721/"></a><a href="?pageNo=1&expansionCodes=MA6">1</a>',
    ("SV-P", 1): '<a href="/th/card-search/detail/900/"></a>',
}


def th_detail(card_id: str, name: str, number: str, code: str, hp: str | None, dex: int | None):
    marker = '<span class="evolveMarker">พื้นฐาน</span>' if hp else ""
    hp_html = (
        '<p class="mainInfomation"><span class="hitPoint">HP</span>'
        f'<span class="number">{hp}</span><span class="type">ประเภท</span>'
        '<img src="https://asia.pokemon-card.com/various_images/energy/Grass.png"></p>'
        if hp
        else ""
    )
    dex_html = f'<div class="extraInformation"><h3>No.{dex} โปเกมอนไข่</h3></div>' if dex else ""
    return f"""
<h1 class="pageHeader cardDetail">
  {marker}
  {name}
</h1>
<div class="cardImage"><img src="https://asia.pokemon-card.com/th/card-img/th{int(card_id):08d}.png"></div>
{hp_html}
<section class="expansionColumn"><span class="alpha">J</span>
<span class="collectorNumber">{number}</span></section>
{dex_html}
<div class="illustrator"><h3>นักวาด</h3><a href="/th/card-search/list/?illustratorName=Nelnal">Nelnal</a></div>
<section class="expansionLinkColumn"><h3>รวมอยู่ในชุด</h3>
<a href="/th/card-search/list/?expansionCodes={code}"> ชุด {code} </a></section>
"""


TH_DETAILS = {
    "14720": th_detail("14720", "ทามะทามะ", "001/130", "MA6", "60", 102),
    "14721": th_detail("14721", "เมก้าลิซาร์ดอนXex", "002/130", "MA6", "360", 6),
    "900": th_detail("900", "ไอเท็มลึกลับ", "001/SV-P", "SV-P", None, None),
}

KO_DETAIL = """
<img src="/s3.php?key=home%2Fdata%2Fcards.image_www%2Fdata%2Fwmimages%2FMEGA%2FM6a%2FM6a_001.png&w=512" class="feature_image">
<span class="p_num">001/103<span id="no_wrap_by_admin"> </span></span>
<p class="illustrator">일러스트<br />Nelnal</p>
<span class="card-hp title">아라리</span>
<span class="card-hp"><span class="hp_num">HP60</span>
<img src="/s3.php?key=x%2Ftype1.png" class="type_b" data-toggle="tooltip" title="풀"></span>
<a href="/cards?s=MEGA" class="search_href">MEGA 확장팩 「30th CELEBRATION」</a>
<!--No. 102-->
<a href="/cards/detail/BS2026001010"><img src="/s3.php?key=home%2Fdata%2Fcards.image_www%2Fdata%2Fwmimages%2FMEGA%2FMC%2FMC_010.png&w=300"></a>
"""


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path)
    return tmp_path


def test_parse_pages():
    card = official_asia.parse_asia_detail(TH_DETAILS["14720"])
    assert card == OfficialCard(
        code="MA6",
        number="001",
        image="https://asia.pokemon-card.com/th/card-img/th00014720.png",
        name="ทามะทามะ",
        set_name="ชุด MA6",
        total=130,
        dex=102,
        hp=60,
        types=["Grass"],
        artist="Nelnal",
    )
    korean = official_asia.parse_korea_detail(KO_DETAIL)
    assert korean is not None
    assert (korean.code, korean.number, korean.name, korean.total) == ("M6a", "001", "아라리", 103)
    assert korean.image == f"{official_asia.KOREA_IMAGES}wmimages/MEGA/M6a/M6a_001.png"
    assert (korean.dex, korean.hp, korean.types) == (102, 60, ["Grass"])
    assert official_asia.parse_asia_detail("<html>no card</html>") is None


def test_korean_picture_paths():
    assert official_asia.korea_picture("wmimages/MEGA/M-P/M-P_090.png?w=400") == (
        "M-P",
        "090",
        f"{official_asia.KOREA_IMAGES}wmimages/MEGA/M-P/M-P_090.png",
    )
    # Old picture names hold no number.
    assert official_asia.korea_picture("wmimages/DP/BS1/bs1_kr_19.jpg")[:2] == ("BS1", None)
    assert official_asia.korea_picture("images/symbol/M6a.png") is None


def test_thai_english_names():
    assert official_asia.thai_english("ทามะทามะ", 102) == "Exeggcute"
    assert official_asia.thai_english("ลิซาร์ดอนex", 6) == "Charizard ex"
    assert official_asia.thai_english("อโลลา นัชชีex", 103) == "Alolan Exeggutor ex"
    assert official_asia.thai_english("<อโลลา> นัชชี", 103) == "Alolan Exeggutor"
    # "X" left: Mega Charizard X, not only the species.
    assert official_asia.thai_english("เมก้าลิซาร์ดอนXex", 6) is None
    assert official_asia.thai_english("ทามะทามะ", None) is None


async def test_crawl_thai_site_within_budget(cache_dir):
    site = f"{official_asia.ASIA_SITE}/th/card-search"

    def listing(request):
        key = (request.url.params["expansionCodes"], int(request.url.params["pageNo"]))
        return respx.MockResponse(200, text=TH_LIST[key])

    with respx.mock() as router:
        search = router.get(f"{site}/").respond(text=TH_SEARCH)
        lists = router.get(f"{site}/list/").mock(side_effect=listing)
        details = {
            card_id: router.get(f"{site}/detail/{card_id}/").respond(text=page)
            for card_id, page in TH_DETAILS.items()
        }
        async with http_client() as http:
            cache = Cache("th")
            # Search page, the first product's two list pages and its two cards.
            budget = RequestBudget("pokemon-official-th-test", "day", 5)
            with pytest.raises(official_asia.BudgetSpent):
                await official_asia.crawl_asia(http, budget, cache, "th")
            assert search.call_count == 1 and lists.call_count == 2
            assert sorted(cache.listed) == ["14720", "14721"]
            assert sorted(cache.cards) == ["14720", "14721"]
            # Next run: the first product's list is fresh, the second one is read.
            cache = Cache("th")
            budget = RequestBudget("pokemon-official-th-test2", "day", 10)
            await official_asia.crawl_asia(http, budget, cache, "th")
            assert search.call_count == 1 and lists.call_count == 3
            assert all(route.call_count == 1 for route in details.values())
    saved = json.loads((cache_dir / "cache" / "pokemon-official-th.json").read_text())
    assert saved["listed"]["14721"] == [
        "MA6",
        "002",
        "https://asia.pokemon-card.com/th/card-img/th00014721.png",
    ]
    sets = {s.code: s for s in official_asia.asian_sets(Cache("th"), "th")}
    assert set(sets) == {"MA6", "SV-P"}
    assert sets["MA6"].data == SetData(
        external_id="MA6",
        code="MA6",
        name='การ์ดชุดเสริม "30th CELEBRATION"',
        lang="th",
        total=130,
    )
    first = sets["MA6"].cards[0]
    assert first.names == {"th": "ทามะทามะ", "en": "Exeggcute"}
    assert first.attributes == {"category": "Pokemon", "hp": 60, "dexId": [102]}
    assert first.colors == ["grass"]
    assert first.printings[0].languages == ["th"]
    trainer = sets["SV-P"].cards[0]
    assert trainer.names == {"th": "ไอเท็มลึกลับ"} and trainer.attributes == {}


async def test_crawl_korean_list_then_pages(cache_dir):
    def listing(request):
        body = request.read().decode()
        tab = body.split('name="CardTypeNum"')[1].split("\r\n\r\n")[1].split("\r\n")[0]
        page = int(body.split('name="limit"')[1].split("\r\n\r\n")[1].split("\r\n")[0])
        rows = []
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return respx.MockResponse(200, text="접근불가")
        if page == 0:
            rows = {
                "1": [
                    {
                        "CardNum": "BS2026006001",
                        "feature_image": "wmimages/MEGA/M6a/M6a_001.png?w=400",
                    },
                    {
                        "CardNum": "BS2026006002",
                        "feature_image": "wmimages/MEGA/M6a/M6a_002.png?w=400",
                    },
                ],
                # Energies: picture names without number.
                "3": [
                    {
                        "CardNum": "BS2026009019",
                        "feature_image": "wmimages/MEGA/MEM/MEM_GRA.png?w=400",
                    }
                ],
            }.get(tab, [])
        return respx.MockResponse(200, text=json.dumps({"status": True, "result": rows}))

    with respx.mock() as router:
        ajax = router.post(f"{official_asia.KOREA_SITE}/v2/ajax2_dev2").mock(side_effect=listing)
        router.get(f"{official_asia.KOREA_SITE}/cards/detail/BS2026006001").respond(text=KO_DETAIL)
        gone = router.get(f"{official_asia.KOREA_SITE}/cards/detail/BS2026006002").respond(404)
        router.get(f"{official_asia.KOREA_SITE}/cards/detail/BS2026009019").respond(text="<p>?</p>")
        async with http_client() as http:
            cache = Cache("ko")
            budget = RequestBudget("pokemon-official-ko-test", "day", 10)
            await official_asia.crawl_korea(http, budget, cache)
    # One page per tab (fewer than 30 cards: the end), three card pages. The tab that
    # answered nothing is read again next time.
    assert ajax.call_count == 3 and gone.call_count == 1
    assert cache.complete == ["1", "3"]
    assert list(cache.listed) == ["BS2026006001", "BS2026009019"]
    assert cache.listed["BS2026009019"] == [
        "MEM",
        "GRA",
        f"{official_asia.KOREA_IMAGES}wmimages/MEGA/MEM/MEM_GRA.png",
    ]
    assert cache.cards["BS2026006001"]["name"] == "아라리"


def _japanese_set() -> tuple[dict, dict, dict]:
    fetched = {(True, "M6a"): "M6a", (True, "SV-P"): "SV-P"}
    keys = {("M6a", "001"): "en:exeggcute", ("SV-P", "001"): "ja:ふしぎなアイテム"}
    langs: dict[str, str | None] = {"M6a": "ja", "SV-P": "ja"}
    return fetched, keys, langs


def _official(code: str, lang: str, cards: list[CardData]) -> asia.AsianSet:
    return asia.AsianSet(code, SetData(external_id=code, code=code, name=code, lang=lang), cards)


def test_korean_cards_join_japanese_printings():
    fetched, keys, langs = _japanese_set()
    read = official_asia.to_card(
        OfficialCard("M6a", "001", "https://k/1.png", name="아라리", hp=60, dex=102), "ko", "M6a"
    )
    listed_only = official_asia.to_card(OfficialCard("M6a", "002", "https://k/2.png"), "ko", "M6a")
    batch = join_asian_set(
        _official("M6a", "ko", [read, listed_only]), "ko", fetched, keys, set(), langs
    )
    # The read card joins the Japanese printing; the one only listed has no printing to
    # join and no name: left for later.
    assert batch.sets == []
    assert len(batch.cards) == 1
    joined = batch.cards[0]
    assert (joined.external_id, joined.partial) == ("en:exeggcute", True)
    printing = joined.printings[0]
    assert (printing.external_id, printing.languages) == ("001", ["ko"])
    assert printing.names == {"ko": "아라리"} and printing.images == {"ko": "https://k/1.png"}
    # Its Latin names help the Japanese card (Asian names stay the Japanese card's own).
    assert joined.names["en"] == "Exeggcute" and joined.names["fr"] == "Noeunoeuf"
    assert not {"ja", "ko"} & set(joined.names)


def test_listed_korean_card_joins_without_name():
    fetched, keys, langs = _japanese_set()
    listed_only = official_asia.to_card(OfficialCard("M6a", "001", "https://k/1.png"), "ko", "M6a")
    batch = join_asian_set(_official("M6a", "ko", [listed_only]), "ko", fetched, keys, set(), langs)
    printing = batch.cards[0].printings[0]
    assert printing.names == {} and printing.languages == ["ko"]


def test_thai_and_indonesian_sets_keep_their_own_numbers():
    fetched, keys, langs = _japanese_set()
    thai = official_asia.to_card(
        OfficialCard("SV-P", "001", "https://t/1.png", name="ไอเท็มลึกลับ"), "th", "SV-P"
    )
    batch = join_asian_set(_official("SV-P", "th", [thai]), "th", fetched, keys, set(), langs)
    # Not the Japanese promo 001: a set of their own.
    assert [s.external_id for s in batch.sets] == ["sea:SV-P"]
    assert batch.cards[0].printings[0].set_external_id == "sea:SV-P"
    assert langs["sea:SV-P"] == "th"
    indonesian = official_asia.to_card(
        OfficialCard("SV-P", "001", "https://i/1.png", name="Item Misterius"), "id", "SV-P"
    )
    keys[("sea:SV-P", "001")] = batch.cards[0].external_id
    again = join_asian_set(_official("SV-P", "id", [indonesian]), "id", fetched, keys, set(), langs)
    # Indonesian joins the Thai printing of that set.
    assert again.sets == []
    printing = again.cards[0].printings[0]
    assert (printing.set_external_id, printing.languages) == ("sea:SV-P", ["id"])


def test_indonesian_species_names_are_english():
    card = official_asia.to_card(
        OfficialCard("MA6", "001", None, name="Exeggcute", hp=60, dex=102), "id", "MA6"
    )
    assert card.names == {"id": "Exeggcute", "en": "Exeggcute"}
    regional = official_asia.to_card(
        OfficialCard("MA6", "002", None, name="Alolan Exeggutor", hp=150, dex=103), "id", "MA6"
    )
    assert regional.names["en"] == "Alolan Exeggutor"
    trainer = official_asia.to_card(
        OfficialCard("MA6", "090", None, name="Riset Profesor"), "id", "MA6"
    )
    assert trainer.names == {"id": "Riset Profesor"}
