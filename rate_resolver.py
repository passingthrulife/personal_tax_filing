import csv
import os
from datetime import datetime, date, timedelta
import logging

logger = logging.getLogger(__name__)

class RateResolver:
    def __init__(self, csv_dir="csv_files"):
        self.csv_dir = csv_dir
        self.usd_rates = {}  # Maps date_obj (date) -> float (TT BUY rate)
        self._load_usd_rates()

    def _load_usd_rates(self):
        """Loads USD rates from the SBI reference rates CSV file."""
        csv_path = os.path.join(self.csv_dir, "SBI_REFERENCE_RATES_USD.csv")
        if not os.path.exists(csv_path):
            # Try searching up one directory just in case we are running from a subdirectory
            csv_path = os.path.join("..", self.csv_dir, "SBI_REFERENCE_RATES_USD.csv")
            if not os.path.exists(csv_path):
                logger.warning(f"USD reference rates CSV not found at {csv_path}. Forex conversions will fail.")
                return

        try:
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Date format is "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
                    date_str = row.get("DATE", "").split()[0]
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                        tt_buy = float(row.get("TT BUY", 0.0))
                        if tt_buy > 0:
                            # If there are multiple entries for the same date (rare), keep the latest or average.
                            # Standard behavior: overwrite with the last one seen.
                            self.usd_rates[date_obj] = tt_buy
                    except (ValueError, TypeError) as e:
                        continue
            logger.info(f"Loaded {len(self.usd_rates)} historical USD rates from {csv_path}")
        except Exception as e:
            logger.error(f"Error loading USD rates: {e}")

    def get_last_day_of_preceding_month(self, target_date: date) -> date:
        """Returns the last day of the month preceding the month of the target_date."""
        # Subtract days to go to the previous month
        first_day_of_current_month = target_date.replace(day=1)
        last_day_of_preceding_month = first_day_of_current_month - timedelta(days=1)
        return last_day_of_preceding_month

    def get_rate_for_date(self, target_date: date, conversion_type="TT BUY") -> float:
        """
        Get rate for a specific date. If not available, search backward day-by-day.
        """
        current_search_date = target_date
        max_lookback_days = 15  # Avoid infinite loop if there's no data

        for _ in range(max_lookback_days):
            if current_search_date in self.usd_rates:
                return self.usd_rates[current_search_date]
            current_search_date -= timedelta(days=1)

        # Fallback if no rate found in the lookback window
        # Return a conservative default rate (e.g. 83.0) or raise error
        logger.warning(f"Could not find USD rate near {target_date}. Using fallback default of 83.0")
        return 83.0

    def resolve_rule_115_rate(self, transaction_date: date) -> float:
        """
        Resolves the exchange rate under Rule 115 for the given transaction date.
        Rule 115: Rate of exchange is SBI TT Buy rate on the last day of the month
        immediately preceding the month in which the income is earned/received.
        """
        specified_date = self.get_last_day_of_preceding_month(transaction_date)
        resolved_rate = self.get_rate_for_date(specified_date)
        logger.debug(f"Rule 115 for tx date {transaction_date}: Preceding month end is {specified_date}, resolved rate is {resolved_rate}")
        return resolved_rate
