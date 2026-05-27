from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class CachedRate(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("date", "currency"),)

    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True)
    currency: str = Field(index=True)
    purchase: float
    sale: float
