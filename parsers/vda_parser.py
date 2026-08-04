import re
import csv
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class VDAParserMixin:
    def parse_vda_csv(self, csv_content: str) -> list:
        """
        Parses Virtual Digital Assets (VDA) / Cryptocurrency trades CSV.
        Expected columns:
        - Symbol/Asset/Token: name of crypto (BTC, ETH, etc.)
        - Acquisition Date / Buy Date: date of purchase
        - Transfer Date / Sell Date: date of sale
        - Cost / Purchase Price / Buy Price: cost of acquisition in INR
        - Proceeds / Sell Price / Consideration: consideration received in INR
        """
        records = []
        normalized_content = csv_content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized_content.strip())
        reader = csv.reader(f)
        rows = list(reader)
        if not rows:
            return []
            
        header_row_idx = -1
        headers = []
        
        for idx, row in enumerate(rows):
            row_headers = [str(cell).strip().lower() for cell in row]
            
            def has_match(names):
                return any(any(name in cell for name in names) for cell in row_headers)
                
            has_buy_dt = has_match(["buy date", "acquisition", "purchase date", "acquired"])
            has_sell_dt = has_match(["sell date", "transfer", "sale date", "sold"])
            has_cost = has_match(["cost", "buy price", "purchase price", "acquisition cost"])
            has_proceeds = has_match(["proceeds", "sell price", "consideration", "sale value"])
            
            if (has_buy_dt or has_sell_dt) and (has_cost or has_proceeds):
                header_row_idx = idx
                headers = row_headers
                break
                
        if header_row_idx == -1:
            for idx, row in enumerate(rows):
                if any(row):
                    header_row_idx = idx
                    headers = [str(cell).strip().lower() for cell in row]
                    break
                    
        sym_idx = -1
        buy_date_idx = -1
        sell_date_idx = -1
        cost_idx = -1
        proceeds_idx = -1
        
        for idx, h in enumerate(headers):
            if any(x in h for x in ["symbol", "asset", "token", "coin", "currency", "name"]):
                sym_idx = idx
            elif any(x in h for x in ["buy date", "acquisition", "purchase date", "acquired"]):
                buy_date_idx = idx
            elif any(x in h for x in ["sell date", "transfer", "sale date", "sold"]):
                sell_date_idx = idx
            elif any(x in h for x in ["cost", "purchase price", "buy price", "acquisition cost"]):
                cost_idx = idx
            elif any(x in h for x in ["proceeds", "sell price", "consideration", "sale value", "amount", "value"]):
                proceeds_idx = idx
                
        if buy_date_idx == -1:
            if len(headers) >= 4:
                buy_date_idx = 1
        if sell_date_idx == -1:
            if len(headers) >= 4:
                sell_date_idx = 2
        if cost_idx == -1:
            if len(headers) >= 4:
                cost_idx = 3
        if proceeds_idx == -1:
            if len(headers) >= 5:
                proceeds_idx = 4
                
        for row in rows[header_row_idx + 1:]:
            if not row or len(row) < max(buy_date_idx, sell_date_idx, cost_idx, proceeds_idx) + 1:
                continue
            row_str = " ".join([str(c) for c in row]).lower()
            if "total" in row_str and len(row_str) < 50:
                continue
                
            try:
                symbol = row[sym_idx].strip().upper() if sym_idx != -1 else "VDA"
                buy_date_str = row[buy_date_idx].strip()
                sell_date_str = row[sell_date_idx].strip()
                
                def parse_date(d_str):
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                        try:
                            return datetime.strptime(d_str, fmt).date()
                        except ValueError:
                            continue
                    try:
                        from dateutil import parser as date_parser
                        return date_parser.parse(d_str).date()
                    except Exception:
                        raise ValueError(f"Unable to parse VDA date: {d_str}")
                        
                buy_date = parse_date(buy_date_str)
                sell_date = parse_date(sell_date_str)
                
                cost_val = float(re.sub(r"[^\d\.\-]", "", row[cost_idx]))
                proceeds_val = float(re.sub(r"[^\d\.\-]", "", row[proceeds_idx]))
                
                is_usd = any("$" in row[cost_idx] or "$" in row[proceeds_idx] or "usd" in h for h in headers)
                if is_usd:
                    buy_rate = self.rate_resolver.resolve_rule_115_rate(buy_date)
                    sell_rate = self.rate_resolver.resolve_rule_115_rate(sell_date)
                    cost_inr = cost_val * buy_rate
                    proceeds_inr = proceeds_val * sell_rate
                else:
                    cost_inr = cost_val
                    proceeds_inr = proceeds_val
                    
                records.append({
                    "symbol": symbol,
                    "buy_date": buy_date.isoformat() if hasattr(buy_date, "isoformat") else buy_date,
                    "sell_date": sell_date.isoformat() if hasattr(sell_date, "isoformat") else sell_date,
                    "cost_usd": cost_val if is_usd else 0.0,
                    "proceeds_usd": proceeds_val if is_usd else 0.0,
                    "cost_inr": cost_inr,
                    "proceeds_inr": proceeds_inr,
                    "gain_inr": max(0.0, proceeds_inr - cost_inr)
                })
            except Exception as e:
                logger.warning(f"Failed to parse VDA row {row}: {e}")
                continue
                
        return records
