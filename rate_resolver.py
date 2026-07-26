import csv
import os
from datetime import datetime, date, timedelta
import logging

logger = logging.getLogger(__name__)

class RateResolver:
    def __init__(self, csv_dir="csv_files"):
        self.csv_dir = csv_dir
        self.usd_rates = {}  # Maps date_obj (date) -> float (TT BUY rate)
        self.rbi_rates = {}  # Maps date_obj (date) -> float (RBI Reference rate)
        self._load_usd_rates()
        self._load_rbi_rates()

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

    def _load_rbi_rates(self):
        """Loads RBI reference rates from any RBI reference rate CSV files in the project root."""
        import glob
        # The script may run from different directories, check both current directory and parent
        project_dir = os.path.dirname(os.path.abspath(__file__))
        rbi_files = glob.glob(os.path.join(project_dir, "*RBI*.csv"))
        if not rbi_files:
            rbi_files = glob.glob(os.path.join(os.path.dirname(project_dir), "*RBI*.csv"))
            
        for filepath in rbi_files:
            try:
                with open(filepath, mode="r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    
                    # Find indices for Date and USD columns
                    date_idx = -1
                    usd_idx = -1
                    for idx, h in enumerate(header):
                        h_clean = h.strip().lower()
                        if "date" in h_clean:
                            date_idx = idx
                        elif "usd" in h_clean or "1 usd" in h_clean:
                            usd_idx = idx
                            
                    if date_idx == -1 or usd_idx == -1:
                        continue
                        
                    loaded_count = 0
                    for row in reader:
                        if not row or len(row) < max(date_idx, usd_idx) + 1:
                            continue
                        date_str = row[date_idx].strip()
                        usd_str = row[usd_idx].strip()
                        try:
                            # Try parsing date formats
                            dt = None
                            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
                                try:
                                    dt = datetime.strptime(date_str, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            if not dt:
                                from dateutil import parser as date_parser
                                dt = date_parser.parse(date_str).date()
                                
                            val = float(usd_str)
                            if val > 0:
                                self.rbi_rates[dt] = val
                                loaded_count += 1
                        except Exception:
                            continue
                    logger.info(f"Loaded {loaded_count} RBI rates from {os.path.basename(filepath)}")
            except Exception as e:
                logger.error(f"Error loading RBI reference rates from {filepath}: {e}")

    def get_last_day_of_preceding_month(self, target_date: date) -> date:
        """Returns the last day of the month preceding the month of the target_date."""
        # Subtract days to go to the previous month
        first_day_of_current_month = target_date.replace(day=1)
        last_day_of_preceding_month = first_day_of_current_month - timedelta(days=1)
        return last_day_of_preceding_month

    def get_rate_for_date(self, target_date: date, conversion_type="TT BUY") -> float:
        """
        Get rate for a specific date. If not available in SBI, search backward day-by-day.
        If still not found, search backward day-by-day in RBI reference rates and estimate via:
        SBI_TT_BUY = 0.991161 * RBI_REF + 0.257978
        """
        current_search_date = target_date
        max_lookback_days = 15  # Avoid infinite loop if there's no data

        # 1. Search in SBI TT Buy rates
        for _ in range(max_lookback_days):
            if current_search_date in self.usd_rates:
                return self.usd_rates[current_search_date]
            current_search_date -= timedelta(days=1)

        # 2. Search in RBI reference rates and apply linear regression model
        current_search_date = target_date
        for _ in range(max_lookback_days):
            if current_search_date in self.rbi_rates:
                rbi_rate = self.rbi_rates[current_search_date]
                estimated_sbi = 0.991161 * rbi_rate + 0.257978
                logger.info(f"Using estimated SBI rate for {target_date} from RBI rate {rbi_rate:.4f}: {estimated_sbi:.4f}")
                return round(estimated_sbi, 4)
            current_search_date -= timedelta(days=1)

        # Fallback if no rate found in either
        logger.warning(f"Could not find USD rate near {target_date} in SBI or RBI. Using fallback default of 83.0")
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
