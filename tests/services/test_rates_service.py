from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ticorates.models.domain import ExchangeRates, Rate
from ticorates.services.rates_service import RatesService


def usd_rates(date: str = "2024-01-15") -> ExchangeRates:
    return ExchangeRates(date=date, rates={"USD": Rate(purchase=500.0, sale=510.0)})


def multi_rates(date: str = "2024-01-15") -> ExchangeRates:
    return ExchangeRates(
        date=date,
        rates={
            "USD": Rate(purchase=500.0, sale=510.0),
            "EUR": Rate(purchase=550.0, sale=560.0),
        },
    )


TWO_CURRENCIES = {"USD": "United States Dollar", "EUR": "Euro"}


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_bccr():
    client = AsyncMock()
    # enrich_descriptions is synchronous — override the AsyncMock default
    client.enrich_descriptions = MagicMock(side_effect=lambda er: er)
    return client


@pytest.fixture
def service(mock_repo, mock_bccr):
    return RatesService(mock_repo, mock_bccr)


# --- _dates_in_range ---


def test_dates_in_range_single_day():
    assert RatesService._dates_in_range("2024-01-15", "2024-01-15") == ["2024-01-15"]


def test_dates_in_range_multiple_days():
    result = RatesService._dates_in_range("2024-01-15", "2024-01-17")
    assert result == ["2024-01-15", "2024-01-16", "2024-01-17"]


def test_dates_in_range_reversed_returns_empty():
    assert RatesService._dates_in_range("2024-01-17", "2024-01-15") == []


# --- get_rates_for_date: cache hit ---


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_hit(service, mock_repo, mock_bccr):
    mock_repo.get_rates_for_date.return_value = usd_rates()

    await service.get_rates_for_date("2024-01-15", "USD")

    mock_bccr.fetch_rate_for_currency.assert_not_called()
    mock_bccr.fetch_rates_for_date.assert_not_called()
    mock_repo.save_rates.assert_not_called()


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_hit_returns_enriched(service, mock_repo, mock_bccr):
    cached = usd_rates()
    enriched = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0, description="US Dollar")})
    mock_repo.get_rates_for_date.return_value = cached
    mock_bccr.enrich_descriptions = MagicMock(return_value=enriched)

    result = await service.get_rates_for_date("2024-01-15", "USD")
    assert result is enriched


# --- get_rates_for_date: cache miss ---


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_miss_fetches_single_currency(service, mock_repo, mock_bccr):
    fetched = usd_rates()
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rate_for_currency.return_value = fetched

    await service.get_rates_for_date("2024-01-15", "USD")

    mock_bccr.fetch_rate_for_currency.assert_called_once_with("USD", "2024-01-15")
    mock_repo.save_rates.assert_called_once_with(fetched)


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_miss_fetches_all_currencies(service, mock_repo, mock_bccr):
    fetched = multi_rates()
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rates_for_date.return_value = fetched

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value=TWO_CURRENCIES):
        await service.get_rates_for_date("2024-01-15")

    mock_bccr.fetch_rates_for_date.assert_called_once_with("2024-01-15")
    mock_repo.save_rates.assert_called_once_with(fetched)


# --- get_rates_for_date: partial cache ---


@pytest.mark.asyncio
async def test_get_rates_for_date_partial_cache_triggers_full_fetch(service, mock_repo, mock_bccr):
    """Only USD cached, but all currencies requested → must re-fetch."""
    partial = usd_rates()  # only USD, missing EUR
    fetched = multi_rates()
    mock_repo.get_rates_for_date.return_value = partial
    mock_bccr.fetch_rates_for_date.return_value = fetched

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value=TWO_CURRENCIES):
        await service.get_rates_for_date("2024-01-15")

    mock_bccr.fetch_rates_for_date.assert_called_once()


@pytest.mark.asyncio
async def test_get_rates_for_date_full_cache_no_fetch(service, mock_repo, mock_bccr):
    """All requested currencies already cached → no BCCR call."""
    mock_repo.get_rates_for_date.return_value = multi_rates()

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value=TWO_CURRENCIES):
        await service.get_rates_for_date("2024-01-15")

    mock_bccr.fetch_rates_for_date.assert_not_called()
    mock_bccr.fetch_rate_for_currency.assert_not_called()


# --- get_latest_rates ---


@pytest.mark.asyncio
async def test_get_latest_rates_uses_today(service):
    with patch.object(service, "get_rates_for_date", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = usd_rates()
        await service.get_latest_rates("USD")

    mock_get.assert_called_once()
    args = mock_get.call_args.args
    assert args[1] == "USD"
    # The date arg should be a valid ISO date string
    from datetime import date as Date
    Date.fromisoformat(args[0])  # raises if invalid


# --- get_rates_for_date_range ---


@pytest.mark.asyncio
async def test_get_rates_for_date_range_all_cached(service, mock_repo, mock_bccr):
    cached = [usd_rates("2024-01-15"), usd_rates("2024-01-16")]
    mock_repo.get_rates_for_date_range.return_value = cached

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value={"USD": "Dollar"}):
        results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    mock_bccr.fetch_rate_for_currency.assert_not_called()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_rates_for_date_range_fetches_missing_dates(service, mock_repo, mock_bccr):
    only_15 = [usd_rates("2024-01-15")]
    both = [usd_rates("2024-01-15"), usd_rates("2024-01-16")]
    mock_repo.get_rates_for_date_range.side_effect = [only_15, both]
    mock_bccr.fetch_rate_for_currency.return_value = usd_rates("2024-01-16")

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value={"USD": "Dollar"}):
        results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    mock_bccr.fetch_rate_for_currency.assert_called_once_with("USD", "2024-01-16")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_rates_for_date_range_failed_fetch_doesnt_break_batch(service, mock_repo, mock_bccr):
    """A fetch error for one date shouldn't prevent other dates from being returned."""
    from ticorates.core.exceptions import BCCRError

    only_15 = [usd_rates("2024-01-15")]
    mock_repo.get_rates_for_date_range.side_effect = [only_15, only_15]
    mock_bccr.fetch_rate_for_currency.side_effect = BCCRError("BCCR down")

    with patch("ticorates.services.rates_service.BCCRClient.get_currencies", return_value={"USD": "Dollar"}):
        results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    # The cached date-15 should still be returned even though date-16 failed
    assert len(results) == 1
    assert results[0].date == "2024-01-15"
