"""Set symbol (expansion pictogram) matching for cards that print no set code.

The scanner sends a grayscale picture around the recognized text; the symbol sits at
the right end of the type line. Its silhouette is compared with the sets' icons (the
SVGs already cached for set pictures), as intersection over union of small bitmaps.
Only used to order printings of an already found card, never to find a card.
"""

import asyncio
import base64
import binascii
import io
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from app.games.base import OcrLine
from app.models import CardSet
from app.services.images import cached_asset, set_icon_stem

log = logging.getLogger(__name__)

SIZE = 32
# Height the symbol area is scaled to, and the closing filter size there.
WORK_HEIGHT = 64
CLOSE = 5
# Largest picture accepted from the phone (base64 decoded).
MAX_IMAGE_BYTES = 300_000
# A component smaller than this share of the search area is noise (dust, a letter).
MIN_AREA_SHARE = 0.02
# The best set must beat the next one by this much to count.
MIN_MARGIN = 0.08
MIN_SCORE = 0.45

Silhouette = list[bool]


@dataclass
class ScanPicture:
    image: Image.Image
    # Picture bounds in the OCR boxes' frame (fractions of the text area, may go past
    # 0..1 when the phone sent a margin around the text): left, top, right, bottom.
    box: tuple[float, float, float, float]


def decode(data: str | None, box: list[float] | None) -> ScanPicture | None:
    """The phone's picture, or None when missing or unreadable."""
    if not data or not box or len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            return None
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError):
        return None
    return ScanPicture(ImageOps.grayscale(image), (box[0], box[1], box[2], box[3]))


def symbol_area(type_line: OcrLine) -> tuple[float, float, float, float] | None:
    """Where the symbol is, in the OCR frame: right of the type line's text, as far as
    the card's right edge (past the text area), a bit taller than the line."""
    if type_line.left is None or type_line.top is None:
        return None
    height = type_line.height or 0.03
    end = type_line.left + (type_line.width or 0.3)
    return (max(end, 0.55), type_line.top - 0.4 * height, 1.25, type_line.top + 1.4 * height)


def crop_symbol(picture: ScanPicture, area: tuple[float, float, float, float]) -> Silhouette | None:
    left, top, right, bottom = picture.box
    width, height = picture.image.size

    def px(value: float, start: float, end: float, size: int) -> int:
        return round(min(max((value - start) / (end - start), 0), 1) * size)

    x0, x1 = px(area[0], left, right, width), px(area[2], left, right, width)
    y0, y1 = px(area[1], top, bottom, height), px(area[3], top, bottom, height)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    region = picture.image.crop((x0, y0, x1, y1))
    # Same scale whatever the phone's resolution, then outlines broken by blur closed.
    region = ImageOps.autocontrast(
        region.resize((round(region.width * WORK_HEIGHT / region.height), WORK_HEIGHT))
    )
    mask = Image.frombytes("L", region.size, bytes(255 if d else 0 for d in _dark_mask(region)))
    mask = mask.filter(ImageFilter.MaxFilter(CLOSE)).filter(ImageFilter.MinFilter(CLOSE))
    return silhouette_of([v >= 128 for v in mask.tobytes()], mask.size, keep_edges=False)


def _dark_mask(image: Image.Image) -> list[bool]:
    """Pixels darker than the Otsu threshold of the picture."""
    histogram = image.histogram()[:256]
    total = sum(histogram)
    sum_all = sum(i * h for i, h in enumerate(histogram))
    best, threshold, weight, sum_dark = -1.0, 128, 0, 0
    for i, count in enumerate(histogram):
        weight += count
        if weight == 0 or weight == total:
            continue
        sum_dark += i * count
        mean_dark = sum_dark / weight
        mean_light = (sum_all - sum_dark) / (total - weight)
        between = weight * (total - weight) * (mean_dark - mean_light) ** 2
        if between > best:
            best, threshold = between, i
    return [value <= threshold for value in image.tobytes()]


def silhouette_of(
    mask: list[bool], size: tuple[int, int], keep_edges: bool = True
) -> Silhouette | None:
    """The largest shape of the mask, holes filled, scaled into a SIZE square (aspect
    kept, centered). Shapes touching the left or right side (card frame, type bar
    borders) are skipped unless `keep_edges`."""
    width, height = size
    seen = [False] * len(mask)
    best: list[int] = []
    for start, on in enumerate(mask):
        if not on or seen[start]:
            continue
        component, edge = [], False
        queue = deque([start])
        seen[start] = True
        while queue:
            i = queue.popleft()
            component.append(i)
            x = i % width
            if x in (0, width - 1):
                edge = True
            for n in (i - 1 if x else -1, i + 1 if x < width - 1 else -1, i - width, i + width):
                if 0 <= n < len(mask) and mask[n] and not seen[n]:
                    seen[n] = True
                    queue.append(n)
        if (keep_edges or not edge) and len(component) > len(best):
            best = component
    if len(best) < max(4, MIN_AREA_SHARE * width * height):
        return None
    xs = [i % width for i in best]
    ys = [i // width for i in best]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    shape = Image.new("L", (x1 - x0, y1 - y0), 0)
    pixels = shape.load()
    assert pixels is not None
    for i in best:
        pixels[i % width - x0, i // width - y0] = 255
    filled = _fill_holes(shape)
    side = max(filled.size)
    square = Image.new("L", (side, side), 0)
    square.paste(filled, ((side - filled.width) // 2, (side - filled.height) // 2))
    small = square.resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    return [value >= 128 for value in small.tobytes()]


def _fill_holes(shape: Image.Image) -> Image.Image:
    """Everything the outside cannot reach is part of the shape (outlined symbols)."""
    width, height = shape.size
    data = list(shape.tobytes())
    outside = [False] * len(data)
    queue = deque(
        i
        for i in range(len(data))
        if data[i] == 0 and (i % width in (0, width - 1) or i // width in (0, height - 1))
    )
    for i in queue:
        outside[i] = True
    while queue:
        i = queue.popleft()
        x = i % width
        for n in (i - 1 if x else -1, i + 1 if x < width - 1 else -1, i - width, i + width):
            if 0 <= n < len(data) and data[n] == 0 and not outside[n]:
                outside[n] = True
                queue.append(n)
    return Image.frombytes("L", shape.size, bytes(0 if out else 255 for out in outside))


def icon_silhouette(svg: bytes) -> Silhouette | None:
    """Silhouette of a set icon: its opaque pixels."""
    import resvg_py

    try:
        png = resvg_py.svg_to_bytes(
            svg_string=svg.decode("utf-8", "replace"), width=96, skip_system_fonts=True
        )
        image = Image.open(io.BytesIO(bytes(png)))
        image.load()
    except (ValueError, OSError, UnidentifiedImageError) as exc:
        log.debug("set icon not rendered: %s", exc)
        return None
    alpha = image.convert("RGBA").getchannel("A")
    return silhouette_of([value >= 128 for value in alpha.tobytes()], alpha.size)


def similarity(a: Silhouette, b: Silhouette) -> float:
    both = sum(1 for x, y in zip(a, b, strict=True) if x and y)
    either = sum(1 for x, y in zip(a, b, strict=True) if x or y)
    return both / either if either else 0.0


_icons: dict[tuple[int, str], Silhouette | None] = {}


async def _set_silhouette(http: httpx.AsyncClient, card_set: CardSet) -> Silhouette | None:
    key = (card_set.id, card_set.icon_url or "")
    if key not in _icons:
        path: Path | None = await cached_asset(http, card_set.icon_url, set_icon_stem(card_set))
        if path is None or path.suffix.lower() != ".svg":
            _icons[key] = None
        else:
            svg = await asyncio.to_thread(path.read_bytes)
            _icons[key] = await asyncio.to_thread(icon_silhouette, svg)
    return _icons[key]


async def best_set(
    http: httpx.AsyncClient, symbol: Silhouette, sets: list[CardSet]
) -> tuple[int | None, dict[str, float]]:
    """The set whose icon clearly matches the symbol (None when unsure), and every
    set's score (for the debug log)."""
    unique = list({s.id: s for s in sets}.values())
    shapes = await asyncio.gather(*(_set_silhouette(http, s) for s in unique))
    scores = {
        s.id: similarity(symbol, shape) for s, shape in zip(unique, shapes, strict=True) if shape
    }
    named = {s.code: round(scores[s.id], 2) for s in unique if s.id in scores}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] < MIN_SCORE:
        return None, named
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < MIN_MARGIN:
        return None, named
    return ranked[0][0], named
