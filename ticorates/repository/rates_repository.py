from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Session, select

from ticorates.models.database import CachedRate
from ticorates.models.domain import ExchangeRates, Rate


class RatesRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_rates_for_date(self, date: str, currency: str) -> ExchangeRates | None:
        query = (
            select(CachedRate)
            .where(CachedRate.date == date)
            .where(CachedRate.currency == currency.upper())
        )
        cached_rates = self.session.exec(query).all()

        if not cached_rates:
            return None

        rates = {row.currency: Rate(purchase=row.purchase, sale=row.sale) for row in cached_rates}
        return ExchangeRates(date=date, rates=rates)

    def save_rates(self, exchange_rates: ExchangeRates) -> None:
        for currency, rate in exchange_rates.rates.items():
            upsert_stmt = (
                insert(CachedRate)
                .values(
                    date=exchange_rates.date,
                    currency=currency,
                    purchase=rate.purchase,
                    sale=rate.sale,
                )
                .on_conflict_do_nothing(index_elements=["date", "currency"])
            )
            self.session.execute(upsert_stmt)

        self.session.commit()

    def get_rates_for_date_range(self, from_date: str, to_date: str, currency: str) -> list[ExchangeRates]:
        query = (
            select(CachedRate)
            .where(CachedRate.date >= from_date)
            .where(CachedRate.date <= to_date)
            .where(CachedRate.currency == currency.upper())
        )
        cached_rates = self.session.exec(query).all()

        return [
            ExchangeRates(date=row.date, rates={row.currency: Rate(purchase=row.purchase, sale=row.sale)})
            for row in sorted(cached_rates, key=lambda r: r.date)
        ]
