from enum import StrEnum
from typing import Literal, TypedDict


class IndicatorType(StrEnum):
    DIRECT = "direct"
    CROSS_RATE = "cross_rate"


class DirectConfig(TypedDict):
    type: Literal["direct"]
    purchase: int
    sale: int
    description: str


class CrossRateConfig(TypedDict):
    type: Literal["cross_rate"]
    reference_code: int
    usd_is_base: bool
    description: str
