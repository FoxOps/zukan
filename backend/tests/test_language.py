"""Account interface language: picked by the user, else the client's OS or browser language
(`Accept-Language`) when the interface has it, else English."""

from app.api.auth import ui_language
from tests.conftest import bearer, make_user


def test_ui_language():
    assert ui_language("fr-FR,fr;q=0.9,en-US;q=0.8") == "fr"
    # Weights before order.
    assert ui_language("en;q=0.5,de-AT;q=0.9") == "de"
    # Languages the interface lacks are skipped; none left: English.
    assert ui_language("ja,es-MX;q=0.4") == "es"
    assert ui_language("ja,zh;q=0.8") == "en"
    assert ui_language("de;q=0,it") == "en"
    assert ui_language("*") == "en"
    assert ui_language("") == "en"
    assert ui_language(None) == "en"
    assert ui_language("fr;q=abc,de") == "de"


async def test_follows_the_client_until_chosen(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")

    async def me(accept: str | None = None, **patch) -> tuple[str, bool]:
        sent = dict(headers)
        if accept is not None:
            sent["Accept-Language"] = accept
        if patch:
            response = await client.patch("/api/auth/me", json=patch, headers=sent)
        else:
            response = await client.get("/api/auth/me", headers=sent)
        assert response.status_code == 200, response.text
        return response.json()["language"], response.json()["language_chosen"]

    assert await me() == ("en", False)
    assert await me("de-DE,de;q=0.9") == ("de", False)
    # A language the interface lacks: English.
    assert await me("ja,zh;q=0.8") == ("en", False)
    # Picked: the client's language no longer matters.
    assert await me("de", language="fr") == ("fr", True)
    assert await me("es") == ("fr", True)
    # Back to the client's language.
    assert await me("es-ES", language_chosen=False) == ("es", False)
    # `language_chosen: false` with a language is a choice.
    assert await me("es", language="de", language_chosen=False) == ("de", True)
