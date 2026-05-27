class UnsupportedCurrencyError(Exception):
    def __init__(self, currency: str):
        self.currency = currency
        super().__init__(f"Currency '{currency}' is not supported")


class BCCRError(Exception):
    pass
