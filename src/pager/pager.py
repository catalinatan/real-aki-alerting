"""
Pager Module

Creates POST request to target URL to page clinical response team
upon receiving positive prediction from AKI model.
"""

import time

import requests

from src.metrics import pager_errors_total


class Pager:
    """
    Pager implementation

    Sends POST request in form (mrn, prediction_time) to target URL
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

    def page(self, mrn: str, prediction_time: str, max_retries: int = 2, retry_delay: float = 0.5) -> bool:
        """
        Send POST request to target URL with paging information.
        Retries on failure up to max_retries times.

        Args:
            mrn (str): Medical Record Number of patient to page on
            prediction_time (str): Time of prediction
            max_retries (int): Maximum number of attempts
            retry_delay (float): Seconds to wait between retries

        Returns:
            bool: True if page successful, else False
        """
        for attempt in range(max_retries):
            try:
                if self.payload_format == "json":
                    payload = {
                        "mrn": mrn,
                        "prediction_time": prediction_time
                    }
                    response = requests.post(self.target_url, json=payload, timeout=2)
                elif self.payload_format == "csv":
                    body = f"{mrn},{prediction_time}" if prediction_time else str(mrn)
                    response = requests.post(
                        self.target_url,
                        data=body,
                        headers={"Content-Type": "text/plain"},
                        timeout=2
                    )
                else:
                    raise ValueError(f"Unsupported payload format: {self.payload_format}")
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException:
                pager_errors_total.inc()
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        return False
