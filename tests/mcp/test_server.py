from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.server import (
    TicoRatesAPIError,
    convert_amount,
    get_historical_average,
    get_latest_rates,
    get_rate_change,
    get_rates_for_date,
    get_rates_for_date_range,
    get_supported_currencies,
)


def make_response(data) -> MagicMock:
    response = MagicMock()
    response.is_success = True
    response.json.return_value = data
    return response


def make_error_response(status_code: int, detail: str) -> MagicMock:
    response = MagicMock()
    response.is_success = False
    response.status_code = status_code
    response.json.return_value = {"detail": detail}
    return response


@contextmanager
def patched_httpx(*responses):
    mock_client = AsyncMock()
    resolved = [r if isinstance(r, MagicMock) else make_response(r) for r in responses]
    if len(resolved) == 1:
        mock_client.get.return_value = resolved[0]
    else:
        mock_client.get.side_effect = resolved

    with patch("httpx.AsyncClient") as mock_class:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=mock_client)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_class.return_value = instance
        yield mock_client


CURRENCIES = {
    "USD": "United States Dollar",
    "EUR": "Euro (European Union)",
}

RATES_USD = {
    "date": "2025-05-27",
    "rates": {
        "USD": {"purchase": 512.50, "sale": 519.75, "description": "United States Dollar"},
    },
}

RATES_EUR = {
    "date": "2025-05-27",
    "rates": {
        "EUR": {"purchase": 553.00, "sale": 561.00, "description": "Euro (European Union)"},
    },
}


@pytest.mark.asyncio
async def test_get_supported_currencies_returns_data():
    with patched_httpx(CURRENCIES):
        result = await get_supported_currencies()
    assert result == CURRENCIES


@pytest.mark.asyncio
async def test_get_supported_currencies_hits_correct_endpoint():
    with patched_httpx(CURRENCIES) as mock_client:
        await get_supported_currencies()
    url = mock_client.get.call_args.args[0]
    assert url.endswith("/currencies")


@pytest.mark.asyncio
async def test_get_latest_rates_passes_currency():
    with patched_httpx(RATES_USD) as mock_client:
        result = await get_latest_rates("USD")
    assert result == RATES_USD
    params = mock_client.get.call_args.kwargs["params"]
    assert params["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_latest_rates_hits_latest_endpoint():
    with patched_httpx(RATES_USD) as mock_client:
        await get_latest_rates("USD")
    url = mock_client.get.call_args.args[0]
    assert url.endswith("/rates/latest")


@pytest.mark.asyncio
async def test_get_rates_for_date_passes_date_and_currency():
    with patched_httpx(RATES_USD) as mock_client:
        result = await get_rates_for_date("2025-05-27", "USD")
    assert result == RATES_USD
    params = mock_client.get.call_args.kwargs["params"]
    assert params["date"] == "2025-05-27"
    assert params["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_rates_for_date_range_passes_from_to_currency():
    range_data = [RATES_USD, RATES_USD]
    with patched_httpx(range_data) as mock_client:
        result = await get_rates_for_date_range("2025-05-01", "2025-05-27", "USD")
    assert result == range_data
    params = mock_client.get.call_args.kwargs["params"]
    assert params["from"] == "2025-05-01"
    assert params["to"] == "2025-05-27"
    assert params["currency"] == "USD"


@pytest.mark.asyncio
async def test_convert_same_currency_skips_http():
    result = await convert_amount(100.0, "USD", "USD")
    assert result["to"]["amount"] == 100.0
    assert result["date"] is None


@pytest.mark.asyncio
async def test_convert_usd_to_crc_fetches_only_usd():
    """CRC is the target — only USD rate needed (1 API call)."""
    with patched_httpx(RATES_USD) as mock_client:
        result = await convert_amount(100.0, "USD", "CRC")
    assert mock_client.get.call_count == 1
    params = mock_client.get.call_args.kwargs["params"]
    assert params["currency"] == "USD"
    expected = round(100.0 * RATES_USD["rates"]["USD"]["purchase"], 2)
    assert result["to"]["amount"] == expected
    assert result["from"]["currency"] == "USD"
    assert result["to"]["currency"] == "CRC"


@pytest.mark.asyncio
async def test_convert_crc_to_usd_fetches_only_usd():
    """CRC is the source — only USD rate needed (1 API call)."""
    with patched_httpx(RATES_USD) as mock_client:
        result = await convert_amount(50_000.0, "CRC", "USD")
    assert mock_client.get.call_count == 1
    params = mock_client.get.call_args.kwargs["params"]
    assert params["currency"] == "USD"
    expected = round(50_000.0 / RATES_USD["rates"]["USD"]["sale"], 2)
    assert result["to"]["amount"] == expected


@pytest.mark.asyncio
async def test_convert_cross_currency_fetches_both_in_parallel():
    """EUR → USD: needs both currencies — 2 parallel API calls."""
    with patched_httpx(RATES_EUR, RATES_USD) as mock_client:
        result = await convert_amount(100.0, "EUR", "USD")
    assert mock_client.get.call_count == 2
    crc = 100.0 * RATES_EUR["rates"]["EUR"]["purchase"]
    expected = round(crc / RATES_USD["rates"]["USD"]["sale"], 2)
    assert result["to"]["amount"] == expected


@pytest.mark.asyncio
async def test_convert_with_date_passes_date_param():
    with patched_httpx(RATES_USD) as mock_client:
        await convert_amount(100.0, "USD", "CRC", date="2025-01-15")
    params = mock_client.get.call_args.kwargs["params"]
    assert params["date"] == "2025-01-15"


@pytest.mark.asyncio
async def test_convert_without_date_hits_latest_endpoint():
    with patched_httpx(RATES_USD) as mock_client:
        await convert_amount(100.0, "USD", "CRC")
    url = mock_client.get.call_args.args[0]
    assert url.endswith("/rates/latest")


RATES_JAN = {"date": "2025-01-01", "rates": {"USD": {"purchase": 500.0, "sale": 510.0}}}
RATES_FEB = {"date": "2025-02-01", "rates": {"USD": {"purchase": 515.0, "sale": 525.0}}}


@pytest.mark.asyncio
async def test_get_rate_change_positive():
    with patched_httpx(RATES_JAN, RATES_FEB):
        result = await get_rate_change("USD", "2025-01-01", "2025-02-01")

    assert result["currency"] == "USD"
    assert result["from_date"] == "2025-01-01"
    assert result["to_date"] == "2025-02-01"
    assert result["change"]["purchase"]["absolute"] == 15.0
    assert result["change"]["sale"]["absolute"] == 15.0
    assert result["change"]["purchase"]["percentage"] == round(15.0 / 500.0 * 100, 4)
    assert result["change"]["sale"]["percentage"] == round(15.0 / 510.0 * 100, 4)


@pytest.mark.asyncio
async def test_get_rate_change_negative():
    rates_high = {"date": "2025-01-01", "rates": {"USD": {"purchase": 520.0, "sale": 530.0}}}
    rates_low = {"date": "2025-02-01", "rates": {"USD": {"purchase": 510.0, "sale": 520.0}}}

    with patched_httpx(rates_high, rates_low):
        result = await get_rate_change("USD", "2025-01-01", "2025-02-01")

    assert result["change"]["purchase"]["absolute"] == -10.0
    assert result["change"]["sale"]["absolute"] == -10.0


@pytest.mark.asyncio
async def test_get_rate_change_makes_two_calls():
    with patched_httpx(RATES_JAN, RATES_FEB) as mock_client:
        await get_rate_change("USD", "2025-01-01", "2025-02-01")
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_historical_average():
    entries = [
        {"date": "2025-01-01", "rates": {"USD": {"purchase": 500.0, "sale": 510.0}}},
        {"date": "2025-01-02", "rates": {"USD": {"purchase": 502.0, "sale": 512.0}}},
        {"date": "2025-01-03", "rates": {"USD": {"purchase": 504.0, "sale": 514.0}}},
    ]
    with patched_httpx(entries):
        result = await get_historical_average("USD", "2025-01-01", "2025-01-03")

    assert result["currency"] == "USD"
    assert result["days"] == 3
    assert result["average"]["purchase"] == round((500 + 502 + 504) / 3, 2)
    assert result["average"]["sale"] == round((510 + 512 + 514) / 3, 2)


@pytest.mark.asyncio
async def test_get_historical_average_empty_returns_none():
    with patched_httpx([]):
        result = await get_historical_average("USD", "2025-01-01", "2025-01-03")

    assert result["days"] == 0
    assert result["average"] is None


@pytest.mark.asyncio
async def test_api_error_surfaces_detail_message():
    error = make_error_response(404, "No exchange rate data published by BCCR for 2024-01-01")
    with patched_httpx(error):
        with pytest.raises(TicoRatesAPIError, match="No exchange rate data published by BCCR") as exc_info:
            await get_rates_for_date("2024-01-01", "USD")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_convert_unsupported_currency_raises_value_error():
    with patched_httpx(RATES_USD):
        with pytest.raises(ValueError, match="'XYZ'"):
            await convert_amount(100.0, "XYZ", "CRC")
