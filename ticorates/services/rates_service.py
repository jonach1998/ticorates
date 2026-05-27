import asyncio
import logging
from datetime import date as Date
from datetime import timedelta

from ticorates.clients.bccr_client import BCCRClient
from ticorates.models.domain import ExchangeRates
from ticorates.repository.rates_repository import RatesRepository

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_FETCHES = 5


class RatesService:
    def __init__(self, repository: RatesRepository, bccr_client: BCCRClient):
        self.repository = repository
        self.bccr_client = bccr_client

    async def get_latest_rates(self, currency: str | None = None) -> ExchangeRates:
        today = Date.today().isoformat()
        return await self.get_rates_for_date(today, currency)

    async def get_rates_for_date(self, date: str, currency: str | None = None) -> ExchangeRates:
        expected_currencies = {currency.upper()} if currency else set(BCCRClient.get_currencies().keys())

        cached = self.repository.get_rates_for_date(date, currency)
        if cached and expected_currencies.issubset(cached.rates.keys()):
            logger.info("Cache hit for date=%s currency=%s", date, currency)
            return self.bccr_client.enrich_descriptions(cached)

        logger.info("Cache miss for date=%s currency=%s — fetching from BCCR", date, currency)
        if currency:
            fetched = await self.bccr_client.fetch_rate_for_currency(currency, date)
        else:
            fetched = await self.bccr_client.fetch_rates_for_date(date)

        self.repository.save_rates(fetched)
        return self.bccr_client.enrich_descriptions(fetched)

    async def get_rates_for_date_range(self, from_date: str, to_date: str, currency: str | None = None) -> list[ExchangeRates]:
        all_dates = self._dates_in_range(from_date, to_date)
        expected_currencies = {currency.upper()} if currency else set(BCCRClient.get_currencies().keys())

        cached_results = self.repository.get_rates_for_date_range(from_date, to_date, currency)
        fully_cached_dates = {er.date for er in cached_results if expected_currencies.issubset(er.rates.keys())}
        missing_dates = [d for d in all_dates if d not in fully_cached_dates]

        if missing_dates:
            logger.info("Fetching %d missing dates from BCCR for range %s to %s", len(missing_dates), from_date, to_date)
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
            await asyncio.gather(
                *[self._fetch_and_save(d, currency, semaphore) for d in missing_dates],
                return_exceptions=True,
            )
            cached_results = self.repository.get_rates_for_date_range(from_date, to_date, currency)

        return [self.bccr_client.enrich_descriptions(er) for er in cached_results]

    async def _fetch_and_save(self, date: str, currency: str | None, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                if currency:
                    fetched = await self.bccr_client.fetch_rate_for_currency(currency, date)
                else:
                    fetched = await self.bccr_client.fetch_rates_for_date(date)
                self.repository.save_rates(fetched)
            except Exception as exc:
                logger.warning("Could not fetch BCCR rates for %s: %s", date, exc)

    @staticmethod
    def _dates_in_range(from_date: str, to_date: str) -> list[str]:
        start = Date.fromisoformat(from_date)
        end = Date.fromisoformat(to_date)
        days = []
        current = start
        while current <= end:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days
