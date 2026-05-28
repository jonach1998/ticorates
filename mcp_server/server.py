import asyncio
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TicoRates")

_BASE_URL = os.environ.get("TICORATES_BASE_URL", "https://ticorates.dev")
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class TicoRatesAPIError(RuntimeError):
    """Raised when the TicoRates API returns a non-success HTTP response.

    Carries the upstream ``status_code`` so callers can distinguish between
    client errors (4xx), gateway errors (5xx from BCCR), and our own faults.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"TicoRates API error {status_code}: {detail}")
        self.status_code = status_code


async def _api_get(path: str, params: dict | None = None) -> dict | list:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        kwargs = {"params": params} if params is not None else {}
        response = await client.get(f"{_BASE_URL}{path}", **kwargs)
    if not response.is_success:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise TicoRatesAPIError(response.status_code, detail)
    return response.json()


@mcp.tool()
async def get_supported_currencies() -> dict:
    """List all currencies supported by TicoRates with their descriptions.
    Use this to discover available currency codes before making other requests.
    Returns a dict of currency code → description (e.g. {"USD": "United States Dollar"})."""
    return await _api_get("/currencies")


@mcp.tool()
async def get_latest_rates(currency: str) -> dict:
    """Get today's exchange rates from Banco Central de Costa Rica (BCCR) for a specific currency.
    Currency codes follow ISO 4217 (e.g. USD, EUR, JPY, GBP).
    Use get_supported_currencies first to discover available codes."""
    return await _api_get("/rates/latest", {"currency": currency})


@mcp.tool()
async def get_rates_for_date(date: str, currency: str) -> dict:
    """Get exchange rates from BCCR for a specific date and currency (format: YYYY-MM-DD).
    Currency codes follow ISO 4217 (e.g. USD, EUR).
    Results are cached — historical dates are served instantly after the first request."""
    return await _api_get("/rates", {"date": date, "currency": currency})


@mcp.tool()
async def get_rates_for_date_range(from_date: str, to_date: str, currency: str) -> list:
    """Get exchange rates from BCCR for a date range and currency (format: YYYY-MM-DD). Returns one entry per day.
    Currency codes follow ISO 4217 (e.g. USD, EUR)."""
    return await _api_get("/rates", {"from": from_date, "to": to_date, "currency": currency})


@mcp.tool()
async def convert_amount(amount: float, from_currency: str, to_currency: str, date: str | None = None) -> dict:
    """Convert an amount from one currency to another using BCCR official exchange rates.
    Currency codes follow ISO 4217 (e.g. USD, EUR, CRC). Date format: YYYY-MM-DD (omit for today).
    Cross-currency conversions (e.g. EUR → USD) go through CRC automatically.
    Uses purchase rate when selling foreign currency, sale rate when buying foreign currency."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return {
            "date": None,
            "from": {"currency": from_currency, "amount": amount},
            "to": {"currency": to_currency, "amount": amount},
        }

    if from_currency == "CRC":
        currencies_needed = [to_currency]
    elif to_currency == "CRC":
        currencies_needed = [from_currency]
    else:
        currencies_needed = [from_currency, to_currency]  # cross-rate: fetch both in parallel

    path = "/rates" if date else "/rates/latest"
    params_base = {"date": date} if date else {}

    responses = await asyncio.gather(*[
        _api_get(path, {**params_base, "currency": c}) for c in currencies_needed
    ])

    rate_date = responses[0]["date"]
    rates = {k: v for r in responses for k, v in r["rates"].items()}

    try:
        if from_currency == "CRC":
            converted_amount = amount / rates[to_currency]["sale"]
        elif to_currency == "CRC":
            converted_amount = amount * rates[from_currency]["purchase"]
        else:
            crc_amount = amount * rates[from_currency]["purchase"]
            converted_amount = crc_amount / rates[to_currency]["sale"]
    except KeyError as exc:
        raise ValueError(f"Currency {exc} is not supported or has no rate data for the requested date") from exc

    return {
        "date": rate_date,
        "from": {"currency": from_currency, "amount": amount},
        "to": {"currency": to_currency, "amount": round(converted_amount, 2)},
    }


@mcp.tool()
async def get_rate_change(currency: str, from_date: str, to_date: str) -> dict:
    """Get how much an exchange rate changed between two dates.
    Returns absolute and percentage change for both purchase and sale rates.
    Useful for answering 'how much has the dollar gone up this month?'
    Date format: YYYY-MM-DD. Currency codes follow ISO 4217 (e.g. USD, EUR)."""
    currency = currency.upper()

    rates_on_from_date, rates_on_to_date = await asyncio.gather(
        _api_get("/rates", {"date": from_date, "currency": currency}),
        _api_get("/rates", {"date": to_date, "currency": currency}),
    )

    rate_from = rates_on_from_date["rates"][currency]
    rate_to = rates_on_to_date["rates"][currency]

    purchase_change = round(rate_to["purchase"] - rate_from["purchase"], 2)
    sale_change = round(rate_to["sale"] - rate_from["sale"], 2)

    return {
        "currency": currency,
        "from_date": from_date,
        "to_date": to_date,
        "from_rates": {"purchase": rate_from["purchase"], "sale": rate_from["sale"]},
        "to_rates": {"purchase": rate_to["purchase"], "sale": rate_to["sale"]},
        "change": {
            "purchase": {"absolute": purchase_change, "percentage": round(purchase_change / rate_from["purchase"] * 100, 4)},
            "sale": {"absolute": sale_change, "percentage": round(sale_change / rate_from["sale"] * 100, 4)},
        },
    }


@mcp.tool()
async def get_historical_average(currency: str, from_date: str, to_date: str) -> dict:
    """Get the average exchange rate for a currency over a date range.
    Useful for accounting, tax reporting, and financial planning.
    Only includes days with available BCCR data (excludes weekends and holidays).
    Date format: YYYY-MM-DD. Currency codes follow ISO 4217 (e.g. USD, EUR)."""
    currency = currency.upper()

    daily_rates = await _api_get("/rates", {"from": from_date, "to": to_date, "currency": currency})

    if not daily_rates:
        return {"currency": currency, "from_date": from_date, "to_date": to_date, "days": 0, "average": None}

    avg_purchase = round(sum(day["rates"][currency]["purchase"] for day in daily_rates) / len(daily_rates), 2)
    avg_sale = round(sum(day["rates"][currency]["sale"] for day in daily_rates) / len(daily_rates), 2)

    return {
        "currency": currency,
        "from_date": from_date,
        "to_date": to_date,
        "days": len(daily_rates),
        "average": {"purchase": avg_purchase, "sale": avg_sale},
    }


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
