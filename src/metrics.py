"""
Prometheus Metrics Module

Centralized definitions for all application metrics.
Exposes an HTTP server for Prometheus scraping.
"""

from prometheus_client import Counter, Histogram, start_http_server

METRICS_PORT = 8000

messages_received_total = Counter(
    "messages_received_total",
    "Total HL7 messages received via MLLP",
)

blood_tests_received_total = Counter(
    "blood_tests_received_total",
    "Total creatinine blood test results received",
)

aki_predictions_total = Counter(
    "aki_predictions_total",
    "Total AKI predictions made",
    ["result"],
)

pages_sent_total = Counter(
    "pages_sent_total",
    "Total successful pages sent to clinical team",
)

pager_errors_total = Counter(
    "pager_errors_total",
    "Total pager HTTP request failures",
)

mllp_reconnections_total = Counter(
    "mllp_reconnections_total",
    "Total MLLP socket reconnection attempts",
)

blood_test_value = Histogram(
    "blood_test_value",
    "Distribution of creatinine blood test values",
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0],
)


def start_metrics_server():
    """Start the Prometheus metrics HTTP server on METRICS_PORT."""
    start_http_server(METRICS_PORT)
