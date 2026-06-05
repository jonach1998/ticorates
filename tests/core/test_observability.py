from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest

from ticorates.core.observability import _only_from_trusted_proxy, build_instrumentator


def make_info(headers: dict) -> MagicMock:
    info = MagicMock()
    info.request.headers = headers
    return info


def test_records_when_trusted_header_present():
    record = MagicMock()
    gated = _only_from_trusted_proxy(record, "CF-Connecting-IP")

    info = make_info({"cf-connecting-ip": "203.0.113.1"})
    gated(info)

    record.assert_called_once_with(info)


def test_skips_when_trusted_header_absent():
    record = MagicMock()
    gated = _only_from_trusted_proxy(record, "CF-Connecting-IP")

    gated(make_info({}))

    record.assert_not_called()


def app_with(instrumentator) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    instrumentator.instrument(app)
    return app


def ping_metric(registry: CollectorRegistry) -> str | None:
    for line in generate_latest(registry).decode().splitlines():
        if line.startswith('http_requests_total{handler="/ping"'):
            return line
    return None


def test_gating_records_only_requests_with_trusted_header():
    registry = CollectorRegistry()
    client = TestClient(app_with(build_instrumentator("CF-Connecting-IP", registry=registry)))

    client.get("/ping")
    client.get("/ping", headers={"cf-connecting-ip": "1.2.3.4"})

    assert ping_metric(registry) == 'http_requests_total{handler="/ping",method="GET",status="200"} 1.0'


def test_without_trusted_header_records_every_request():
    registry = CollectorRegistry()
    client = TestClient(app_with(build_instrumentator(registry=registry)))

    client.get("/ping")
    client.get("/ping")

    assert ping_metric(registry) == 'http_requests_total{handler="/ping",method="GET",status="200"} 2.0'
