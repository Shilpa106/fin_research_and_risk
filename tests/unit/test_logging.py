import json
import logging

import pytest

from src.observability.logging import (
    StructuredJsonFormatter,
    clear_correlation_context,
    correlation_id_ctx,
    set_correlation_context,
    tenant_id_ctx,
)


@pytest.mark.unit
def test_structured_json_logging():
    """Verify logger produces structured JSON with correlation and tenant IDs."""
    formatter = StructuredJsonFormatter(service_name="test-service")
    set_correlation_context(correlation_id="corr-9988-1122", tenant_id="tenant-msam-44")

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Processing 10-K filing",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)
    log_dict = json.loads(formatted)

    assert log_dict["service"] == "test-service"
    assert log_dict["level"] == "INFO"
    assert log_dict["message"] == "Processing 10-K filing"
    assert log_dict["correlation_id"] == "corr-9988-1122"
    assert log_dict["tenant_id"] == "tenant-msam-44"

    clear_correlation_context()
    assert correlation_id_ctx.get() is None
    assert tenant_id_ctx.get() is None
