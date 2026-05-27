# TicoRates

Public exchange rate API for Costa Rica, powered by [BCCR](https://www.bccr.fi.cr/) (Banco Central de Costa Rica). Supports 43 currencies with on-demand caching and a built-in MCP server for AI assistants.

- **REST API** — Simple HTTP endpoints, no authentication required
- **43 currencies** — USD, EUR, GBP, JPY, CAD, AUD, CHF, and more
- **On-demand caching** — rates are fetched from BCCR on first request and served instantly after
- **Historical rates** — query any date or date range going back years
- **MCP server** — native integration with Claude, Cursor, Windsurf, and other AI tools
- **Self-hosted** — Docker image available for `linux/amd64` and `linux/arm64`

---

## Table of Contents

- [API Reference](#api-reference)
- [MCP Server](#mcp-server)
- [Self-Hosting](#self-hosting)
- [Development](#development)

---

## API Reference

**Base URL:** `https://ticorates.dev`  
**Interactive docs:** `https://ticorates.dev/docs`

---

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

---

### `GET /rates/latest`

Returns today's exchange rates from BCCR. Omit `currency` to get all 43 currencies at once.

| Parameter  | Type   | Required | Description                           |
|------------|--------|----------|---------------------------------------|
| `currency` | string | No       | Filter to a single code (e.g. `USD`)  |

```
GET /rates/latest
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

---

### `GET /rates`

Returns rates for a specific date or date range. Provide either `date` or both `from` + `to`.

| Parameter  | Type   | Required | Description                             |
|------------|--------|----------|-----------------------------------------|
| `date`     | string | No*      | Single date in `YYYY-MM-DD` format      |
| `from`     | string | No*      | Start of range in `YYYY-MM-DD` format   |
| `to`       | string | No*      | End of range in `YYYY-MM-DD` format     |
| `currency` | string | No       | Filter to a single code (e.g. `EUR`)    |

*Either `date` or both `from` + `to` must be provided.

```
GET /rates?date=2025-01-15
GET /rates?date=2025-01-15&currency=EUR
GET /rates?from=2025-01-01&to=2025-01-31
GET /rates?from=2025-01-01&to=2025-01-31&currency=USD
```

A single-date request returns an object. A date-range request returns an array sorted by date.

**Response — single date**

```json
{
  "date": "2025-01-15",
  "rates": {
    "USD": { "purchase": 510.25, "sale": 517.50, "description": "United States Dollar" },
    "EUR": { "purchase": 552.00, "sale": 560.30, "description": "Euro (European Union)" }
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

---

### `GET /health`

Health check endpoint. Returns `200 OK` when the service is running.

```json
{ "status": "ok" }
```

---

### Error responses

| Status | Condition                                           |
|--------|-----------------------------------------------------|
| `400`  | Missing required parameters or unsupported currency |
| `422`  | Invalid date format (must be `YYYY-MM-DD`)          |
| `502`  | BCCR upstream error                                 |

---

## MCP Server

TicoRates includes an [MCP](https://modelcontextprotocol.io/) server that gives AI assistants direct access to Costa Rican exchange rates. No API key required — it connects to `https://ticorates.dev` by default.

### Available tools

| Tool                       | Description                                      |
|----------------------------|--------------------------------------------------|
| `get_supported_currencies` | List all available currency codes and names      |
| `get_latest_rates`         | Today's rates for one or all currencies          |
| `get_rates_for_date`       | Historical rates for a specific date             |
| `get_rates_for_date_range` | Rates for a date range, one entry per day        |
| `convert_amount`           | Convert between any two currencies               |
| `get_rate_change`          | Absolute and percentage change between two dates |
| `get_historical_average`   | Average purchase/sale rate over a period         |

---

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

---

#### Claude Code

Run once in your terminal:

```bash
claude mcp add ticorates -- uvx ticorates-mcp
```

Or add it manually to `~/.claude/settings.json`:

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

---

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

---

#### Windsurf

Open the Cascade panel → **⚙ Settings → MCP Servers → Add**, then enter:

- **Command:** `uvx`
- **Args:** `ticorates-mcp`

---

#### OpenAI Codex CLI

Run once in your terminal:

```bash
codex mcp add ticorates -- uvx ticorates-mcp
```

Or add it manually to `~/.codex/config.toml` (global) or `.codex/config.toml` (project-scoped):

```toml
[mcp_servers.ticorates]
command = "uvx"
args = ["ticorates-mcp"]
```

---

#### Other clients

Any MCP-compatible client that supports `stdio` transport works with TicoRates. Use the same config structure shown above.

---

### Pointing the MCP at a self-hosted instance

By default, `ticorates-mcp` connects to `https://ticorates.dev`. If you're running your own instance, override it with the `TICORATES_BASE_URL` environment variable in your client's config.

**Claude Desktop / Claude Code / Cursor / Windsurf** (`JSON`):

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

**OpenAI Codex CLI** (`config.toml`):

```toml
[mcp_servers.ticorates]
command = "uvx"
args = ["ticorates-mcp"]
env = { TICORATES_BASE_URL = "http://your-server:8000" }
```

Or via CLI:

```bash
codex mcp add ticorates --env TICORATES_BASE_URL=http://your-server:8000 -- uvx ticorates-mcp
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
    volumes:
      - ticorates_data:/app/ticorates.db
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

# Run tests
uv run pytest
```
