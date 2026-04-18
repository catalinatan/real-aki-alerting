"""
Pager Module

Creates POST request to target URL to page clinical response team
upon receiving positive prediction from AKI model.
"""

import time
from typing import Optional

import requests

from src.logger import logger
from src.metrics import pager_errors_total

DEFAULT_TIMEOUT = 2
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0


class Pager:
    """
    Pager implementation

    Sends POST request in form (mrn, prediction_time) to target URL with
    bounded retries on transient network or HTTP failures.
    """
    def __init__(self, target_url: str, payload_format: str = "csv"):
        """
        Initialize Pager class with connection configuration.

        Args:
            target_url (str): URL to send paging POST requests to
            payload_format (str): Payload format to use ("json" or "csv")
        """
        self.target_url = target_url
        self.payload_format = payload_format

    def _send(self, mrn: str, prediction_time: Optional[str]) -> requests.Response:
        if self.payload_format == "json":
            payload = {"mrn": mrn, "prediction_time": prediction_time}
            return requests.post(self.target_url, json=payload, timeout=DEFAULT_TIMEOUT)
        if self.payload_format == "csv":
            body = f"{mrn},{prediction_time}" if prediction_time else str(mrn)
            return requests.post(
                self.target_url,
                data=body,
                headers={"Content-Type": "text/plain"},
                timeout=DEFAULT_TIMEOUT,
            )
        raise ValueError(f"Unsupported payload format: {self.payload_format}")

    def page(
        self,
        mrn: str,
        prediction_time: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> bool:
        """
        Send POST request to target URL with paging information.
        Retries on failure up to max_retries total attempts.

        Args:
            mrn (str): Medical Record Number of patient to page on
            prediction_time (Optional[str]): Timestamp in HL7 format
                (yyyyMMddHHmmss), or None to omit.
            max_retries (int): Total number of attempts before giving up.
            retry_delay (float): Seconds to sleep between attempts.

        Returns:
            bool: True if page successful, else False
        """
        for attempt in range(max_retries):
            try:
                response = self._send(mrn, prediction_time)
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                pager_errors_total.inc()
                logger.error(
                    f"Pager request failed for MRN={mrn} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        return False
