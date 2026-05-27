import asyncio
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TicoRates")

_BASE_URL = os.environ.get("TICORATES_BASE_URL", "https://ticorates.dev")


@mcp.tool()
async def get_supported_currencies() -> dict:
    """List all currencies supported by TicoRates with their descriptions.
    Use this to discover available currency codes before making other requests.
    Returns a dict of currency code → description (e.g. {"USD": "United States Dollar"})."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{_BASE_URL}/currencies")
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def get_latest_rates(currency: str | None = None) -> dict:
    """Get today's exchange rates from Banco Central de Costa Rica (BCCR).
    Supports 40+ currencies. If currency is omitted, returns all available currencies.
    Currency codes follow ISO 4217 (e.g. USD, EUR, JPY, GBP)."""
    params = {"currency": currency} if currency else {}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{_BASE_URL}/rates/latest", params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def get_rates_for_date(date: str, currency: str | None = None) -> dict:
    """Get exchange rates from BCCR for a specific date (format: YYYY-MM-DD).
    Supports 40+ currencies. If currency is omitted, returns all available currencies.
    Results are cached — historical dates are served instantly after the first request."""
    params = {"date": date}
    if currency:
        params["currency"] = currency
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{_BASE_URL}/rates", params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def get_rates_for_date_range(from_date: str, to_date: str, currency: str | None = None) -> list:
    """Get exchange rates from BCCR for a date range (format: YYYY-MM-DD). Returns one entry per day.
    Supports 40+ currencies. If currency is omitted, returns all available currencies per day."""
    params = {"from": from_date, "to": to_date}
    if currency:
        params["currency"] = currency
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{_BASE_URL}/rates", params=params)
        response.raise_for_status()
        return response.json()


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

    async with httpx.AsyncClient() as client:
        if date:
            response = await client.get(f"{_BASE_URL}/rates", params={"date": date})
        else:
            response = await client.get(f"{_BASE_URL}/rates/latest")
        response.raise_for_status()
        data = response.json()

    rates = data["rates"]

    if from_currency == "CRC":
        result = amount / rates[to_currency]["sale"]
    elif to_currency == "CRC":
        result = amount * rates[from_currency]["purchase"]
    else:
        crc_amount = amount * rates[from_currency]["purchase"]
        result = crc_amount / rates[to_currency]["sale"]

    return {
        "date": data["date"],
        "from": {"currency": from_currency, "amount": amount},
        "to": {"currency": to_currency, "amount": round(result, 2)},
    }


@mcp.tool()
async def get_rate_change(currency: str, from_date: str, to_date: str) -> dict:
    """Get how much an exchange rate changed between two dates.
    Returns absolute and percentage change for both purchase and sale rates.
    Useful for answering 'how much has the dollar gone up this month?'
    Date format: YYYY-MM-DD. Currency codes follow ISO 4217 (e.g. USD, EUR)."""
    currency = currency.upper()

    async with httpx.AsyncClient() as client:
        r1, r2 = await asyncio.gather(
            client.get(f"{_BASE_URL}/rates", params={"date": from_date, "currency": currency}),
            client.get(f"{_BASE_URL}/rates", params={"date": to_date, "currency": currency}),
        )
        r1.raise_for_status()
        r2.raise_for_status()

    rate_from = r1.json()["rates"][currency]
    rate_to = r2.json()["rates"][currency]

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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_BASE_URL}/rates",
            params={"from": from_date, "to": to_date, "currency": currency},
        )
        response.raise_for_status()

    entries = response.json()

    if not entries:
        return {"currency": currency, "from_date": from_date, "to_date": to_date, "days": 0, "average": None}

    avg_purchase = round(sum(e["rates"][currency]["purchase"] for e in entries) / len(entries), 2)
    avg_sale = round(sum(e["rates"][currency]["sale"] for e in entries) / len(entries), 2)

    return {
        "currency": currency,
        "from_date": from_date,
        "to_date": to_date,
        "days": len(entries),
        "average": {"purchase": avg_purchase, "sale": avg_sale},
    }


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
