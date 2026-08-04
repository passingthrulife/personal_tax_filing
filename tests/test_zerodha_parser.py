import sys
import os
import unittest
from datetime import date

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parsers import DocumentParser
from rate_resolver import RateResolver

class TestZerodhaParser(unittest.TestCase):
    def setUp(self):
        self.resolver = RateResolver()
        self.parser = DocumentParser(self.resolver)
        self.sample_path = "/Users/Karthik/Documents/Karthik Personal/Taxes/Adithi AY 2026-27/taxpnl-IQG660-2025_2026-Q1-Q4.xlsx"

    def test_zerodha_pnl_parsing(self):
        if not os.path.exists(self.sample_path):
            self.skipTest("Sample Zerodha P&L statement file not found at " + self.sample_path)
            
        with open(self.sample_path, "rb") as f:
            file_bytes = f.read()
            
        records = self.parser.parse_zerodha_excel(file_bytes)
        self.assertGreater(len(records), 0, "No records parsed from Zerodha P&L statement!")
        
        # Verify the mutual fund transaction lot details
        mf_lot = next((r for r in records if r["symbol"] == "QUANT INFRASTRUCTURE FUND - DIRECT PLAN"), None)
        self.assertIsNotNone(mf_lot, "Quant Infrastructure Fund lot was not found in parsed records!")
        
        self.assertEqual(mf_lot["isin"], "INF966L01721")
        self.assertEqual(mf_lot["quantity"], 4356.805)
        self.assertEqual(mf_lot["buy_date"], date(2024, 8, 9))
        self.assertEqual(mf_lot["sell_date"], date(2025, 9, 25))
        self.assertAlmostEqual(mf_lot["buy_price"], 199989.9842 / 4356.805, places=5)
        self.assertAlmostEqual(mf_lot["sell_price"], 181125.4543 / 4356.805, places=5)
        self.assertEqual(mf_lot["transfer_expenses"], 0.0)
        self.assertEqual(mf_lot["asset_type"], "equity_mf")
        self.assertFalse(mf_lot["is_us"])

if __name__ == "__main__":
    unittest.main()
