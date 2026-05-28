import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.exceptions import BCCRError, NoDataError
from ticorates.models.domain import ExchangeRates, Rate


def make_http_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


def make_client(http_client=None) -> BCCRClient:
    return BCCRClient(http_client or make_http_client())


def mock_indicator_response(value: float) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "estado": True,
        "datos": [{"series": [{"valorDatoPorPeriodo": value}]}],
    }
    return response


def test_get_currencies_returns_dict():
    currencies = BCCRClient.get_currencies()
    assert isinstance(currencies, dict)
    assert len(currencies) > 1


def test_get_currencies_includes_usd():
    currencies = BCCRClient.get_currencies()
    assert "USD" in currencies
    assert "Dollar" in currencies["USD"]


def test_get_currencies_values_are_strings():
    currencies = BCCRClient.get_currencies()
    assert all(isinstance(v, str) for v in currencies.values())


def test_calculate_cross_rate_usd_is_base_divides():
    """JPY-style: CRC/USD ÷ JPY/USD → CRC/JPY."""
    client = make_client()
    usd_rate = Rate(purchase=500.0, sale=510.0)
    result = client._calculate_cross_rate(usd_rate, 150.0, usd_is_base=True)
    assert result.purchase == round(500.0 / 150.0, 2)
    assert result.sale == round(510.0 / 150.0, 2)


def test_calculate_cross_rate_usd_is_not_base_multiplies():
    """EUR-style: USD/EUR × CRC/USD → CRC/EUR."""
    client = make_client()
    usd_rate = Rate(purchase=500.0, sale=510.0)
    result = client._calculate_cross_rate(usd_rate, 1.08, usd_is_base=False)
    assert result.purchase == round(1.08 * 500.0, 2)
    assert result.sale == round(1.08 * 510.0, 2)


def test_calculate_cross_rate_rounds_to_two_decimals():
    client = make_client()
    usd_rate = Rate(purchase=503.33, sale=513.33)
    result = client._calculate_cross_rate(usd_rate, 3.0, usd_is_base=False)
    assert result.purchase == round(3.0 * 503.33, 2)
    assert result.sale == round(3.0 * 513.33, 2)


def test_enrich_descriptions_adds_description():
    client = make_client()
    exchange_rates = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0)})
    enriched = client.enrich_descriptions(exchange_rates)
    assert enriched.rates["USD"].description is not None
    assert "Dollar" in enriched.rates["USD"].description


def test_enrich_descriptions_preserves_values():
    client = make_client()
    exchange_rates = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=501.25, sale=512.75)})
    enriched = client.enrich_descriptions(exchange_rates)
    assert enriched.rates["USD"].purchase == 501.25
    assert enriched.rates["USD"].sale == 512.75


def test_enrich_descriptions_unknown_currency_gets_none():
    client = make_client()
    exchange_rates = ExchangeRates(date="2024-01-15", rates={"XXX": Rate(purchase=100.0, sale=110.0)})
    enriched = client.enrich_descriptions(exchange_rates)
    assert enriched.rates["XXX"].description is None


def test_enrich_descriptions_returns_new_object():
    client = make_client()
    exchange_rates = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0)})
    enriched = client.enrich_descriptions(exchange_rates)
    assert enriched is not exchange_rates


@pytest.mark.asyncio
async def test_fetch_indicator_returns_value():
    http_client = make_http_client()
    http_client.get.return_value = mock_indicator_response(500.5)
    client = BCCRClient(http_client)

    result = await client._fetch_indicator(317, "2024-01-15")
    assert result == 500.5


@pytest.mark.asyncio
async def test_fetch_indicator_formats_date_correctly():
    """Date must be sent to BCCR as YYYY/MM/DD."""
    http_client = make_http_client()
    http_client.get.return_value = mock_indicator_response(500.0)
    client = BCCRClient(http_client)

    await client._fetch_indicator(317, "2024-01-15")

    call_kwargs = http_client.get.call_args.kwargs
    params = call_kwargs.get("params", {})
    assert params["fechaInicio"] == "2024/01/15"
    assert params["fechaFin"] == "2024/01/15"


@pytest.mark.asyncio
async def test_fetch_indicator_raises_on_api_error():
    http_client = make_http_client()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"estado": False, "mensaje": "Internal error"}
    http_client.get.return_value = response
    client = BCCRClient(http_client)

    with pytest.raises(BCCRError, match="BCCR API error"):
        await client._fetch_indicator(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_indicator_raises_on_empty_series():
    http_client = make_http_client()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"estado": True, "datos": [{"series": []}]}
    http_client.get.return_value = response
    client = BCCRClient(http_client)

    with pytest.raises(NoDataError):
        await client._fetch_indicator(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_indicator_raises_on_empty_datos():
    http_client = make_http_client()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"estado": True, "datos": []}
    http_client.get.return_value = response
    client = BCCRClient(http_client)

    with pytest.raises(NoDataError):
        await client._fetch_indicator(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_indicator_raises_no_data_error_on_null_value():
    http_client = make_http_client()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "estado": True,
        "datos": [{"series": [{"valorDatoPorPeriodo": None}]}],
    }
    http_client.get.return_value = response
    client = BCCRClient(http_client)

    with pytest.raises(NoDataError):
        await client._fetch_indicator(317, "2026-05-02")


@pytest.mark.asyncio
async def test_fetch_indicator_retries_on_429():
    http_client = make_http_client()
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429

    success_response = mock_indicator_response(500.0)
    success_response.status_code = 200

    http_client.get.side_effect = [rate_limit_response, success_response]
    client = BCCRClient(http_client)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await client._fetch_indicator(317, "2024-01-15")

    assert result == 500.0
    assert http_client.get.call_count == 2


@pytest.mark.asyncio
async def test_request_with_retry_raises_bccr_error_after_exhausting_429_retries():
    http_client = make_http_client()
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    http_client.get.return_value = rate_limit_response

    client = BCCRClient(http_client)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(BCCRError, match="rate limit") as exc_info:
            await client._request_with_retry(317, "2024-01-15")

    assert exc_info.value.upstream_status == 429
    assert http_client.get.call_count == 3


@pytest.mark.asyncio
async def test_request_with_retry_raises_bccr_error_on_http_error():
    http_client = make_http_client()

    error_response = MagicMock()
    error_response.status_code = 401
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized",
        request=MagicMock(),
        response=MagicMock(status_code=401),
    )
    http_client.get.return_value = error_response
    client = BCCRClient(http_client)

    with pytest.raises(BCCRError) as exc_info:
        await client._request_with_retry(317, "2024-01-15")

    assert exc_info.value.upstream_status == 401


@pytest.mark.asyncio
async def test_request_with_retry_raises_bccr_error_on_timeout():
    http_client = make_http_client()
    http_client.get.side_effect = httpx.ReadTimeout("timed out")
    client = BCCRClient(http_client)

    with pytest.raises(BCCRError, match="timed out"):
        await client._request_with_retry(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_rate_for_currency_coalesces_concurrent_calls():
    """5 concurrent requests for the same key → only 2 HTTP calls (buy + sell)."""
    http_client = make_http_client()

    async def slow_get(*args, **kwargs):
        await asyncio.sleep(0.05)
        return mock_indicator_response(500.0)

    http_client.get.side_effect = slow_get
    client = make_client(http_client)

    results = await asyncio.gather(
        *[client.fetch_rate_for_currency("USD", "2024-01-15") for _ in range(5)]
    )

    assert http_client.get.call_count == 2
    assert all(isinstance(r, ExchangeRates) for r in results)
    assert all(r.rates["USD"].purchase == 500.0 for r in results)
