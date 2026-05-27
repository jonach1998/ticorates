from pydantic import BaseModel


class Rate(BaseModel):
    purchase: float
    sale: float
    description: str | None = None


class ExchangeRates(BaseModel):
    date: str
    rates: dict[str, Rate]
