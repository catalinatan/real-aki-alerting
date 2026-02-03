"""
Pager Module

Creates POST request to target URL to page clinical response team
upon receiving positive prediction from AKI model.
"""

import requests

class Pager:
    """
    Pager implementation
    """
    def __init__(self, target_url: str):
        """
        Initialize Pager class with connection configuration.

        Args:
            target_url (str): URL to send paging POST requests to
        """
        self.target_url = target_url
        
    def page(self, mrn: str, timestamp: str = None) -> bool:
        """
        Send POST request to target URL with paging information.
        Returns True if page successful, else False.

        Args:
            mrn (str): Medical Record Number of patient to page on
            timestamp (str, optional): Time of blood test result in HL7 format (YYYYMMDDHHmm).
                           If None, server assumes time of last test result.

        Returns:
            bool: True if page successful, else False
        """

        try:
            # Format body as CSV: mrn,timestamp or just mrn
            body = f"{mrn},{timestamp}" if timestamp else mrn
            
            # Send POST with text/plain content type as per spec
            response = requests.post(
                self.target_url, 
                data=body,
                headers={"Content-Type": "text/plain"},
                timeout=3
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            # Log error or raise
            return False