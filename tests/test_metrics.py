"""Unit tests for Prometheus metrics module."""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from prometheus_client import CollectorRegistry
from src.metrics import (
    messages_received_total,
    blood_tests_received_total,
    aki_predictions_total,
    pages_sent_total,
    pager_errors_total,
    mllp_reconnections_total,
    blood_test_value,
    METRICS_PORT,
)


class TestMetricDefinitions:
    """Tests that all metrics are properly defined."""

    def test_messages_received_total_is_counter(self):
        assert messages_received_total._type == "counter"

    def test_blood_tests_received_total_is_counter(self):
        assert blood_tests_received_total._type == "counter"

    def test_aki_predictions_total_is_counter_with_result_label(self):
        assert aki_predictions_total._type == "counter"
        assert "result" in aki_predictions_total._labelnames

    def test_pages_sent_total_is_counter(self):
        assert pages_sent_total._type == "counter"

    def test_pager_errors_total_is_counter(self):
        assert pager_errors_total._type == "counter"

    def test_mllp_reconnections_total_is_counter(self):
        assert mllp_reconnections_total._type == "counter"

    def test_blood_test_value_is_histogram(self):
        assert blood_test_value._type == "histogram"

    def test_metrics_port_is_8000(self):
        assert METRICS_PORT == 8000
