"""
main.py
───────
Receipt Ingestion Pipeline
──────────────────────────
Orchestrates the full receipt-processing workflow:

  1. Check Dropbox /incoming for new receipt images
  2. For each receipt, get a temporary link and send it to Azure OCR
  3. Parse the OCR results (merchant, total, date, card number)
  4. Look up the credit card → Actual Budget account mapping
  5. Import the transaction into Actual Budget (via actualpy)
  6. Move the file to /completed (or /exception on failure)
  7. Send a Pushover notification with the result

Designed to be triggered by cron (e.g. every 15 minutes).
"""

import logging
from logging import config
import sys
import os

from config_loader import load_config
from dropbox_client import DropboxClient
from azure_ocr import AzureOCR
from account_mapper import AccountMapper
from actual_budget import ActualBudget
from pushover_notify import PushoverNotifier


def setup_logging(level_name: str):
    """Configure logging for the application."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def process_receipt(file_info: dict, dropbox: DropboxClient, ocr: AzureOCR,
                    mapper: AccountMapper, actual: ActualBudget,
                    notifier: PushoverNotifier):
    """
    Process a single receipt file through the full pipeline.

    Args:
        file_info:  Dict with keys: name, path, size, id  (from Dropbox)
        dropbox:    DropboxClient instance
        ocr:        AzureOCR instance
        mapper:     AccountMapper instance
        actual:     ActualBudget instance
        notifier:   PushoverNotifier instance
    """
    filename = file_info["name"]
    source_path = file_info["path"]
    log = logging.getLogger("receipt")

    log.info(f"Processing: {filename}")

    # ── Step 1: Get a temporary download link from Dropbox ────────
    log.info("  Getting temporary Dropbox link...")
    temp_link = dropbox.get_temp_link(source_path)

    # ── Step 2: Send to Azure OCR ─────────────────────────────────
    log.info("  Sending to Azure OCR...")
    receipt = ocr.analyze_receipt(temp_link)

    log.info(f"  OCR result: {receipt['merchant_name']} | "
             f"${receipt['total']:.2f} | {receipt['transaction_date']} | "
             f"card: {receipt.get('cardnumber', 'N/A')} | "
             f"confidence: {receipt['confidence']:.2f}")

    if receipt.get("date_corrected"):
        log.warning(f"  Date auto-corrected: {receipt['original_date']} → "
                     f"{receipt['transaction_date']}")

    # ── Step 3: Look up the credit card account ───────────────────
    account_name = mapper.lookup(receipt.get("cardnumber"), receipt.get("account"))

    if not account_name:
        log.warning(f"  No account match for card={receipt.get('cardnumber')}, "
                     f"account={receipt.get('account')}")

        # Move to exception folder
        new_path = dropbox.move_to_exception(source_path)
        log.info(f"  Moved to: {new_path}")

        # Get a link for the notification
        try:
            exception_link = dropbox.get_temp_link(new_path)
        except Exception:
            exception_link = None

        notifier.notify_exception(
            merchant_name=receipt["merchant_name"],
            total=receipt["total"],
            cardnumber=receipt.get("cardnumber"),
            receipt_link=exception_link,
        )
        return

    log.info(f"  Matched account: {account_name}")

    # ── Step 4: Import into Actual Budget ─────────────────────────
    log.info("  Importing to Actual Budget...")
    result = actual.import_transaction(
        account_name=account_name,
        merchant_name=receipt["merchant_name"],
        total=receipt["total"],
        transaction_date=receipt["transaction_date"],
        filename=filename,
    )

    if not result["matched"]:
        log.error(f"  Actual Budget account not found: {account_name}")

        new_path = dropbox.move_to_exception(source_path)
        log.info(f"  Moved to: {new_path}")

        try:
            exception_link = dropbox.get_temp_link(new_path)
        except Exception:
            exception_link = None

        notifier.notify_exception(
            merchant_name=receipt["merchant_name"],
            total=receipt["total"],
            cardnumber=receipt.get("cardnumber"),
            receipt_link=exception_link,
        )
        return

    if result["skipped"]:
        log.warning(f"  Duplicate transaction — not imported")
    else:
        log.info(f"  Transaction added successfully")

    # ── Step 5: Move file to completed ────────────────────────────
    new_path = dropbox.move_to_completed(source_path, receipt["merchant_name"])
    log.info(f"  Moved to: {new_path}")

    # ── Step 6: Send success notification ─────────────────────────
    notifier.notify_success(
        merchant_name=receipt["merchant_name"],
        total=receipt["total"],
        account_name=account_name,
        skipped=result["skipped"],
    )

def ping_healthcheck(url: str):
    """Ping healthchecks.io to signal successful completion."""
    import requests
    log = logging.getLogger("main")
    try:
        requests.get(url, timeout=10)
        log.info("Healthcheck ping sent.")
    except Exception as e:
        log.warning(f"Healthcheck ping failed: {e}")


def main():
    """Main entry point — run the full receipt ingestion pipeline."""

    # ── Load configuration ────────────────────────────────────────
    config = load_config()
    healthcheck_url = config["healthchecks"]["url"]
    setup_logging(config.get("logging", {}).get("level", "INFO"))
    log = logging.getLogger("main")


    log.info("=" * 50)
    log.info("Receipt Ingestion Pipeline — starting")
    log.info("=" * 50)

    # ── Initialize all service clients ────────────────────────────
    dbx_cfg = config["dropbox"]
    dropbox = DropboxClient(
        app_key=dbx_cfg["app_key"],
        app_secret=dbx_cfg["app_secret"],
        refresh_token=dbx_cfg["refresh_token"],
        incoming_folder=dbx_cfg["incoming_folder"],
        completed_folder=dbx_cfg["completed_folder"],
        exception_folder=dbx_cfg["exception_folder"],
    )

    ocr_cfg = config["azure_ocr"]
    ocr = AzureOCR(
        endpoint=ocr_cfg["endpoint"],
        api_key=ocr_cfg["api_key"],
        api_version=ocr_cfg["api_version"],
        poll_interval=ocr_cfg.get("poll_interval", 3),
        max_poll_attempts=ocr_cfg.get("max_poll_attempts", 20),
    )

    mapper = AccountMapper(config["account_mapping"])

    ab_cfg = config["actual_budget"]
    actual = ActualBudget(
        server_url=ab_cfg["server_url"],
        password=ab_cfg["password"],
        sync_id=ab_cfg["sync_id"],
        data_dir=ab_cfg.get("data_dir", "./actual-cache"),
    )

    po_cfg = config["pushover"]
    notifier = PushoverNotifier(
        api_token=po_cfg["api_token"],
        user_key=po_cfg["user_key"],
    )

    # ── Check Dropbox for new receipts ────────────────────────────
    log.info("Checking Dropbox /incoming for new files...")
    files = dropbox.list_incoming_files()

    if not files:
        log.info("No new receipts found. Done.")
        ping_healthcheck(config["healthchecks"]["url"])
        return

    log.info(f"Found {len(files)} file(s) to process.")
    ping_healthcheck(config["healthchecks"]["url"])

    # ── Process each receipt ──────────────────────────────────────
    for file_info in files:
        try:
            process_receipt(file_info, dropbox, ocr, mapper, actual, notifier)
        except Exception as e:
            log.error(f"Error processing {file_info['name']}: {e}", exc_info=True)
            try:
                notifier.notify_error(
                    f"Error processing {file_info['name']}: {str(e)[:200]}"
                )
            except Exception:
                log.error("Failed to send error notification")

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
