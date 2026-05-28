import asyncio
import json
import logging
from functools import cache
from pathlib import Path

import httpx

from ticorates.core.config import settings
from ticorates.core.exceptions import BCCRError, UnsupportedCurrencyError
from ticorates.models.domain import ExchangeRates, Rate
from ticorates.clients.indicators import CrossRateConfig, DirectConfig, IndicatorType

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 2


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

    async def fetch_rates_for_date(self, date: str) -> ExchangeRates:
        direct_rates = await self._fetch_direct_rates(date)
        cross_rates = await self._fetch_cross_rates(date, direct_rates)
        return ExchangeRates(date=date, rates={**direct_rates, **cross_rates})

    async def fetch_rate_for_currency(self, currency: str, date: str) -> ExchangeRates:
        currency = currency.upper()

        if currency not in self._indicators:
            raise UnsupportedCurrencyError(currency)

        config = self._indicators[currency]

        if config["type"] == IndicatorType.DIRECT:
            direct_config: DirectConfig = config  # type: ignore[assignment]
            rate = await self._fetch_direct_rate(direct_config, date)
        else:
            cross_config: CrossRateConfig = config  # type: ignore[assignment]
            base_config: DirectConfig = self._indicators["USD"]  # type: ignore[assignment]
            base_rate = await self._fetch_direct_rate(base_config, date)
            reference_value = await self._fetch_indicator(cross_config["reference_code"], date)
            rate = self._calculate_cross_rate(base_rate, reference_value, cross_config["usd_is_base"])

        return ExchangeRates(date=date, rates={currency: rate})

    async def _fetch_direct_rates(self, date: str) -> dict[str, Rate]:
        direct_items = [
            (currency, config)
            for currency, config in self._indicators.items()
            if config["type"] == IndicatorType.DIRECT
        ]
        results = await asyncio.gather(*[self._fetch_direct_rate(config, date) for _, config in direct_items])  # type: ignore[arg-type]
        return {currency: rate for (currency, _), rate in zip(direct_items, results)}

    async def _fetch_cross_rates(self, date: str, direct_rates: dict[str, Rate]) -> dict[str, Rate]:
        cross_items = [
            (currency, config)
            for currency, config in self._indicators.items()
            if config["type"] == IndicatorType.CROSS_RATE
        ]
        reference_values = await asyncio.gather(
            *[self._fetch_indicator(config["reference_code"], date) for _, config in cross_items]
        )
        return {
            currency: self._calculate_cross_rate(
                direct_rates["USD"], reference_value, config["usd_is_base"]
            )
            for (currency, config), reference_value in zip(cross_items, reference_values)
        }

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

    async def _request_with_retry(self, indicator_code: int, date: str) -> httpx.Response:
        bccr_date = date.replace("-", "/")
        for attempt in range(_MAX_RETRIES):
            async with self._semaphore:
                response = await self._client.get(
                    f"{settings.bccr_base_url}/indicadoresEconomicos/{indicator_code}/series",
                    params={"fechaInicio": bccr_date, "fechaFin": bccr_date, "idioma": "EN"},
                    headers={
                        "Authorization": f"Bearer {settings.bccr_api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/91.0.4472.124 Safari/537.36"
                        ),
                    },
                    timeout=30,
                )
            if response.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    wait = _BACKOFF_BASE**attempt
                    logger.warning("BCCR rate limit hit, retrying in %ds (attempt %d)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise BCCRError(f"BCCR rate limit exceeded after {_MAX_RETRIES} retries")
            response.raise_for_status()
            return response
        raise BCCRError(f"BCCR rate limit exceeded after {_MAX_RETRIES} retries")

    async def _fetch_indicator(self, indicator_code: int, date: str) -> float:
        logger.debug("Fetching indicator %s from BCCR for date %s", indicator_code, date)
        response = await self._request_with_retry(indicator_code, date)
        payload = response.json()

        if not payload.get("estado"):
            raise BCCRError(f"BCCR API error: {payload.get('mensaje')}")

        response_data = payload.get("datos", [])
        series = response_data[0].get("series", []) if response_data else []

        if not series:
            raise BCCRError(f"No data from BCCR for indicator {indicator_code} on {date}")

        return series[0]["valorDatoPorPeriodo"]
