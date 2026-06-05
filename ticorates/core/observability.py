from collections.abc import Callable

from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info

Instrumentation = Callable[[Info], None]

_EXCLUDED_HANDLERS = ["/metrics", "/health"]


def _only_from_trusted_proxy(record: Instrumentation, header: str) -> Instrumentation:
    header = header.lower()

    def gated(info: Info) -> None:
        if header in info.request.headers:
            record(info)

    return gated


def build_instrumentator(
    trusted_header: str | None = None,
    registry: CollectorRegistry = REGISTRY,
) -> Instrumentator:
    """Build the Prometheus instrumentator, optionally restricted to traffic from a trusted proxy."""
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=_EXCLUDED_HANDLERS,
        registry=registry,
    )
    record = metrics.default(registry=registry)
    if trusted_header:
        record = _only_from_trusted_proxy(record, trusted_header)
    instrumentator.add(record)
    return instrumentator
