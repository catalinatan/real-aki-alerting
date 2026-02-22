"""
Unit tests for Pager Module
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pager.pager import Pager


class TestPagerInitialization:
    """Tests for Pager initialization."""

    def test_init_sets_target_url(self):
        """Initialize Pager with target URL."""
        target_url = "https://example.com/api/page"
        pager = Pager(target_url)

        assert pager.target_url == target_url


class TestPagerPageSuccess:
    """Tests for successful paging operations."""

    def setup_method(self):
        self.pager = Pager("https://example.com/api/page")

    @patch("requests.post")
    def test_page_successful_request_returns_true(self, mock_post):
        """Successful POST request returns True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.pager.page("12345678", "2024-01-20T16:30:00")

        assert result is True

    @patch("requests.post")
    def test_page_sends_correct_payload(self, mock_post):
        """POST request includes correct MRN and prediction_time."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        self.pager.page("87654321", "2024-01-20T14:25:30")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"] == "87654321,2024-01-20T14:25:30"
        assert call_kwargs["headers"] == {"Content-Type": "text/plain"}

    @patch("requests.post")
    def test_page_sends_to_correct_url(self, mock_post):
        """POST request is sent to configured target URL."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        self.pager.page("12345678", "2024-01-20T16:30:00")

        mock_post.assert_called_once_with(
            "https://example.com/api/page",
            data="12345678,2024-01-20T16:30:00",
            headers={"Content-Type": "text/plain"},
            timeout=2
        )

    @patch("requests.post")
    def test_page_uses_2_second_timeout(self, mock_post):
        """POST request includes 2-second timeout."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        self.pager.page("12345678", "2024-01-20T16:30:00")

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["timeout"] == 2


class TestPagerPageHTTPErrors:
    """Tests for HTTP error handling."""

    def setup_method(self):
        self.pager = Pager("https://example.com/api/page")

    @patch("requests.post")
    def test_page_http_4xx_error_returns_false(self, mock_post):
        """4xx HTTP error returns False."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("404 Client Error")
        )
        mock_post.return_value = mock_response

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=1, retry_delay=0.0)

        assert result is False

    @patch("requests.post")
    def test_page_http_5xx_error_returns_false(self, mock_post):
        """5xx HTTP error returns False."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("500 Server Error")
        )
        mock_post.return_value = mock_response

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=1, retry_delay=0.0)

        assert result is False


class TestPagerPageNetworkErrors:
    """Tests for network and connection error handling."""

    def setup_method(self):
        self.pager = Pager("https://example.com/api/page")

    @patch("requests.post")
    def test_page_connection_error_returns_false(self, mock_post):
        """Connection error returns False."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=1, retry_delay=0.0)

        assert result is False

    @patch("requests.post")
    def test_page_timeout_error_returns_false(self, mock_post):
        """Timeout error returns False."""
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=1, retry_delay=0.0)

        assert result is False

    @patch("requests.post")
    def test_page_generic_request_exception_returns_false(self, mock_post):
        """Generic RequestException returns False."""
        mock_post.side_effect = requests.exceptions.RequestException("Unknown error")

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=1, retry_delay=0.0)

        assert result is False


class TestPagerPageEdgeCases:
    """Tests for edge cases and various input scenarios."""

    def setup_method(self):
        self.pager = Pager("https://example.com/api/page")

    @patch("requests.post")
    def test_page_with_empty_mrn(self, mock_post):
        """Page with empty MRN string."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.pager.page("", "2024-01-20T16:30:00")

        assert result is True
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"] == ",2024-01-20T16:30:00"

    @patch("requests.post")
    def test_page_with_empty_prediction_time(self, mock_post):
        """Page with empty prediction_time string."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.pager.page("12345678", "")

        assert result is True
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"] == "12345678"

    @patch("requests.post")
    def test_page_with_special_characters_in_mrn(self, mock_post):
        """Page with special characters in MRN."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.pager.page("MRN-123/456", "2024-01-20T16:30:00")

        assert result is True
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"] == "MRN-123/456,2024-01-20T16:30:00"


class TestPagerRetryBehavior:
    """Tests for pager retry logic."""

    def setup_method(self):
        self.pager = Pager("https://example.com/api/page")

    @patch("requests.post")
    def test_page_retries_on_failure_then_succeeds(self, mock_post):
        """Page retries after failure and succeeds on second attempt."""
        fail_response = MagicMock()
        fail_response.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("500 Server Error")
        )
        success_response = MagicMock()
        success_response.raise_for_status = MagicMock()

        mock_post.side_effect = [fail_response, success_response]

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=3, retry_delay=0.0)

        assert result is True
        assert mock_post.call_count == 2

    @patch("requests.post")
    def test_page_returns_false_after_all_retries_exhausted(self, mock_post):
        """Page returns False after all retry attempts fail."""
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=3, retry_delay=0.0)

        assert result is False
        assert mock_post.call_count == 3

    @patch("requests.post")
    def test_page_no_retry_on_first_success(self, mock_post):
        """Successful first attempt should not retry."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=3, retry_delay=0.0)

        assert result is True
        assert mock_post.call_count == 1

    @patch("requests.post")
    @patch("time.sleep")
    def test_page_sleeps_between_retries(self, mock_sleep, mock_post):
        """Page sleeps retry_delay seconds between retry attempts."""
        mock_post.side_effect = requests.exceptions.Timeout("timeout")

        self.pager.page("12345678", "2024-01-20T16:30:00", max_retries=3, retry_delay=2.0)

        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(2.0)
