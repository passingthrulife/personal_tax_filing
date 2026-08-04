import sys
import os
import unittest
from datetime import date

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parsers import DocumentParser
from rate_resolver import RateResolver

class TestIciciDirectParser(unittest.TestCase):
    def setUp(self):
        self.resolver = RateResolver()
        self.parser = DocumentParser(self.resolver)
        self.sample_path = "/Users/Karthik/Documents/Karthik Personal/Taxes/Tax AY 2027-28/ICICI P&L.csv"

    def test_icici_direct_parsing(self):
        if not os.path.exists(self.sample_path):
            self.skipTest("Sample ICICI P&L statement file not found at " + self.sample_path)
            
        with open(self.sample_path, "r", encoding="utf-8", errors="ignore") as f:
            csv_content = f.read()
            
        records = self.parser.parse_stock_sales_csv(csv_content, is_us=False)
        self.assertEqual(len(records), 1, "Should parse exactly 1 record from the statement!")
        
        item = records[0]
        self.assertEqual(item["symbol"], "LT")
        self.assertEqual(item["isin"], "INE018A01030")
        self.assertEqual(item["quantity"], 5.0)
        self.assertEqual(item["buy_date"], date(2025, 1, 10))
        self.assertEqual(item["sell_date"], date(2026, 6, 15))
        self.assertAlmostEqual(item["buy_price"], 3530.90, places=2)
        self.assertAlmostEqual(item["sell_price"], 4149.45, places=2)
        self.assertEqual(item["transfer_expenses"], 0.0)
        self.assertFalse(item["is_us"])

if __name__ == "__main__":
    unittest.main()
