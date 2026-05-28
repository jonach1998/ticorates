class UnsupportedCurrencyError(Exception):
    def __init__(self, currency: str):
        self.currency = currency
        super().__init__(f"Currency '{currency}' is not supported")


class BCCRError(Exception):
    def __init__(self, message: str, upstream_status: int | None = None):
        super().__init__(message)
        self.upstream_status = upstream_status


class NoDataError(Exception):
    def __init__(self, date: str):
        super().__init__(f"No exchange rate data published by BCCR for {date}")
