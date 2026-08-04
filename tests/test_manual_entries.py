import sys
import os
import unittest
import json
import io
from datetime import date
from unittest.mock import MagicMock

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend import app
from rate_resolver import RateResolver

class TestManualEntries(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.rate_resolver = RateResolver()

    def test_conditional_us_dividends_validation(self):
        # 1. No 1042-S uploaded, no US dividends uploaded -> Should NOT throw a validation error (should parse successfully)
        response = self.client.post("/api/process", data={
            "pan": "ABCDE1234F",
            "dob": "31121990",
            "fy": "2025-26",
            "manual_indian_stocks": "[]",
            "manual_us_stocks": "[]"
        })
        # It might return warning about Form 16, but should NOT return 400 Bad Request
        self.assertNotEqual(response.status_code, 400)

        # 2. 1042-S PDF uploaded but NO US dividends uploaded -> Should return 400 Bad Request
        # We mock a small PDF file upload using BytesIO
        pdf_file = io.BytesIO(b"dummy pdf content")
        response = self.client.post("/api/process", data={
            "pan": "ABCDE1234F",
            "dob": "31121990",
            "fy": "2025-26",
            "us_1042s": (pdf_file, "test_1042s.pdf"),
            "manual_indian_stocks": "[]",
            "manual_us_stocks": "[]"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("US Dividends statement file is mandatory when US Form 1042-S is uploaded", response.json["error"])

    def test_manual_indian_stocks_parsing(self):
        # Post a valid manual Indian stock entry
        manual_indian = [
            {
                "symbol": "TCS",
                "isin": "INE467B01029",
                "quantity": "10",
                "buy_date": "2025-04-10",
                "buy_price": "3500.50",
                "sell_date": "2026-02-15",
                "sell_price": "4100.20",
                "transfer_expenses": "50.0"
            }
        ]
        
        response = self.client.post("/api/process", data={
            "pan": "ABCDE1234F",
            "dob": "31121990",
            "fy": "2025-26",
            "manual_indian_stocks": json.dumps(manual_indian),
            "manual_us_stocks": "[]"
        })
        
        self.assertEqual(response.status_code, 200)
        res_data = response.json
        self.assertTrue(res_data["success"])
        
        # Verify manual entry was integrated into parsed raw stocks sales list
        raw_sales = res_data["parsed_raw"]["stock_sales"]
        self.assertEqual(len(raw_sales), 1)
        self.assertEqual(raw_sales[0]["symbol"], "TCS")
        self.assertEqual(raw_sales[0]["isin"], "INE467B01029")
        self.assertEqual(raw_sales[0]["quantity"], 10.0)
        self.assertEqual(raw_sales[0]["buy_price_inr"], 3500.5)
        self.assertEqual(raw_sales[0]["sell_price_inr"], 4100.2)
        self.assertEqual(raw_sales[0]["transfer_expenses"], 50.0)
        self.assertFalse(raw_sales[0]["is_us"])

    def test_manual_us_stocks_currency_conversion(self):
        # Post a valid manual US stock entry
        # Buy date: 2025-05-15 (Preceding month end: 2025-04-30)
        # Sell date: 2026-01-20 (Preceding month end: 2025-12-31)
        manual_us = [
            {
                "symbol": "AAPL",
                "quantity": "5.5",
                "buy_date": "2025-05-15",
                "buy_price": "170.0",
                "sell_date": "2026-01-20",
                "sell_price": "190.0",
                "transfer_expenses": "5.0"
            }
        ]
        
        response = self.client.post("/api/process", data={
            "pan": "ABCDE1234F",
            "dob": "31121990",
            "fy": "2025-26",
            "manual_indian_stocks": "[]",
            "manual_us_stocks": json.dumps(manual_us)
        })
        
        self.assertEqual(response.status_code, 200)
        res_data = response.json
        self.assertTrue(res_data["success"])
        
        raw_sales = res_data["parsed_raw"]["stock_sales"]
        self.assertEqual(len(raw_sales), 1)
        self.assertEqual(raw_sales[0]["symbol"], "AAPL")
        self.assertEqual(raw_sales[0]["quantity"], 5.5)
        self.assertEqual(raw_sales[0]["buy_price"], 170.0)
        self.assertEqual(raw_sales[0]["sell_price"], 190.0)
        self.assertTrue(raw_sales[0]["is_us"])
        
        # Verify currency conversion occurred and populated INR values
        buy_rate = self.rate_resolver.resolve_rule_115_rate(date(2025, 5, 15))
        sell_rate = self.rate_resolver.resolve_rule_115_rate(date(2026, 1, 20))
        self.assertAlmostEqual(raw_sales[0]["buy_price_inr"], 170.0 * buy_rate, places=2)
        self.assertAlmostEqual(raw_sales[0]["sell_price_inr"], 190.0 * sell_rate, places=2)
        self.assertAlmostEqual(raw_sales[0]["transfer_expenses"], 5.0 * sell_rate, places=2)

if __name__ == "__main__":
    unittest.main()
