from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.dependencies import get_rates_service
from ticorates.models.domain import ExchangeRates
from ticorates.services.rates_service import RatesService

rates_router = APIRouter(prefix="/rates", tags=["rates"])
currencies_router = APIRouter(prefix="/currencies", tags=["currencies"])


@currencies_router.get("", response_model=dict[str, str])
async def get_supported_currencies():
    return BCCRClient.get_currencies()


@rates_router.get("/latest", response_model=ExchangeRates)
async def get_latest_rates(
    currency: str = Query(description="Currency code (e.g. USD, EUR)"),
    service: RatesService = Depends(get_rates_service),
):
    return await service.get_latest_rates(currency)


@rates_router.get("", response_model=ExchangeRates | list[ExchangeRates])
async def get_rates(
    currency: str = Query(description="Currency code (e.g. USD, EUR)"),
    date: Date | None = Query(default=None, description="Single date (YYYY-MM-DD)"),
    from_date: Date | None = Query(default=None, alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: Date | None = Query(default=None, alias="to", description="End date (YYYY-MM-DD)"),
    service: RatesService = Depends(get_rates_service),
):
    if from_date and to_date:
        return await service.get_rates_for_date_range(from_date.isoformat(), to_date.isoformat(), currency)

    if date:
        return await service.get_rates_for_date(date.isoformat(), currency)

    raise HTTPException(status_code=400, detail="Provide 'date' or 'from' and 'to' parameters")
