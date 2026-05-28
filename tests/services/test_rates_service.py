from contextlib import contextmanager
from datetime import date as Date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ticorates.core.exceptions import BCCRError, NoDataError
from ticorates.models.domain import ExchangeRates, Rate
from ticorates.services.rates_service import RatesService


@contextmanager
def _mock_session():
    """Minimal session factory for tests — yields a throw-away mock session."""
    yield MagicMock()


def usd_rates(date: str = "2024-01-15") -> ExchangeRates:
    return ExchangeRates(date=date, rates={"USD": Rate(purchase=500.0, sale=510.0)})


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_bccr():
    client = AsyncMock()
    client.enrich_descriptions = MagicMock(side_effect=lambda er: er)
    return client


@pytest.fixture
def service(mock_repo, mock_bccr):
    with patch("ticorates.services.rates_service.RatesRepository", return_value=mock_repo):
        yield RatesService(_mock_session, mock_bccr)


def test_dates_in_range_single_day():
    assert RatesService._dates_in_range("2024-01-15", "2024-01-15") == ["2024-01-15"]


def test_dates_in_range_multiple_days():
    result = RatesService._dates_in_range("2024-01-15", "2024-01-17")
    assert result == ["2024-01-15", "2024-01-16", "2024-01-17"]


def test_dates_in_range_reversed_returns_empty():
    assert RatesService._dates_in_range("2024-01-17", "2024-01-15") == []


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_hit(service, mock_repo, mock_bccr):
    mock_repo.get_rates_for_date.return_value = usd_rates()

    await service.get_rates_for_date("2024-01-15", "USD")

    mock_bccr.fetch_rate_for_currency.assert_not_called()
    mock_repo.save_rates.assert_not_called()


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_hit_returns_enriched(service, mock_repo, mock_bccr):
    cached = usd_rates()
    enriched = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0, description="US Dollar")})
    mock_repo.get_rates_for_date.return_value = cached
    mock_bccr.enrich_descriptions = MagicMock(return_value=enriched)

    result = await service.get_rates_for_date("2024-01-15", "USD")
    assert result is enriched


@pytest.mark.asyncio
async def test_get_rates_for_date_cache_miss_fetches_currency(service, mock_repo, mock_bccr):
    fetched = usd_rates()
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rate_for_currency.return_value = fetched

    await service.get_rates_for_date("2024-01-15", "USD")

    mock_bccr.fetch_rate_for_currency.assert_called_once_with("USD", "2024-01-15")
    mock_repo.save_rates.assert_called_once_with(fetched)


@pytest.mark.asyncio
async def test_get_latest_rates_uses_today(service):
    with patch.object(service, "get_rates_for_date", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = usd_rates()
        await service.get_latest_rates("USD")

    mock_get.assert_called_once()
    args = mock_get.call_args.args
    assert args[1] == "USD"
    Date.fromisoformat(args[0])


@pytest.mark.asyncio
async def test_get_rates_for_date_range_all_cached(service, mock_repo, mock_bccr):
    cached = [usd_rates("2024-01-15"), usd_rates("2024-01-16")]
    mock_repo.get_rates_for_date_range.return_value = cached

    results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    mock_bccr.fetch_rate_for_currency.assert_not_called()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_rates_for_date_range_fetches_missing_dates(service, mock_repo, mock_bccr):
    only_15 = [usd_rates("2024-01-15")]
    both = [usd_rates("2024-01-15"), usd_rates("2024-01-16")]
    mock_repo.get_rates_for_date_range.side_effect = [only_15, both]
    mock_bccr.fetch_rate_for_currency.return_value = usd_rates("2024-01-16")

    results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    mock_bccr.fetch_rate_for_currency.assert_called_once_with("USD", "2024-01-16")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_rates_for_date_range_failed_fetch_doesnt_break_batch(service, mock_repo, mock_bccr):
    only_15 = [usd_rates("2024-01-15")]
    mock_repo.get_rates_for_date_range.side_effect = [only_15, only_15]
    mock_bccr.fetch_rate_for_currency.side_effect = BCCRError("BCCR down")

    results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    assert len(results) == 1
    assert results[0].date == "2024-01-15"


@pytest.mark.asyncio
async def test_get_rates_for_date_falls_back_to_previous_day_on_no_data(service, mock_repo, mock_bccr):
    prev_day = usd_rates("2024-01-14")
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rate_for_currency.side_effect = [NoDataError("2024-01-15"), prev_day]

    await service.get_rates_for_date("2024-01-15", "USD")

    calls = mock_bccr.fetch_rate_for_currency.call_args_list
    assert calls[0].args == ("USD", "2024-01-15")
    assert calls[1].args == ("USD", "2024-01-14")


@pytest.mark.asyncio
async def test_get_rates_for_date_fallback_result_has_actual_date(service, mock_repo, mock_bccr):
    prev_day = usd_rates("2024-01-14")
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rate_for_currency.side_effect = [NoDataError("2024-01-15"), prev_day]

    result = await service.get_rates_for_date("2024-01-15", "USD")

    assert result.date == "2024-01-14"


@pytest.mark.asyncio
async def test_get_rates_for_date_raises_no_data_after_7_failed_attempts(service, mock_repo, mock_bccr):
    mock_repo.get_rates_for_date.return_value = None
    mock_bccr.fetch_rate_for_currency.side_effect = NoDataError("no data")

    with pytest.raises(NoDataError):
        await service.get_rates_for_date("2024-01-15", "USD")

    assert mock_bccr.fetch_rate_for_currency.call_count == 7


@pytest.mark.asyncio
async def test_get_rates_for_date_range_no_data_skips_date(service, mock_repo, mock_bccr):
    only_15 = [usd_rates("2024-01-15")]
    mock_repo.get_rates_for_date_range.side_effect = [only_15, only_15]
    mock_bccr.fetch_rate_for_currency.side_effect = NoDataError("2024-01-16")

    results = await service.get_rates_for_date_range("2024-01-15", "2024-01-16", "USD")

    assert len(results) == 1
    assert results[0].date == "2024-01-15"
