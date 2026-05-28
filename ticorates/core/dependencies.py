from fastapi import Depends, Request

from ticorates.clients.bccr_client import BCCRClient
from ticorates.core.database import SessionFactory, get_session_factory
from ticorates.services.rates_service import RatesService


def get_bccr_client(request: Request) -> BCCRClient:
    return request.app.state.bccr_client


def get_rates_service(
    session_factory: SessionFactory = Depends(get_session_factory),
    bccr_client: BCCRClient = Depends(get_bccr_client),
) -> RatesService:
    return RatesService(session_factory, bccr_client)
