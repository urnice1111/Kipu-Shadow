import httpx
import pytest

from app.ingestion.client import ApiSource, SourceError

TOKEN = "tok-secreto-xyz"


def make_source(handler, sleeps):
    return ApiSource(
        "https://fuentes.example.test/v1",
        TOKEN,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        max_per_second=1000,
    )


def test_retries_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.url.path == "/v1/record_index"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"chats": []})

    sleeps = []
    source = make_source(handler, sleeps)
    assert source.json("/record_index") == {"chats": []}
    assert len(calls) == 2
    assert 2.0 in sleeps
    assert source.requests == 2


def test_gives_up_without_leaking_token():
    def handler(request):
        return httpx.Response(503, text=f"caído {TOKEN}")

    source = make_source(handler, [])
    with pytest.raises(SourceError) as err:
        source.bytes("/tables/clientes.csv")
    assert TOKEN not in str(err.value)
    assert "HTTP 503" in str(err.value)
    assert source.requests == 5


def test_404_is_not_retried():
    def handler(request):
        return httpx.Response(404, json={"error": "No existe"})

    source = make_source(handler, [])
    with pytest.raises(SourceError):
        source.json("/chats/nope")
    assert source.requests == 1


def test_network_error_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=b"ok")

    source = make_source(handler, [])
    assert source.bytes("/docs/doc_01") == b"ok"
