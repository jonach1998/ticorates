from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ticorates.core.dependencies import get_rates_service
from ticorates.core.exceptions import BCCRError, NoDataError, UnsupportedCurrencyError
from ticorates.main import app
from ticorates.models.domain import ExchangeRates, Rate


def make_exchange_rates(date: str = "2024-01-15") -> ExchangeRates:
    return ExchangeRates(
        date=date,
        rates={"USD": Rate(purchase=500.0, sale=510.0, description="United States Dollar")},
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    service = AsyncMock()
    service.get_latest_rates.return_value = make_exchange_rates()
    service.get_rates_for_date.return_value = make_exchange_rates()
    service.get_rates_for_date_range.return_value = [make_exchange_rates("2024-01-15"), make_exchange_rates("2024-01-16")]
    return service


@pytest.fixture
def client(mock_service) -> TestClient:
    app.dependency_overrides[get_rates_service] = lambda: mock_service
    with patch("ticorates.main.create_tables"):  # avoid creating the DB file during tests
        with TestClient(app) as test_client:
            yield test_client
    app.dependency_overrides.clear()


def test_get_supported_currencies_returns_dict(client):
    response = client.get("/currencies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "USD" in data
    assert isinstance(data["USD"], str)


def test_get_supported_currencies_includes_descriptions(client):
    response = client.get("/currencies")
    data = response.json()
    assert "Dollar" in data["USD"]


def test_get_latest_rates_requires_currency(client):
    response = client.get("/rates/latest")
    assert response.status_code == 422


def test_get_latest_rates_with_currency(client, mock_service):
    response = client.get("/rates/latest?currency=USD")
    assert response.status_code == 200
    data = response.json()
    assert "date" in data
    assert "rates" in data
    mock_service.get_latest_rates.assert_called_once_with("USD")


def test_get_latest_rates_response_shape(client):
    response = client.get("/rates/latest?currency=USD")
    data = response.json()
    assert data["date"] == "2024-01-15"
    assert data["rates"]["USD"]["purchase"] == 500.0
    assert data["rates"]["USD"]["sale"] == 510.0


def test_get_rates_for_date_requires_currency(client):
    response = client.get("/rates?date=2024-01-15")
    assert response.status_code == 422


def test_get_rates_for_date(client, mock_service):
    response = client.get("/rates?date=2024-01-15&currency=USD")
    assert response.status_code == 200
    mock_service.get_rates_for_date.assert_called_once_with("2024-01-15", "USD")


def test_get_rates_for_date_invalid_format_returns_422(client):
    response = client.get("/rates?date=not-a-date&currency=USD")
    assert response.status_code == 422


def test_get_rates_for_date_invalid_format_dd_mm_yyyy_returns_422(client):
    """European format should not be accepted — only ISO 8601."""
    response = client.get("/rates?date=15/01/2024&currency=USD")
    assert response.status_code == 422


def test_get_rates_for_date_range_requires_currency(client):
    response = client.get("/rates?from=2024-01-15&to=2024-01-16")
    assert response.status_code == 422


def test_get_rates_for_date_range(client, mock_service):
    response = client.get("/rates?from=2024-01-15&to=2024-01-16&currency=USD")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    mock_service.get_rates_for_date_range.assert_called_once_with("2024-01-15", "2024-01-16", "USD")


def test_get_rates_for_date_range_with_currency(client, mock_service):
    response = client.get("/rates?from=2024-01-15&to=2024-01-16&currency=EUR")
    assert response.status_code == 200
    mock_service.get_rates_for_date_range.assert_called_once_with("2024-01-15", "2024-01-16", "EUR")


def test_get_rates_for_date_range_invalid_date_returns_422(client):
    response = client.get("/rates?from=bad&to=2024-01-16&currency=USD")
    assert response.status_code == 422


def test_get_rates_no_params_returns_422(client):
    """No currency and no date → 422 (currency is now required)."""
    response = client.get("/rates")
    assert response.status_code == 422


def test_get_rates_only_from_no_to_returns_400(client):
    """currency present, 'from' without 'to' → falls through to date check → 400."""
    response = client.get("/rates?from=2024-01-15&currency=USD")
    assert response.status_code == 400


def test_unsupported_currency_returns_400(client, mock_service):
    mock_service.get_latest_rates.side_effect = UnsupportedCurrencyError("XYZ")
    response = client.get("/rates/latest?currency=XYZ")
    assert response.status_code == 400
    assert "XYZ" in response.json()["detail"]


def test_no_data_returns_404(client, mock_service):
    mock_service.get_latest_rates.side_effect = NoDataError("2024-01-15")
    response = client.get("/rates/latest?currency=USD")
    assert response.status_code == 404
    assert "2024-01-15" in response.json()["detail"]


def test_bccr_error_returns_502(client, mock_service):
    mock_service.get_latest_rates.side_effect = BCCRError("upstream failure")
    response = client.get("/rates/latest?currency=USD")
    assert response.status_code == 502
    assert "upstream failure" in response.json()["detail"]
