from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.exceptions import BCCRError
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


# --- get_currencies ---


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


# --- _calculate_cross_rate ---


def test_calculate_cross_rate_usd_is_base_divides():
    """JPY-style: CRC/USD ÷ JPY/USD → CRC/JPY."""
    client = make_client()
    base = Rate(purchase=500.0, sale=510.0)
    result = client._calculate_cross_rate(base, 150.0, usd_is_base=True)
    assert result.purchase == round(500.0 / 150.0, 2)
    assert result.sale == round(510.0 / 150.0, 2)


def test_calculate_cross_rate_usd_is_not_base_multiplies():
    """EUR-style: USD/EUR × CRC/USD → CRC/EUR."""
    client = make_client()
    base = Rate(purchase=500.0, sale=510.0)
    result = client._calculate_cross_rate(base, 1.08, usd_is_base=False)
    assert result.purchase == round(1.08 * 500.0, 2)
    assert result.sale == round(1.08 * 510.0, 2)


def test_calculate_cross_rate_rounds_to_two_decimals():
    client = make_client()
    base = Rate(purchase=503.33, sale=513.33)
    result = client._calculate_cross_rate(base, 3.0, usd_is_base=False)
    assert result.purchase == round(3.0 * 503.33, 2)
    assert result.sale == round(3.0 * 513.33, 2)


# --- enrich_descriptions ---


def test_enrich_descriptions_adds_description():
    client = make_client()
    er = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0)})
    enriched = client.enrich_descriptions(er)
    assert enriched.rates["USD"].description is not None
    assert "Dollar" in enriched.rates["USD"].description


def test_enrich_descriptions_preserves_values():
    client = make_client()
    er = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=501.25, sale=512.75)})
    enriched = client.enrich_descriptions(er)
    assert enriched.rates["USD"].purchase == 501.25
    assert enriched.rates["USD"].sale == 512.75


def test_enrich_descriptions_unknown_currency_gets_none():
    client = make_client()
    er = ExchangeRates(date="2024-01-15", rates={"XXX": Rate(purchase=100.0, sale=110.0)})
    enriched = client.enrich_descriptions(er)
    assert enriched.rates["XXX"].description is None


def test_enrich_descriptions_returns_new_object():
    client = make_client()
    er = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0)})
    enriched = client.enrich_descriptions(er)
    assert enriched is not er


# --- _fetch_indicator ---


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

    with pytest.raises(BCCRError, match="No data"):
        await client._fetch_indicator(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_indicator_raises_on_empty_datos():
    http_client = make_http_client()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"estado": True, "datos": []}
    http_client.get.return_value = response
    client = BCCRClient(http_client)

    with pytest.raises(BCCRError, match="No data"):
        await client._fetch_indicator(317, "2024-01-15")


@pytest.mark.asyncio
async def test_fetch_indicator_retries_on_429():
    """Should retry on rate limit and succeed on the second attempt."""
    http_client = make_http_client()
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429

    success_response = mock_indicator_response(500.0)
    success_response.status_code = 200

    http_client.get.side_effect = [rate_limit_response, success_response]
    client = BCCRClient(http_client)

    # Patch asyncio.sleep to avoid actually waiting
    import asyncio
    from unittest.mock import patch

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await client._fetch_indicator(317, "2024-01-15")

    assert result == 500.0
    assert http_client.get.call_count == 2
