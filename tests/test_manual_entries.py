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

    def test_marginal_relief_surcharge_new(self):
        from tax_engine import TaxCalculator
        calc = TaxCalculator(fy="2025-26")
        
        # Scenario: Salary = 49L, LTCG 112A = 2L
        inputs = {
            "form16": {
                "gross_salary_17_1": 4900000.0,
                "gross_salary_17_2": 0.0,
                "gross_salary_17_3": 0.0,
                "perquisites_value": 0.0,
                "profits_in_lieu_of_salary": 0.0,
                "allowances_exempt": 0.0,
                "deductions_16": 0.0
            },
            "dob": "28051987", # Under 60 years old
            "stock_sales": [
                {
                    "symbol": "TCS",
                    "isin": "INE467B01029",
                    "quantity": 100,
                    "buy_date": "2020-04-10",
                    "buy_price_inr": 1000.0,
                    "sell_date": "2025-08-01",
                    "sell_price_inr": 3000.0,
                    "transfer_expenses": 0.0,
                    "is_us": False,
                    "asset_type": "stock"
                }
            ]
        }
        
        res = calc.compute_tax_liability(inputs)
        new_regime = res["regimes"]["new"]
        
        # Taxable Slab Income = 49L - 75k = 48.25L
        # Total Income = 48.25L + 2L = 50.25L
        # Without relief, surcharge is 10% of basic tax (~1,05,687.50).
        # With marginal relief, surcharge is capped at ~17,676.
        # Let's assert surcharge is capped and is less than 20,000.
        self.assertTrue(new_regime["surcharge"] > 0)
        self.assertLess(new_regime["surcharge"], 20000)
        self.assertAlmostEqual(new_regime["surcharge"], 17676.61, delta=100.0)

    def test_marginal_relief_surcharge_old(self):
        from tax_engine import TaxCalculator
        calc = TaxCalculator(fy="2025-26")
        
        # Scenario: Salary = 49L, LTCG 112A = 2L
        inputs = {
            "form16": {
                "gross_salary_17_1": 4900000.0,
                "gross_salary_17_2": 0.0,
                "gross_salary_17_3": 0.0,
                "perquisites_value": 0.0,
                "profits_in_lieu_of_salary": 0.0,
                "allowances_exempt": 0.0,
                "deductions_16": 0.0
            },
            "dob": "28051987",
            "stock_sales": [
                {
                    "symbol": "TCS",
                    "isin": "INE467B01029",
                    "quantity": 100,
                    "buy_date": "2020-04-10",
                    "buy_price_inr": 1000.0,
                    "sell_date": "2025-08-01",
                    "sell_price_inr": 3000.0,
                    "transfer_expenses": 0.0,
                    "is_us": False,
                    "asset_type": "stock"
                }
            ]
        }
        
        res = calc.compute_tax_liability(inputs)
        old_regime = res["regimes"]["old"]
        
        # Taxable Slab Income = 49L - 50k = 48.50L
        # Total Income = 48.50L + 2L = 50.50L
        # Without relief, surcharge is 10% of basic tax (~1,27,687.50).
        # With marginal relief, surcharge is capped at ~35,346.53.
        # Let's assert surcharge is capped and is less than 40,000.
        self.assertTrue(old_regime["surcharge"] > 0)
        self.assertLess(old_regime["surcharge"], 40000)
        self.assertAlmostEqual(old_regime["surcharge"], 35346.53, delta=100.0)

if __name__ == "__main__":
    unittest.main()
