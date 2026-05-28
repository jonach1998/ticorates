# TicoRates 🇨🇷

[![Test & Publish](https://github.com/jonach1998/ticorates/actions/workflows/test-and-publish.yml/badge.svg)](https://github.com/jonach1998/ticorates/actions/workflows/test-and-publish.yml)
[![PyPI](https://img.shields.io/pypi/v/ticorates-mcp)](https://pypi.org/project/ticorates-mcp/)
[![Docker Pulls](https://img.shields.io/docker/pulls/jonach1998/ticorates)](https://hub.docker.com/r/jonach1998/ticorates)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Free, open exchange rate API for Costa Rica — powered by BCCR. No sign-up, no token, ready to use.

**Live server → `https://ticorates.dev` — free for everyone, no API key required.**

## How it works

1. **Request** — you call any endpoint with a date and currency code.
2. **Cache check** — if the rate is already in the database, it's returned instantly.
3. **BCCR fetch** — on a cache miss, rates are fetched from Banco Central de Costa Rica in real time.
4. **Store & serve** — the result is cached in SQLite for all future requests to the same date.

Historical dates are served from cache after the first request. Concurrent requests for the same date are deduplicated — only one BCCR call is made regardless of how many clients ask simultaneously.

## Try it now

No installation. No registration. Paste and run:

```bash
# Today's USD rate
curl "https://ticorates.dev/rates/latest?currency=USD"

# Rate on a specific date
curl "https://ticorates.dev/rates?date=2025-01-15&currency=USD"

# Last 30 days
curl "https://ticorates.dev/rates?from=2025-04-01&to=2025-04-30&currency=USD"

# All supported currencies
curl https://ticorates.dev/currencies
```

Interactive docs → **[ticorates.dev/docs](https://ticorates.dev/docs)**

## Features

- **REST API** — simple HTTP endpoints, no authentication required
- **43 currencies** — USD, EUR, GBP, JPY, CAD, AUD, CHF, and more
- **On-demand caching** — rates are fetched from BCCR on first request and served instantly after
- **Historical rates** — query any date or date range going back years
- **MCP server** — native integration with Claude, Cursor, Windsurf, and other AI tools
- **Self-hosted** — Docker image available for `linux/amd64` and `linux/arm64`

## Table of Contents

- [API Reference](#api-reference)
- [MCP Server](#mcp-server)
- [Self-Hosting](#self-hosting)
- [Development](#development)

---

## API Reference

**Base URL:** `https://ticorates.dev`  
**Interactive docs:** `https://ticorates.dev/docs`

### `GET /currencies`

Returns all supported currency codes and their full names.

```
GET /currencies
```

**Response**

```json
{
  "USD": "United States Dollar",
  "EUR": "Euro (European Union)",
  "GBP": "British Pound Sterling (United Kingdom)",
  "JPY": "Japanese Yen (Japan)"
}
```

### `GET /rates/latest`

Returns today's exchange rate from BCCR for a specific currency.

| Parameter  | Type   | Required | Description                           |
|------------|--------|----------|---------------------------------------|
| `currency` | string | **Yes**  | Currency code (e.g. `USD`, `EUR`)     |

```
GET /rates/latest?currency=USD
```

**Response**

```json
{
  "date": "2025-05-27",
  "rates": {
    "USD": {
      "purchase": 512.50,
      "sale": 519.75,
      "description": "United States Dollar"
    }
  }
}
```

### `GET /rates`

Returns rates for a specific date or date range. Provide either `date` or both `from` + `to`.

| Parameter  | Type   | Required | Description                             |
|------------|--------|----------|-----------------------------------------|
| `currency` | string | **Yes**  | Currency code (e.g. `USD`, `EUR`)       |
| `date`     | string | No*      | Single date in `YYYY-MM-DD` format      |
| `from`     | string | No*      | Start of range in `YYYY-MM-DD` format   |
| `to`       | string | No*      | End of range in `YYYY-MM-DD` format     |

*Either `date` or both `from` + `to` must be provided.

```
GET /rates?date=2025-01-15&currency=EUR
GET /rates?from=2025-01-01&to=2025-01-31&currency=USD
```

A single-date request returns an object. A date-range request returns an array sorted by date.

**Response — single date**

```json
{
  "date": "2025-01-15",
  "rates": {
    "USD": { "purchase": 510.25, "sale": 517.50, "description": "United States Dollar" }
  }
}
```

**Response — date range**

```json
[
  {
    "date": "2025-01-01",
    "rates": { "USD": { "purchase": 508.00, "sale": 515.00, "description": "United States Dollar" } }
  },
  {
    "date": "2025-01-02",
    "rates": { "USD": { "purchase": 509.50, "sale": 516.75, "description": "United States Dollar" } }
  }
]
```

### Weekends & holidays

BCCR only publishes rates on business days. TicoRates handles this transparently:

- **Single date** — if you request a weekend or holiday, the API returns the most
  recent business day's rate (looking back up to a week). The `date` field in the
  response reflects the **actual** date returned, not the one requested. Requesting
  `?date=2025-05-25` (Sunday) returns `{ "date": "2025-05-23", ... }`.
- **Date range** — days with no published data are simply omitted from the array,
  so a 14-day range may return fewer than 14 entries.

### `GET /health`

Health check endpoint. Returns `200 OK` when the service is running.

```json
{ "status": "ok" }
```

### Error responses

| Status | Condition                                                       |
|--------|-----------------------------------------------------------------|
| `400`  | Unsupported currency, or `date` / `from`+`to` not provided     |
| `404`  | No BCCR data published for the requested date                  |
| `422`  | Missing required `currency` parameter, or invalid date format  |
| `502`  | BCCR upstream error (rate limit or service unavailable)        |

---

## MCP Server

> **No API key required.** The MCP server connects to `https://ticorates.dev` by default — install it and it just works.

TicoRates includes an [MCP](https://modelcontextprotocol.io/) server that gives AI assistants direct access to Costa Rican exchange rates. Ask your AI questions like:

- *"What's today's dollar rate in Costa Rica?"*
- *"How much has the euro changed this month?"*
- *"Convert 500 USD to colones using today's rate."*
- *"What was the average dollar rate in Q1 2025?"*

### Available tools

| Tool                       | Description                                      |
|----------------------------|--------------------------------------------------|
| `get_supported_currencies` | List all available currency codes and names      |
| `get_latest_rates`         | Today's rate for a specific currency             |
| `get_rates_for_date`       | Historical rate for a specific date              |
| `get_rates_for_date_range` | Rates for a date range, one entry per day        |
| `convert_amount`           | Convert between any two currencies               |
| `get_rate_change`          | Absolute and percentage change between two dates |
| `get_historical_average`   | Average purchase/sale rate over a period         |

### Setup

The same config block works across all MCP-compatible clients. Pick yours below.

#### Claude Desktop

Edit `claude_desktop_config.json` and restart Claude Desktop.

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ticorates": {
      "command": "uvx",
      "args": ["ticorates-mcp"]
    }
  }
}
```

#### Claude Code

Run once in your terminal:

```bash
claude mcp add ticorates -- uvx ticorates-mcp
```

#### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ticorates": {
      "command": "uvx",
      "args": ["ticorates-mcp"]
    }
  }
}
```

Or go to **Settings → Cursor Settings → Features → MCP → Add MCP Server**.

#### Windsurf

Open the Cascade panel → **⚙ Settings → MCP Servers → Add**, then enter:

- **Command:** `uvx`
- **Args:** `ticorates-mcp`

#### OpenAI Codex CLI

```bash
codex mcp add ticorates -- uvx ticorates-mcp
```

#### Other clients

Any MCP-compatible client that supports `stdio` transport works with TicoRates. Use the same JSON config structure shown above.

### Pointing the MCP at a self-hosted instance

By default, `ticorates-mcp` connects to `https://ticorates.dev`. To use your own instance, set `TICORATES_BASE_URL` in your client's config:

```json
{
  "mcpServers": {
    "ticorates": {
      "command": "uvx",
      "args": ["ticorates-mcp"],
      "env": {
        "TICORATES_BASE_URL": "http://your-server:8000"
      }
    }
  }
}
```

---

## Self-Hosting

### Prerequisites

- Docker and Docker Compose
- A BCCR API key — register at the [BCCR developer portal](https://www.bccr.fi.cr/)

### Setup

**1. Create a `docker-compose.yml`:**

```yaml
services:
  ticorates:
    image: jonach1998/ticorates:latest
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      - TZ=America/Costa_Rica
    volumes:
      - ticorates_data:/app/data
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  ticorates_data:
```

**2. Create a `.env` file:**

```env
BCCR_API_KEY=your_token_here
BCCR_BASE_URL=https://apim.bccr.fi.cr/SDDE/api/Bccr.GE.SDDE.Publico.Indicadores.API

# Optional — change the SQLite database path (default: /app/data/ticorates.db)
# DATABASE_URL=sqlite:////custom/path/ticorates.db
```

**3. Start the service:**

```bash
docker compose up -d
```

The API will be available at `http://localhost:8000`.  
Interactive docs at `http://localhost:8000/docs`.

---

## Development

**Requirements:** Python 3.13+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone the repo and install dependencies
git clone https://github.com/jonach1998/ticorates
cd ticorates
uv sync --extra dev

# Copy and fill in your BCCR credentials
cp .env.example .env

# Run the API
uv run uvicorn ticorates.main:app --reload

# Run the MCP server
uv run ticorates-mcp

# Run unit tests (no credentials needed)
uv run python -m pytest

# Run the full stress test against the live BCCR API (requires .env)
uv run python tests/stress/stress_test.py
```

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jonach1998/ticorates&type=Date)](https://star-history.com/#jonach1998/ticorates&Date)

## License

MIT — see [LICENSE](LICENSE).
