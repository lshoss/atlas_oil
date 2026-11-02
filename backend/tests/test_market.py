from datetime import date

import httpx2

from app.market import change_percent, parse_chart
from app.schemas import PricePoint

from .conftest import BASE_DAY, tickers, yahoo_payload


def quote_for(response, symbol):
    return next(q for q in response.json()["quotes"] if q["symbol"] == symbol)


def test_quotes_cover_all_assets_with_daily_change(client):
    response = client.get("/api/market/quotes")

    assert response.status_code == 200
    body = response.json()
    assert [q["symbol"] for q in body["quotes"]] == [
        "BRENT",
        "WTI",
        "NG",
        "PETR4",
        "PRIO3",
        "RECV3",
    ]
    assert body["source"] == "Yahoo Finance"
    assert body["updated_at"]

    brent = quote_for(response, "BRENT")
    assert brent["price"] == 84.0
    assert brent["change_percent"] == 2.44
    assert brent["unit"] == "US$/bbl"
    assert quote_for(response, "PETR4")["currency"] == "BRL"


def test_yahoo_request_uses_a_browser_user_agent(client, upstream):
    seen = {}

    def capture(request):
        seen["agent"] = request.headers["user-agent"]
        seen["url"] = str(request.url)
        return httpx2.Response(200, json=yahoo_payload([80.0, 81.0]))

    upstream.yahoo["BZ=F"] = capture
    client.get("/api/market/history/BRENT")

    assert seen["agent"].startswith("Mozilla/5.0")
    assert "/v8/finance/chart/BZ=F" in seen["url"]
    assert "range=1y" in seen["url"]
    assert "interval=1d" in seen["url"]


def test_failed_asset_does_not_break_the_others(client, upstream):
    upstream.yahoo["NG=F"] = lambda request: httpx2.Response(429, text="Too Many Requests")

    response = client.get("/api/market/quotes")

    assert response.status_code == 200
    assert quote_for(response, "NG")["price"] is None
    assert quote_for(response, "NG")["change_percent"] is None
    assert quote_for(response, "BRENT")["price"] == 84.0


def test_quotes_and_history_share_cached_series(client, upstream):
    client.get("/api/market/quotes")
    client.get("/api/market/quotes")
    client.get("/api/market/history/BRENT?range=7d")
    client.get("/api/market/history/BRENT?range=1a")

    assert upstream.count("query1.finance.yahoo.com") == len(tickers())


def test_history_slices_by_calendar_days(client, upstream):
    closes = [float(100 + day) for day in range(120)]
    upstream.yahoo["BZ=F"] = lambda request: httpx2.Response(200, json=yahoo_payload(closes))

    seven = client.get("/api/market/history/BRENT?range=7d").json()
    ninety = client.get("/api/market/history/BRENT?range=90d").json()

    assert len(seven["points"]) == 8
    assert seven["points"][-1]["close"] == 219.0
    assert seven["name"] == "Petróleo Brent"
    assert seven["kind"] == "commodity"
    assert len(ninety["points"]) == 91


def test_history_defaults_to_thirty_days(client):
    assert client.get("/api/market/history/BRENT").json()["range"] == "30d"


def test_history_rejects_unknown_symbol_and_range(client):
    assert client.get("/api/market/history/XXX").status_code == 404
    assert client.get("/api/market/history/BRENT?range=5a").status_code == 422


def test_history_reports_upstream_failure(client, upstream):
    upstream.yahoo["BZ=F"] = lambda request: httpx2.Response(500)

    response = client.get("/api/market/history/BRENT")

    assert response.status_code == 502
    assert "Yahoo Finance" in response.json()["detail"]


def test_unexpected_payload_is_an_upstream_failure(client, upstream):
    empty = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    upstream.yahoo["BZ=F"] = lambda request: httpx2.Response(200, json=empty)

    response = client.get("/api/market/history/BRENT")

    assert response.status_code == 502
    assert "formato inesperado" in response.json()["detail"]


def test_parse_chart_skips_gaps_and_keeps_one_close_per_day():
    payload = yahoo_payload([80.0, None, 82.123456])
    result = payload["chart"]["result"][0]
    result["timestamp"].append(result["timestamp"][-1] + 7200)
    result["indicators"]["quote"][0]["close"].append(83.0)
    result["meta"]["regularMarketPrice"] = 83.5

    series = parse_chart(payload)

    assert [(p.date, p.close) for p in series.points] == [
        (date(2026, 10, 1), 80.0),
        (date(2026, 10, 3), 83.5),
    ]


def test_parse_chart_uses_the_market_timezone():
    timestamp = int(BASE_DAY.timestamp())  # 00:00 em Nova York, 04:00 em UTC
    payload = yahoo_payload([80.0])
    result = payload["chart"]["result"][0]
    result["timestamp"] = [timestamp - 3600]  # 23:00 do dia anterior em Nova York
    result["meta"]["regularMarketTime"] = None
    result["meta"]["regularMarketPrice"] = None

    assert parse_chart(payload).points[0].date == date(2026, 9, 30)


def test_change_percent_needs_two_points():
    one = [PricePoint(date=date(2026, 10, 1), close=80)]
    two = [*one, PricePoint(date=date(2026, 10, 2), close=88)]

    assert change_percent(one) is None
    assert change_percent(two) == 10.0
