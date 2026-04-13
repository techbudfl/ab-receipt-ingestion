"""
account_mapper.py
─────────────────
Maps credit card numbers and Apple Pay account names to Actual Budget
account names using the account_mapping list from config.yaml.
"""


class AccountMapper:
    """Look up an Actual Budget account name from a card number or Apple Pay name."""

    def __init__(self, mapping_list: list[dict]):
        """
        Initialize from the account_mapping list in config.yaml.

        Each item should have keys: cardnumber, accountname, applepay_name
        """
        self.accounts = mapping_list

    def lookup(self, cardnumber: str | None, account_name: str | None) -> str | None:
        """
        Try to find the Actual Budget account name.

        First tries to match by last-4 of card number, then by Apple Pay name.
        Returns the account name string, or None if no match is found.
        """
        # Try matching by card number (last 4 digits)
        if cardnumber:
            last4 = cardnumber.strip()[-4:]
            for acct in self.accounts:
                if acct["cardnumber"] == last4:
                    return acct["accountname"]

        # Try matching by Apple Pay account name
        if account_name:
            clean_name = account_name.strip()
            for acct in self.accounts:
                if acct["applepay_name"].lower() == clean_name.lower():
                    return acct["accountname"]

        return None
