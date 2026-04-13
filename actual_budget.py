"""
actual_budget.py
────────────────
Imports a receipt transaction into Actual Budget using the actualpy library.

Uses `create_transaction` for a clean insert of new transactions, with a
manual `imported_id` check beforehand to prevent reprocessing the same
receipt if it wasn't moved out of /incoming (e.g. due to a crash).

We intentionally do NOT use `reconcile_transaction` because its fuzzy
matching on date + amount + payee could merge two legitimately different
purchases (e.g. same coffee shop, same amount, same week).

NOTE: If you get import errors, check your actualpy version:
    pip show actualpy
This was written for actualpy >= 0.6.
Docs: https://actualpy.readthedocs.io/
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from actual import Actual
from actual.queries import (
    create_transaction,
    get_accounts,
    get_transactions,
    normalize_payee,
    reconcile_transaction,
)

log = logging.getLogger("actual")


class ActualBudget:
    """Connect to Actual Budget and import receipt transactions."""

    def __init__(self, server_url: str, password: str, sync_id: str, data_dir: str):
        self.server_url = server_url
        self.password = password
        self.sync_id = sync_id
        self.data_dir = data_dir

    def import_transaction(self, account_name: str, merchant_name: str,
                           total: float, transaction_date: str,
                           filename: str) -> dict:
        """
        Import a single receipt transaction into Actual Budget.

        Args:
            account_name:     The Actual Budget account name (e.g. "💳 Chase Freedom Unlim")
            merchant_name:    Payee name from the receipt
            total:            Dollar amount (positive number — will be made negative for expense)
            transaction_date: Date string in YYYY-MM-DD format
            filename:         Original receipt filename (used for notes + duplicate detection)

        Returns a dict with:
            matched:      bool — whether the account was found in Actual
            account_name: str
            added:        int — 1 if new, 0 if duplicate
            skipped:      bool — True if this was a duplicate
            error:        str or None
        """
        # Clean up OCR artifacts (newlines, carriage returns) then
        # normalize via actualpy to match Actual's own convention:
        #   strip whitespace + title case  (e.g. "MY PAYEE " → "My Payee")
        # This keeps payees consistent across imports and prevents
        # the same merchant from creating multiple payee records.
        raw_payee = merchant_name.replace("\n", " ").replace("\r", "")
        clean_payee = normalize_payee(raw_payee)

        # Create an imported_id for duplicate detection.
        # Uses the *normalized* payee so that casing differences in OCR
        # output don't produce different hashes for the same receipt.
        imported_id = _make_imported_id(filename, total, transaction_date, clean_payee)

        # Convert total to negative Decimal (expenses are negative in Actual)
        amount = Decimal(str(total)) * Decimal("-1")

        # Parse the date
        try:
            txn_date = datetime.strptime(transaction_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            log.warning(f"Could not parse date '{transaction_date}', using today")
            txn_date = date.today()

        # ── Connect to Actual Budget ──────────────────────────────
        with Actual(
            base_url=self.server_url,
            password=self.password,
            file=self.sync_id,
            data_dir=self.data_dir,
        ) as actual:
            actual.download_budget()

            # ── Find the matching account ─────────────────────────
            accounts = get_accounts(actual.session)
            matched_account = None
            for acct in accounts:
                if acct.name == account_name:
                    matched_account = acct
                    break

            if not matched_account:
                return {
                    "matched": False,
                    "account_name": account_name,
                    "added": 0,
                    "skipped": False,
                    "error": f"Account not found in Actual Budget: {account_name}",
                }

            # ── Check for duplicate by imported_id ────────────────
            # This guards against reprocessing the same receipt if
            # it wasn't moved out of /incoming (e.g. due to a crash).
            existing_txns = get_transactions(actual.session)
            is_duplicate = any(
                getattr(t, "imported_id", None) == imported_id
                for t in existing_txns
            )

            if is_duplicate:
                log.info(f"  Duplicate detected (imported_id={imported_id})")
                return {
                    "matched": True,
                    "account_name": account_name,
                    "added": 0,
                    "skipped": True,
                    "error": None,
                }

            # ── Create the transaction ────────────────────────────
            # txn = create_transaction(  ## NOTE: reconcile_transaction is used instead of create_transaction as it's preferred for imported transactions
            txn = reconcile_transaction(
                actual.session,
                txn_date,
                matched_account,
                clean_payee,
                notes=f"#importedreceipt | {filename}",
                amount=amount,
                imported_id=imported_id,  # Store imported_id for future duplicate detection
            )

            # Set imported_id for future duplicate detection
          # txn.imported_id = imported_id
            # Mark as uncleared so the user can review it
            txn.cleared = False

            # Commit changes (sync back to server)
            actual.commit()

            log.info(f"  Transaction created: {clean_payee} | "
                     f"${total:.2f} | {txn_date} | acct={account_name}")

            return {
                "matched": True,
                "account_name": account_name,
                "added": 1,
                "skipped": False,
                "error": None,
            }


def _make_imported_id(filename: str, amount: float, date: str, merchant: str) -> str:
    """
    Generate a stable imported_id from receipt details.

    Hashes filename + amount + date + merchant so that:
      - Reprocessing the same file produces the same ID (caught as duplicate)
      - Two different receipts from the same store on the same day with
        different filenames get unique IDs (both imported)
    """
    import hashlib
    raw = f"{filename}|{amount}|{date}|{merchant}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
