import asyncio
import json
import logging
from functools import cache
from pathlib import Path

import httpx

from ticorates.clients.indicators import CrossRateConfig, DirectConfig, IndicatorType
from ticorates.core.config import settings
from ticorates.core.exceptions import BCCRError, NoDataError, UnsupportedCurrencyError
from ticorates.core.single_flight import SingleFlight
from ticorates.models.domain import ExchangeRates, Rate

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 2
_BCCR_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)


class BCCRClient:
    _INDICATORS_PATH = Path(__file__).parent / "indicators.json"

    @staticmethod
    @cache
    def _load_indicators() -> dict[str, DirectConfig | CrossRateConfig]:
        with open(BCCRClient._INDICATORS_PATH) as f:
            return json.load(f)

    @classmethod
    def get_currencies(cls) -> dict[str, str]:
        return {code: config["description"] for code, config in cls._load_indicators().items()}

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._indicators = self._load_indicators()
        self._semaphore = asyncio.Semaphore(5)
        self._single_flight = SingleFlight()

    async def fetch_rate_for_currency(self, currency: str, date: str) -> ExchangeRates:
        currency = currency.upper()

        if currency not in self._indicators:
            raise UnsupportedCurrencyError(currency)

        async def _fetch() -> ExchangeRates:
            config = self._indicators[currency]
            if config["type"] == IndicatorType.DIRECT:
                rate = await self._fetch_direct_rate(config, date)  # type: ignore[arg-type]
            else:
                cross_config: CrossRateConfig = config  # type: ignore[assignment]
                base_config: DirectConfig = self._indicators["USD"]  # type: ignore[assignment]
                base_rate = await self._fetch_direct_rate(base_config, date)
                reference_value = await self._fetch_indicator(cross_config["reference_code"], date)
                rate = self._calculate_cross_rate(base_rate, reference_value, cross_config["usd_is_base"])
            return ExchangeRates(date=date, rates={currency: rate})

        return await self._single_flight.execute(f"currency:{currency}:{date}", _fetch())

    def enrich_descriptions(self, exchange_rates: ExchangeRates) -> ExchangeRates:
        enriched_rates = {
            currency: Rate(
                purchase=rate.purchase,
                sale=rate.sale,
                description=self._indicators[currency]["description"] if currency in self._indicators else None,
            )
            for currency, rate in exchange_rates.rates.items()
        }
        return ExchangeRates(date=exchange_rates.date, rates=enriched_rates)

    async def _fetch_direct_rate(self, config: DirectConfig, date: str) -> Rate:
        purchase, sale = await asyncio.gather(
            self._fetch_indicator(config["purchase"], date),
            self._fetch_indicator(config["sale"], date),
        )
        return Rate(purchase=purchase, sale=sale)

    def _calculate_cross_rate(self, base_rate: Rate, reference_value: float, usd_is_base: bool) -> Rate:
        if usd_is_base:
            return Rate(
                purchase=round(base_rate.purchase / reference_value, 2),
                sale=round(base_rate.sale / reference_value, 2),
            )
        return Rate(
            purchase=round(reference_value * base_rate.purchase, 2),
            sale=round(reference_value * base_rate.sale, 2),
        )

    async def _fetch_indicator(self, indicator_code: int, date: str) -> float:
        logger.debug("Fetching indicator %s from BCCR for date %s", indicator_code, date)
        response = await self._request_with_retry(indicator_code, date)
        bccr_response = response.json()

        if not bccr_response.get("estado"):
            raise BCCRError(f"BCCR API error: {bccr_response.get('mensaje')}")

        indicator_entries = bccr_response.get("datos", [])
        first_entry = indicator_entries[0] if indicator_entries else {}
        series = first_entry.get("series", [])

        if not series:
            raise NoDataError(date)

        rate_value = series[0]["valorDatoPorPeriodo"]
        if rate_value is None:
            raise NoDataError(date)

        return float(rate_value)

    async def _request_with_retry(self, indicator_code: int, date: str) -> httpx.Response:
        bccr_date = date.replace("-", "/")
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._semaphore:
                    response = await self._client.get(
                        f"{settings.bccr_base_url}/indicadoresEconomicos/{indicator_code}/series",
                        params={"fechaInicio": bccr_date, "fechaFin": bccr_date, "idioma": "EN"},
                        headers={
                            "Authorization": f"Bearer {settings.bccr_api_key}",
                            "Content-Type": "application/json",
                            "User-Agent": _USER_AGENT,
                        },
                        timeout=_BCCR_TIMEOUT,
                    )
            except httpx.TimeoutException as exc:
                raise BCCRError("BCCR request timed out (connect=5s, read=60s)") from exc
            if response.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    backoff_seconds = _BACKOFF_BASE**attempt
                    logger.warning("BCCR rate limit hit, retrying in %ds (attempt %d)", backoff_seconds, attempt + 1)
                    await asyncio.sleep(backoff_seconds)
                    continue
                raise BCCRError(f"BCCR rate limit exceeded after {_MAX_RETRIES} retries", upstream_status=429)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise BCCRError("BCCR upstream error", upstream_status=exc.response.status_code) from exc
            return response
