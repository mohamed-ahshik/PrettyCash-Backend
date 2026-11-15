async def test_privacy_page_is_public_html(client):
    response = await client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "privacy policy" in response.text.lower()
    assert response.headers["cache-control"] == "public, max-age=300"


async def test_privacy_trailing_slash_redirects_to_canonical(client):
    response = await client.get("/privacy/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/privacy")


async def test_privacy_page_not_in_openapi(client):
    response = await client.get("/openapi.json")
    paths = response.json()["paths"]
    assert "/privacy" not in paths
    assert "/" not in paths


async def test_root_shows_prettycash_text(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "PrettyCash"
