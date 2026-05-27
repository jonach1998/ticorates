import httpx
from fastapi import Depends, Request
from sqlmodel import Session

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.database import get_session
from ticorates.repository.rates_repository import RatesRepository
from ticorates.services.rates_service import RatesService


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_rates_service(
    session: Session = Depends(get_session),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> RatesService:
    repository = RatesRepository(session)
    bccr_client = BCCRClient(http_client)
    return RatesService(repository, bccr_client)
