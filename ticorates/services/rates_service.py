import asyncio
import logging
from datetime import date as Date
from datetime import timedelta

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.database import SessionFactory
from ticorates.core.exceptions import BCCRError, NoDataError
from ticorates.models.domain import ExchangeRates
from ticorates.repository.rates_repository import RatesRepository

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_FETCHES = 5
_MAX_FALLBACK_DAYS = 7


class RatesService:
    def __init__(self, session_factory: SessionFactory, bccr_client: BCCRClient):
        self._session_factory = session_factory
        self._bccr_client = bccr_client

    async def get_latest_rates(self, currency: str) -> ExchangeRates:
        today = Date.today().isoformat()
        return await self.get_rates_for_date(today, currency)

    async def get_rates_for_date(self, date: str, currency: str) -> ExchangeRates:
        fallback_date = Date.fromisoformat(date)
        for _ in range(_MAX_FALLBACK_DAYS):
            try:
                return await self._fetch_for_date(fallback_date.isoformat(), currency)
            except NoDataError:
                logger.info("No BCCR data for %s, trying previous day", fallback_date.isoformat())
                fallback_date -= timedelta(days=1)
        raise NoDataError(date)

    async def _fetch_for_date(self, date: str, currency: str) -> ExchangeRates:
        with self._session_factory() as session:
            cached = RatesRepository(session).get_rates_for_date(date, currency)

        if cached:
            logger.info("Cache hit for date=%s currency=%s", date, currency)
            return self._bccr_client.enrich_descriptions(cached)

        logger.info("Cache miss for date=%s currency=%s — fetching from BCCR", date, currency)
        fetched = await self._bccr_client.fetch_rate_for_currency(currency, date)

        with self._session_factory() as session:
            RatesRepository(session).save_rates(fetched)

        return self._bccr_client.enrich_descriptions(fetched)

    async def get_rates_for_date_range(self, from_date: str, to_date: str, currency: str) -> list[ExchangeRates]:
        all_dates = self._dates_in_range(from_date, to_date)

        with self._session_factory() as session:
            cached_entries = RatesRepository(session).get_rates_for_date_range(from_date, to_date, currency)

        cached_dates = {entry.date for entry in cached_entries}
        missing_dates = [d for d in all_dates if d not in cached_dates]

        if missing_dates:
            logger.info("Fetching %d missing dates from BCCR for range %s to %s", len(missing_dates), from_date, to_date)
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
            fetch_outcomes = await asyncio.gather(
                *[self._fetch_and_save(d, currency, semaphore) for d in missing_dates],
                return_exceptions=True,
            )
            for date, fetch_outcome in zip(missing_dates, fetch_outcomes):
                if isinstance(fetch_outcome, BaseException):
                    logger.error("Unexpected error fetching rates for %s: %s", date, fetch_outcome, exc_info=fetch_outcome)

            with self._session_factory() as session:
                cached_entries = RatesRepository(session).get_rates_for_date_range(from_date, to_date, currency)

        return [self._bccr_client.enrich_descriptions(entry) for entry in cached_entries]

    async def _fetch_and_save(self, date: str, currency: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                fetched = await self._bccr_client.fetch_rate_for_currency(currency, date)
                with self._session_factory() as session:
                    RatesRepository(session).save_rates(fetched)
            except (BCCRError, NoDataError) as exc:
                logger.warning("Could not fetch BCCR rates for %s: %s", date, exc)

    @staticmethod
    def _dates_in_range(from_date: str, to_date: str) -> list[str]:
        start = Date.fromisoformat(from_date)
        end = Date.fromisoformat(to_date)
        span = (end - start).days
        return [(start + timedelta(days=offset)).isoformat() for offset in range(span + 1)]
