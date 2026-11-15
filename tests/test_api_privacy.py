async def test_privacy_page_is_public_html(client):
    response = await client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Privacy Policy" in response.text
    assert response.headers["cache-control"] == "public, max-age=300"


async def test_privacy_trailing_slash_redirects_to_canonical(client):
    response = await client.get("/privacy/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/privacy")


async def test_privacy_page_not_in_openapi(client):
    response = await client.get("/openapi.json")
    assert "/privacy" not in response.json()["paths"]
