"""
Pager Module

Creates POST request to target URL to page clinical response team
upon receiving positive prediction from AKI model.
"""

from typing import Optional

import requests

from src.logger import logger


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

    def page(self, mrn: str, prediction_time: Optional[str] = None) -> bool:
        """
        Send POST request to target URL with paging information.
        Returns True if page successful, else False.

        Args:
            mrn (str): Medical Record Number of patient to page on
            prediction_time (Optional[str]): Timestamp in HL7 format
                (yyyyMMddHHmmss), or None to omit.

        Returns:
            bool: True if page successful, else False
        """
        try:
            if self.payload_format == "json":
                payload = {
                    "mrn": mrn,
                    "prediction_time": prediction_time
                }
                response = requests.post(self.target_url, json=payload, timeout=3)
            elif self.payload_format == "csv":
                body = f"{mrn},{prediction_time}" if prediction_time else str(mrn)
                response = requests.post(
                    self.target_url,
                    data=body,
                    headers={"Content-Type": "text/plain"},
                    timeout=3
                )
            else:
                raise ValueError(f"Unsupported payload format: {self.payload_format}")
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Pager request failed for MRN={mrn}: {e}")
            return False
