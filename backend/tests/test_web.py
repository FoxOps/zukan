import httpx

from app.core.config import get_settings
from app.main import create_app


async def test_serves_single_page_app(tmp_path, monkeypatch):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>app</html>")
    (web / "assets" / "index-abc.js").write_text("console.log(1)")
    (web / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(get_settings(), "web_dir", web)

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for path in ("/", "/collection", "/cards/12"):
            response = await client.get(path)
            assert response.text == "<html>app</html>", path
            assert response.headers["cache-control"] == "no-cache"
        asset = await client.get("/assets/index-abc.js")
        assert asset.headers["cache-control"].endswith("immutable")
        assert (await client.get("/favicon.svg")).text == "<svg/>"
        assert (await client.get("/..%2Fsecret.txt")).text == "<html>app</html>"
        assert (await client.get("/api/nope")).status_code == 404
        assert (await client.get("/api/health")).json() == {"status": "ok"}


async def test_no_web_build_means_api_only(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "web_dir", tmp_path / "missing")
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/collection")).status_code == 404
