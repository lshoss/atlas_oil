from datetime import UTC, datetime

from app.schemas import QuotesResponse


def test_orchestrate_tools_are_disabled_without_shared_key(client):
    response = client.post("/api/tools/get_quotes")

    assert response.status_code == 503
    assert "ATLASOIL_TOOL_API_KEY" in response.json()["detail"]


def test_orchestrate_tool_key_protects_and_allows_quotes(client, monkeypatch):
    client.app.state.tool_api_key = "segredo-teste"

    async def fake_quotes():
        return QuotesResponse(quotes=[], source="mock", updated_at=datetime.now(UTC))

    monkeypatch.setattr(client.app.state.market, "quotes", fake_quotes)

    denied = client.post("/api/tools/get_quotes", headers={"X-AtlasOil-Tool-Key": "errada"})
    allowed = client.post(
        "/api/tools/get_quotes", headers={"X-AtlasOil-Tool-Key": "segredo-teste"}
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {"cotações": [], "fonte": "mock"}
