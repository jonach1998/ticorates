import logging
from contextlib import asynccontextmanager
from importlib.metadata import version as _version

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ticorates.api.routes import currencies_router, rates_router
from ticorates.core.database import create_tables
from ticorates.core.exceptions import BCCRError, UnsupportedCurrencyError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    async with httpx.AsyncClient() as http_client:
        app.state.http_client = http_client
        yield


app = FastAPI(
    title="TicoRates",
    description="Public exchange rate API for Costa Rica, powered by BCCR",
    version=_version("ticorates-mcp"),
    lifespan=lifespan,
)

app.include_router(rates_router)
app.include_router(currencies_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.exception_handler(UnsupportedCurrencyError)
async def unsupported_currency_handler(request: Request, exc: UnsupportedCurrencyError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(BCCRError)
async def bccr_error_handler(request: Request, exc: BCCRError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})
