"""
TicoRates Stress Test
Starts a local server with a temporary DB and runs 8 real-world scenarios.

Usage:
    uv run python tests/stress/stress_test.py
"""
import asyncio
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.stress


@dataclass
class Result:
    name: str
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    wall_s: float = 0.0

    def record(self, status: int, elapsed_s: float) -> None:
        self.latencies_ms.append(elapsed_s * 1000)
        self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def p(self, pct: float) -> float:
        s = sorted(self.latencies_ms)
        return s[min(int(len(s) * pct), len(s) - 1)] if s else 0.0

    @property
    def rps(self) -> float:
        total = len(self.latencies_ms) + len(self.errors)
        return total / self.wall_s if self.wall_s else 0.0

    def passed(self) -> bool:
        return not self.errors and self.status_counts.get(500, 0) == 0

    def print(self) -> None:
        total = len(self.latencies_ms) + len(self.errors)
        status_str = "  ".join(f"HTTP {k}: {v}" for k, v in sorted(self.status_counts.items()))
        icon = "✓" if self.passed() else "✗"

        print(f"\n{'─' * 64}")
        print(f"  {icon}  {self.name}")
        print(f"{'─' * 64}")
        print(f"  Requests : {total} in {self.wall_s:.2f}s  ({self.rps:.0f} req/s)")
        if status_str:
            print(f"  Status   : {status_str}")
        if self.errors:
            print(f"  Errors   : {len(self.errors)}")
        if self.latencies_ms:
            print(f"  p50={self.p(0.5):.0f}ms  p95={self.p(0.95):.0f}ms  p99={self.p(0.99):.0f}ms  max={max(self.latencies_ms):.0f}ms")
        for note in self.notes:
            print(f"  → {note}")
        for err in self.errors[:3]:
            print(f"  ! {err}")


async def req(client: httpx.AsyncClient, result: Result, path: str, **kwargs) -> dict | None:
    t = time.perf_counter()
    try:
        resp = await client.get(path, **kwargs)
        result.record(resp.status_code, time.perf_counter() - t)
        return resp.json() if resp.status_code == 200 else None
    except Exception as exc:
        result.errors.append(f"{path}: {exc}")
        return None


async def run_concurrent(result: Result, tasks: list) -> None:
    t = time.perf_counter()
    await asyncio.gather(*tasks)
    result.wall_s = time.perf_counter() - t


def start_server(port: int, db_path: str, log_path: str) -> tuple[subprocess.Popen, object]:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"}
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "ticorates.main:app", f"--port={port}", "--log-level=info"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return proc, log_file


async def wait_ready(base_url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.time() < deadline:
            try:
                r = await client.get("/health")
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Server at {base_url} did not respond within {timeout}s")


async def s1_throughput(client: httpx.AsyncClient) -> Result:
    result = Result("1 — Base throughput: /health × 100 concurrent")
    tasks = [req(client, result, "/health") for _ in range(100)]
    await run_concurrent(result, tasks)
    return result


async def s2_cache_misses(client: httpx.AsyncClient) -> Result:
    result = Result("2 — 15 distinct cache misses (live BCCR, currency=USD)")
    days = [8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 22, 23, 24, 25, 26]
    dates = [f"2024-01-{d:02d}" for d in days]
    tasks = [
        req(client, result, "/rates", params={"date": d, "currency": "USD"})
        for d in dates
    ]
    await run_concurrent(result, tasks)
    result.notes.append("Each date requires 2 BCCR calls (buy + sell indicator for USD)")
    result.notes.append("Shared semaphore limits to 5 concurrent BCCR calls → no 429s expected")
    return result


async def s3_race_condition(client: httpx.AsyncClient) -> Result:
    result = Result("3 — Race condition: same date × 20 concurrent (cache miss)")
    tasks = [
        req(client, result, "/rates", params={"date": "2024-03-15", "currency": "USD"})
        for _ in range(20)
    ]
    await run_concurrent(result, tasks)
    spread = result.p(0.99) - result.p(0.5)
    result.notes.append(f"Spread p99–p50 = {spread:.0f}ms")
    if spread < 200:
        result.notes.append("Tight spread → SingleFlight coalesced the requests (expected behavior)")
    else:
        result.notes.append("Wide spread → requests processed in batches (possible cache stampede)")
    return result


async def s4_cache_hits(client: httpx.AsyncClient) -> Result:
    result = Result("4 — 50 concurrent cache hits (same date already cached)")
    await req(client, Result("warmup"), "/rates", params={"date": "2025-05-27", "currency": "USD"})
    tasks = [
        req(client, result, "/rates", params={"date": "2025-05-27", "currency": "USD"})
        for _ in range(50)
    ]
    await run_concurrent(result, tasks)
    result.notes.append("No BCCR calls — SQLite only → expected p50 < 10ms")
    return result


async def s5_weekend_fallback(client: httpx.AsyncClient) -> Result:
    result = Result("5 — Business day fallback (Saturday + Sunday)")
    for date in ["2025-05-24", "2025-05-25"]:
        t = time.perf_counter()
        resp = await client.get("/rates", params={"date": date, "currency": "USD"})
        result.record(resp.status_code, time.perf_counter() - t)
        if resp.status_code == 200:
            returned = resp.json().get("date")
            if returned != date:
                result.notes.append(f"Requested {date} → returned {returned} ✓ (fallback correct)")
            else:
                result.notes.append(f"Requested {date} → returned {returned} (BCCR had data for that day)")
        else:
            result.notes.append(f"Requested {date} → HTTP {resp.status_code} ✗")
    result.wall_s = sum(result.latencies_ms) / 1000
    return result


async def s6_error_mix(client: httpx.AsyncClient) -> Result:
    result = Result("6 — Mixed load: valid + invalid currency + missing params (50 total)")
    tasks = (
        [req(client, result, "/rates", params={"date": "2025-05-27", "currency": "USD"}) for _ in range(20)] +
        [req(client, result, "/rates", params={"date": "2025-05-27", "currency": "FAKECOIN"}) for _ in range(15)] +
        [req(client, result, "/rates") for _ in range(15)]
    )
    random.shuffle(tasks)
    await run_concurrent(result, tasks)
    result.notes.append("Expected: 20×HTTP 200, 15×HTTP 400 (currency), 15×HTTP 422 (missing params), 0×HTTP 500")
    return result


async def s7_date_range(client: httpx.AsyncClient) -> Result:
    result = Result("7 — Date range 14 days (includes weekends, currency=USD)")
    t = time.perf_counter()
    resp = await client.get("/rates", params={"from": "2025-05-12", "to": "2025-05-25", "currency": "USD"})
    result.record(resp.status_code, time.perf_counter() - t)
    result.wall_s = result.latencies_ms[0] / 1000 if result.latencies_ms else 0.0
    if resp.status_code == 200:
        days = resp.json()
        result.notes.append(f"Returned {len(days)} days out of 14 requested (weekends excluded)")
        if days:
            result.notes.append(f"Actual range: {days[0]['date']} → {days[-1]['date']}")
    return result


async def s8_mcp_tools(base_url: str) -> Result:
    result = Result("8 — Concurrent MCP tools (6 simultaneous)")
    import mcp_server.server as mcp
    original_url = mcp._BASE_URL
    mcp._BASE_URL = base_url

    async def run_tool(label: str, coro, *, expect_error: bool = False) -> None:
        t = time.perf_counter()
        try:
            await coro
            elapsed = (time.perf_counter() - t) * 1000
            result.record(200, elapsed / 1000)
            result.notes.append(f"✓ {label} ({elapsed:.0f}ms)")
        except ValueError as exc:
            elapsed = (time.perf_counter() - t) * 1000
            result.record(400 if expect_error else 500, elapsed / 1000)
            if expect_error:
                result.notes.append(f"✓ {label} → expected ValueError: {exc} ({elapsed:.0f}ms)")
            else:
                result.notes.append(f"✗ {label} → unexpected ValueError: {exc}")
        except mcp.TicoRatesAPIError as exc:
            elapsed = (time.perf_counter() - t) * 1000
            result.record(exc.status_code, elapsed / 1000)
            if expect_error and exc.status_code == 400:
                result.notes.append(f"✓ {label} → expected HTTP 400: {exc} ({elapsed:.0f}ms)")
            else:
                # Upstream error (e.g. BCCR rate-limit → 502): not our code's fault.
                result.notes.append(f"~ {label} → HTTP {exc.status_code}: {exc} ({elapsed:.0f}ms)")
        except RuntimeError as exc:
            elapsed = (time.perf_counter() - t) * 1000
            result.record(500, elapsed / 1000)
            result.notes.append(f"✗ {label} → RuntimeError: {exc} ({elapsed:.0f}ms)")
        except Exception as exc:
            result.errors.append(f"{label}: {type(exc).__name__}: {exc}")

    t = time.perf_counter()
    await asyncio.gather(
        run_tool("get_latest_rates(USD)", mcp.get_latest_rates("USD")),
        run_tool("get_rates_for_date(2025-05-27, USD)", mcp.get_rates_for_date("2025-05-27", "USD")),
        run_tool("get_rate_change(USD, may)", mcp.get_rate_change("USD", "2025-05-01", "2025-05-27")),
        run_tool("convert_amount(100 USD→CRC)", mcp.convert_amount(100.0, "USD", "CRC")),
        run_tool("convert_amount(FAKE→CRC)", mcp.convert_amount(100.0, "FAKE", "CRC"), expect_error=True),
        run_tool("get_historical_average(USD, may)", mcp.get_historical_average("USD", "2025-05-01", "2025-05-27")),
    )
    result.wall_s = time.perf_counter() - t
    mcp._BASE_URL = original_url
    return result


async def main() -> int:
    port = 8765
    base_url = f"http://localhost:{port}"

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    log_path = db_path.replace(".db", ".log")

    print("=" * 64)
    print("  TicoRates — Stress Test")
    print("=" * 64)
    print(f"  Server   : {base_url}")
    print(f"  DB       : {db_path}")
    print(f"  Logs     : {log_path}")

    proc, log_file = start_server(port, db_path, log_path)
    exit_code = 0

    try:
        print("\n  Starting server...", end=" ", flush=True)
        await wait_ready(base_url)
        print("ready ✓")

        results = []
        scenarios = [
            s1_throughput,
            s2_cache_misses,
            s3_race_condition,
            s4_cache_hits,
            s5_weekend_fallback,
            s6_error_mix,
            s7_date_range,
        ]

        async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
            for scenario in scenarios:
                print(f"\n  → {scenario.__name__}...", end=" ", flush=True)
                r = await scenario(client)
                results.append(r)
                print("✓" if r.passed() else "✗ (see results below)")

        print("\n  → s8_mcp_tools...", end=" ", flush=True)
        try:
            r = await s8_mcp_tools(base_url)
            results.append(r)
            print("✓" if r.passed() else "✗ (see results below)")
        except Exception as exc:
            print(f"✗ ERROR: {exc}")
            results.append(Result("8 — MCP tools", errors=[str(exc)]))

        print("\n\n" + "=" * 64)
        print("  DETAILED RESULTS")
        print("=" * 64)
        for r in results:
            r.print()

        failed = [r for r in results if not r.passed()]
        print("\n" + "=" * 64)
        if not failed:
            print("  ✓ All scenarios passed — no crashes, no HTTP 500s")
        else:
            print(f"  ✗ {len(failed)} scenario(s) with issues:")
            for r in failed:
                print(f"    — {r.name}")
            exit_code = 1
        print("=" * 64)

    except Exception as exc:
        print(f"\n  FATAL ERROR: {exc}")
        exit_code = 1

    finally:
        proc.terminate()
        proc.wait()
        log_file.close()
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass
        print(f"\n  Server stopped. Full logs at: {log_path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
