"""Set symbol matching for cards without a printed set code (old Magic frames)."""

import base64
import io

import respx
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import OcrLine, get_provider
from app.models import CardSet
from app.services import set_symbols

SHAPES = {
    "TRI": '<polygon points="50,5 95,95 5,95"/>',
    "SQR": '<rect x="10" y="10" width="80" height="80"/>',
    "CIR": '<circle cx="50" cy="50" r="45"/>',
}


def svg(shape: str) -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{shape}</svg>'.encode()


def card_picture(scale: float = 1.0) -> tuple[str, list[float], OcrLine]:
    """A gray card: type bar with dark borders, the type text on the left and a dark
    outlined triangle (filled lighter, like an uncommon symbol) at its right end."""
    width, height = round(672 * scale), round(936 * scale)
    image = Image.new("L", (width, height), 30)
    draw = ImageDraw.Draw(image)

    def s(*values: float) -> list[float]:
        return [v * scale for v in values]

    draw.rectangle(s(30, 30, 642, 906), fill=150)
    draw.rectangle(s(45, 528, 627, 578), fill=210, outline=20, width=max(1, round(4 * scale)))
    draw.text(s(67, 545), "Land  Swamp", fill=0)
    draw.polygon(s(592, 538, 617, 568, 567, 568), fill=170, outline=10, width=round(3 * scale))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=75)
    # Text area of the OCR boxes: x 60..548, y 65..905 on the card.
    left, top, text_width, text_height = 60, 65, 488, 840
    box = [-left / text_width, -top / text_height, (672 - left) / text_width]
    box.append((936 - top) / text_height)
    line = OcrLine("Land — Swamp", 7 / text_width, 475 / text_height, 200 / text_width, 28 / 840)
    return base64.b64encode(buffer.getvalue()).decode(), box, line


async def test_symbol_of_the_picture_picks_its_set(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path)
    set_symbols._icons.clear()
    sets = [
        CardSet(id=i, game_id="mtg", code=code, name=code, icon_url=f"https://icons/{code}.svg")
        for i, code in enumerate(SHAPES, 1)
    ]
    for scale in (1.0, 0.6):
        data, box, line = card_picture(scale)
        picture = set_symbols.decode(data, box)
        assert picture is not None
        area = set_symbols.symbol_area(line)
        assert area is not None
        symbol = set_symbols.crop_symbol(picture, area)
        assert symbol is not None, scale
        with respx.mock(assert_all_called=False) as router:  # icons are kept in memory
            for code, shape in SHAPES.items():
                router.get(f"https://icons/{code}.svg").respond(
                    content=svg(shape), headers={"content-type": "image/svg+xml"}
                )
            async with http_client() as http:
                best, scores = await set_symbols.best_set(http, symbol, sets)
        assert best == 1, scores
        assert scores["TRI"] > scores["SQR"] and scores["TRI"] > scores["CIR"]


async def test_unreadable_pictures_are_ignored():
    assert set_symbols.decode("not base64!", [0, 0, 1, 1]) is None
    assert set_symbols.decode(base64.b64encode(b"text").decode(), [0, 0, 1, 1]) is None
    data, _, _ = card_picture(0.3)
    assert set_symbols.decode(data, [0, 0, 0, 1]) is None
    assert set_symbols.decode(data, None) is None
    big = base64.b64encode(b"x" * (set_symbols.MAX_IMAGE_BYTES + 1)).decode()
    assert set_symbols.decode(big, [0, 0, 1, 1]) is None
    # An empty area (no symbol drawn there) gives no silhouette.
    blank = Image.new("L", (300, 400), 200)
    buffer = io.BytesIO()
    blank.save(buffer, "PNG")
    picture = set_symbols.decode(base64.b64encode(buffer.getvalue()).decode(), [0, 0, 1, 1])
    assert picture is not None
    assert set_symbols.crop_symbol(picture, (0.6, 0.5, 1, 0.6)) is None


def test_mtg_parser_finds_the_type_line():
    hints = get_provider("mtg").parse_ocr(
        [
            OcrLine("Leechridden Swamp", 0.0, 0.0, 0.5, 0.03),
            OcrLine("Land — Swamp", 0.01, 0.57, 0.4, 0.03),
            OcrLine("Leechridden Swamp comes into play tapped.", 0.02, 0.7, 0.9, 0.03),
            OcrLine("™ & © 1993-2008 Wizards of the Coast, Inc. 273/301", 0.0, 0.98, 0.7, 0.02),
        ]
    )
    assert (hints.collector_number, hints.printed_total) == ("273", "301")
    assert hints.symbol_line is not None and hints.symbol_line.text == "Land — Swamp"
    assert hints.symbol_line.width == 0.4


async def test_identify_accepts_a_picture(client, session):
    from tests.conftest import bearer, make_user

    await make_user(session)
    headers = await bearer(client, "alice")
    data, box, _ = card_picture(0.5)
    body = {"lines": [{"text": "Forest"}], "game": "mtg", "image": data, "image_box": box}
    with respx.mock() as router:
        router.route().respond(404)  # not in the catalog: the source is asked
        response = await client.post("/api/scan/identify", json=body, headers=headers)
    assert response.status_code == 200, response.text
    body["image_box"] = [0, 0, 1]
    response = await client.post("/api/scan/identify", json=body, headers=headers)
    assert response.status_code == 422
