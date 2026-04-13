"""
azure_ocr.py
────────────
Sends a receipt image to Azure Document Intelligence (prebuilt-receipt model)
and returns the parsed receipt fields.
"""

import time
import requests
from datetime import datetime, timedelta


class AzureOCR:
    """Interact with Azure Document Intelligence to extract receipt data."""

    def __init__(self, endpoint: str, api_key: str, api_version: str,
                 poll_interval: int = 3, max_poll_attempts: int = 20):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts

    # ── Public method ─────────────────────────────────────────────────

    def analyze_receipt(self, image_url: str) -> dict:
        """
        Send an image URL to Azure OCR and return parsed receipt data.
        Blocks until Azure finishes processing (polls automatically).

        Returns a dict with keys like:
            merchant_name, total, transaction_date, tax, tip, subtotal,
            confidence, cardnumber, account, merchant_address, etc.
        """
        # Step 1: Submit the image for analysis
        operation_url = self._submit_for_analysis(image_url)

        # Step 2: Poll until processing is complete
        raw_response = self._poll_for_result(operation_url)

        # Step 3: Parse the Azure response into a clean dict
        return self._parse_response(raw_response)

    # ── Submit image ──────────────────────────────────────────────────

    def _submit_for_analysis(self, image_url: str) -> str:
        """
        POST the image URL to Azure. Returns the operation-location URL
        that we poll to get results.
        """
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"prebuilt-receipt:analyze"
            f"?api-version={self.api_version}"
            f"&features=queryFields"
            f"&queryFields=CardNumber,Account"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }

        body = {"urlSource": image_url}

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()

        operation_url = resp.headers.get("operation-location")
        if not operation_url:
            raise RuntimeError("Azure did not return an operation-location header")

        return operation_url

    # ── Poll for result ───────────────────────────────────────────────

    def _poll_for_result(self, operation_url: str) -> dict:
        """
        Poll the operation URL until Azure returns 'succeeded' or we
        exceed the maximum number of attempts.
        """
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        for attempt in range(1, self.max_poll_attempts + 1):
            time.sleep(self.poll_interval)

            resp = requests.get(operation_url, headers=headers, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            status = result.get("status", "unknown")

            if status == "succeeded":
                return result
            elif status in ("failed", "canceled"):
                raise RuntimeError(f"Azure OCR failed with status: {status}")
            # else: still "running" — keep polling

        raise RuntimeError(
            f"Azure OCR did not complete after {self.max_poll_attempts} attempts"
        )

    # ── Parse the raw Azure response ──────────────────────────────────

    def _parse_response(self, raw: dict) -> dict:
        """Extract the key receipt fields from Azure's response."""
        document = raw["analyzeResult"]["documents"][0]
        fields = document.get("fields", {})

        # Build the clean receipt dict
        receipt = {
            "merchant_name": _get_string(fields.get("MerchantName")) or "Unknown Merchant",
            "merchant_address": _get_string(fields.get("MerchantAddress")),
            "merchant_phone": _get_string(fields.get("MerchantPhoneNumber")),
            "transaction_date": _get_date(fields.get("TransactionDate")),
            "transaction_time": _get_string(fields.get("TransactionTime")),
            "total": _get_number(fields.get("Total")) or 0,
            "tax": _get_number(fields.get("TotalTax")) or 0,
            "subtotal": _get_number(fields.get("Subtotal")),
            "tip": _get_number(fields.get("Tip")) or 0,
            "confidence": document.get("confidence", 0),
            "cardnumber": _get_string(fields.get("CardNumber")),
            "account": _get_string(fields.get("Account")),
        }

        # ── Date sanity check ─────────────────────────────────────
        # If the OCR-extracted date is more than 30 days in the past,
        # the year is likely wrong. Correct it to the current year.
        receipt["date_corrected"] = False
        if receipt["transaction_date"]:
            try:
                parsed_date = datetime.strptime(receipt["transaction_date"], "%Y-%m-%d")
                now = datetime.now()
                days_diff = (now - parsed_date).days

                if days_diff > 30:
                    original = receipt["transaction_date"]
                    parsed_date = parsed_date.replace(year=now.year)
                    # If corrected date is in the future (e.g. late Dec → early Jan)
                    if parsed_date > now:
                        parsed_date = parsed_date.replace(year=now.year - 1)
                    receipt["transaction_date"] = parsed_date.strftime("%Y-%m-%d")
                    receipt["date_corrected"] = True
                    receipt["original_date"] = original
            except ValueError:
                pass  # If date doesn't parse, leave it as-is

        return receipt


# ── Helper functions to extract field values ──────────────────────────

def _get_string(field: dict | None) -> str | None:
    """Safely extract a string value from an Azure field."""
    if not field:
        return None
    return field.get("valueString") or field.get("content")


def _get_number(field: dict | None) -> float | None:
    """Safely extract a numeric value from an Azure field."""
    if not field:
        return None
    if "valueNumber" in field:
        return field["valueNumber"]
    if "valueCurrency" in field and "amount" in field["valueCurrency"]:
        return field["valueCurrency"]["amount"]
    return None


def _get_date(field: dict | None) -> str | None:
    """Safely extract a date string from an Azure field."""
    if not field:
        return None
    return field.get("valueDate") or field.get("content")
