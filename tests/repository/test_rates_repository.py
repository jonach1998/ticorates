from unittest.mock import MagicMock

from ticorates.models.domain import ExchangeRates, Rate
from ticorates.repository.rates_repository import RatesRepository


def make_session() -> MagicMock:
    return MagicMock()


def make_row(date: str, currency: str, purchase: float, sale: float) -> MagicMock:
    row = MagicMock()
    row.date = date
    row.currency = currency
    row.purchase = purchase
    row.sale = sale
    return row


# --- get_rates_for_date ---


def test_get_rates_for_date_empty_returns_none():
    session = make_session()
    session.exec.return_value.all.return_value = []
    assert RatesRepository(session).get_rates_for_date("2024-01-15") is None


def test_get_rates_for_date_maps_rows_to_domain():
    session = make_session()
    session.exec.return_value.all.return_value = [make_row("2024-01-15", "USD", 500.0, 510.0)]
    result = RatesRepository(session).get_rates_for_date("2024-01-15")
    assert result.date == "2024-01-15"
    assert result.rates["USD"].purchase == 500.0
    assert result.rates["USD"].sale == 510.0


def test_get_rates_for_date_multiple_currencies():
    session = make_session()
    session.exec.return_value.all.return_value = [
        make_row("2024-01-15", "USD", 500.0, 510.0),
        make_row("2024-01-15", "EUR", 550.0, 560.0),
    ]
    result = RatesRepository(session).get_rates_for_date("2024-01-15")
    assert "USD" in result.rates
    assert "EUR" in result.rates


# --- save_rates ---


def test_save_rates_commits():
    session = make_session()
    rates = ExchangeRates(date="2024-01-15", rates={"USD": Rate(purchase=500.0, sale=510.0)})
    RatesRepository(session).save_rates(rates)
    session.commit.assert_called_once()


def test_save_rates_one_execute_per_currency():
    session = make_session()
    rates = ExchangeRates(
        date="2024-01-15",
        rates={
            "USD": Rate(purchase=500.0, sale=510.0),
            "EUR": Rate(purchase=550.0, sale=560.0),
            "GBP": Rate(purchase=630.0, sale=640.0),
        },
    )
    RatesRepository(session).save_rates(rates)
    assert session.execute.call_count == 3


# --- get_rates_for_date_range ---


def test_get_rates_for_date_range_empty_returns_empty_list():
    session = make_session()
    session.exec.return_value.all.return_value = []
    assert RatesRepository(session).get_rates_for_date_range("2024-01-15", "2024-01-17") == []


def test_get_rates_for_date_range_groups_by_date():
    session = make_session()
    session.exec.return_value.all.return_value = [
        make_row("2024-01-15", "USD", 500.0, 510.0),
        make_row("2024-01-16", "USD", 502.0, 512.0),
        make_row("2024-01-17", "USD", 504.0, 514.0),
    ]
    results = RatesRepository(session).get_rates_for_date_range("2024-01-15", "2024-01-17")
    assert len(results) == 3


def test_get_rates_for_date_range_sorted_by_date():
    session = make_session()
    session.exec.return_value.all.return_value = [
        make_row("2024-01-17", "USD", 504.0, 514.0),
        make_row("2024-01-15", "USD", 500.0, 510.0),
        make_row("2024-01-16", "USD", 502.0, 512.0),
    ]
    results = RatesRepository(session).get_rates_for_date_range("2024-01-15", "2024-01-17")
    assert [r.date for r in results] == ["2024-01-15", "2024-01-16", "2024-01-17"]
