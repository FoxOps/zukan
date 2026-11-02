"""Full page shown instead of the web interface while the server is in maintenance.

Self-contained (styles, logo and texts inline): nothing else is loaded, so the web
interface is really cut. Written in the user's language (saved on the account, else the
browser's); the page itself switches to the language last used in the browser when the
visitor is unknown, and reloads once the data sync is over.
"""

import base64
import json
from functools import cache
from html import escape
from importlib.resources import files
from string import Template

LANGUAGES = ("en", "fr", "de", "es")

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Maintenance in progress · Zukan",
        "home": "Zukan — home",
        "tagline": "Your cards. Your collections.",
        "eyebrow": "A short break",
        "heading": "Zukan is taking a break",
        "description": "Maintenance is in progress. Thank you for your patience: please come "
        "back in a few moments.",
        "actions": "Available actions",
        "retry": "Try again",
        "note": "Nothing to do on your side.",
        "footer": "Your collections are waiting for you.",
    },
    "fr": {
        "title": "Maintenance en cours · Zukan",
        "home": "Zukan — accueil",
        "tagline": "Vos cartes. Vos collections.",
        "eyebrow": "Une petite pause",
        "heading": "Zukan fait une pause",
        "description": "Une maintenance est en cours. Merci de votre patience : nous vous "
        "invitons à revenir dans quelques instants.",
        "actions": "Actions disponibles",
        "retry": "Réessayer",
        "note": "Aucune action n’est nécessaire de votre côté.",
        "footer": "Vos collections vous attendent.",
    },
    "de": {
        "title": "Wartung läuft · Zukan",
        "home": "Zukan — Startseite",
        "tagline": "Deine Karten. Deine Sammlungen.",
        "eyebrow": "Eine kleine Pause",
        "heading": "Zukan macht eine Pause",
        "description": "Gerade finden Wartungsarbeiten statt. Danke für deine Geduld: Schau "
        "in wenigen Augenblicken wieder vorbei.",
        "actions": "Verfügbare Aktionen",
        "retry": "Erneut versuchen",
        "note": "Du musst nichts weiter tun.",
        "footer": "Deine Sammlungen warten auf dich.",
    },
    "es": {
        "title": "Mantenimiento en curso · Zukan",
        "home": "Zukan — inicio",
        "tagline": "Tus cartas. Tus colecciones.",
        "eyebrow": "Una pequeña pausa",
        "heading": "Zukan se toma un descanso",
        "description": "Hay un mantenimiento en curso. Gracias por tu paciencia: vuelve "
        "dentro de unos instantes.",
        "actions": "Acciones disponibles",
        "retry": "Reintentar",
        "note": "No tienes que hacer nada.",
        "footer": "Tus colecciones te esperan.",
    },
}


@cache
def _template() -> Template:
    static = files("app") / "static"
    logo = base64.b64encode((static / "logo-dark.webp").read_bytes()).decode()
    page = (static / "maintenance.html").read_text(encoding="utf-8")
    # Logo and texts never change: filled once.
    texts = json.dumps(TEXTS, ensure_ascii=False).replace("</", "<\\/")
    page = Template(page).safe_substitute(logo=f"data:image/webp;base64,{logo}", texts=texts)
    return Template(page)


def accept_language(header: str | None) -> str | None:
    """First supported language of an Accept-Language header, by preference."""
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate((header or "").split(",")):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                continue
        lang = tag.strip().split("-")[0].lower()
        if lang in LANGUAGES and quality > 0:
            ranked.append((-quality, index, lang))
    return min(ranked)[2] if ranked else None


def render(lang: str | None, known: bool) -> str:
    """The page in `lang` (English if unsupported). `known`: the language is the signed-in
    user's, so the browser's stored one does not replace it."""
    lang = lang if lang in LANGUAGES else "en"
    return _template().substitute(
        lang=lang,
        known="1" if known else "0",
        **{key: escape(value) for key, value in TEXTS[lang].items()},
    )
