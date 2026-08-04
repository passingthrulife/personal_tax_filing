import sys
import os
import unittest
from datetime import date

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parsers import DocumentParser
from rate_resolver import RateResolver
from tax_engine import TaxCalculator

class TestMutualFunds(unittest.TestCase):
    def setUp(self):
        self.resolver = RateResolver()
        self.parser = DocumentParser(self.resolver)
        self.calculator = TaxCalculator(fy="2025-26")
        self.pdf_path = "/Users/Karthik/Documents/Karthik Personal/Taxes/Tax AY 2025-26/Karthik Tax/Mirae Large Cap P&L.pdf"

    def test_parser_and_fifo(self):
        # 1. Read the Mirae PDF file
        self.assertTrue(os.path.exists(self.pdf_path), "Mirae Large Cap P&L statement PDF not found.")
        with open(self.pdf_path, "rb") as f:
            pdf_bytes = f.read()
            
        # 2. Parse transactions
        records = self.parser.parse_mutual_funds_pdf(pdf_bytes)
        
        # 3. Assertions
        # Total units redeemed should match the sum of matched lots
        total_units = sum(r["quantity"] for r in records)
        self.assertAlmostEqual(total_units, 2156.625, places=3)
        
        # There should be exactly 4 matched FIFO lots
        self.assertEqual(len(records), 4)
        
        # Verify first lot (Opening Balance grandfathered lot)
        first_lot = records[0]
        self.assertEqual(first_lot["buy_date"], date(2018, 1, 31))
        self.assertEqual(first_lot["fmv_31_jan_2018"], 51.7990)
        self.assertEqual(first_lot["quantity"], 1612.500)
        
        # 4. Compute capital gains
        results = self.calculator.calculate_capital_gains(records)
        txs = results["transactions"]
        
        # Verify grandfathering cost was applied:
        # buy_price_inr should be 51.7990 for the first lot, since buy_date <= 31/01/2018
        self.assertAlmostEqual(txs[0]["buy_val_inr"] / txs[0]["quantity"], 51.7990, places=4)
        
        # Total gain should match manual calculations
        total_gains = sum(tx["gain_inr"] for tx in txs)
        self.assertAlmostEqual(total_gains, 135285.53, places=1)
        
        # Verify they are categorized under Section 112A
        for tx in txs:
            self.assertEqual(tx["section"], "Sec 112A")
            self.assertEqual(tx["asset_type"], "equity_mf")

    def test_section_50aa_specified_fund(self):
        # Test a specified mutual fund (debt fund) acquired on or after April 1, 2023
        debt_tx = [
            {
                "symbol": "SBI Debt Fund",
                "isin": "INF200K01010",
                "quantity": 100.0,
                "buy_date": date(2023, 6, 1),
                "buy_price_inr": 10.0,
                "sell_date": date(2025, 6, 1),
                "sell_price_inr": 12.0,
                "asset_type": "specified_mf",
                "is_us": False
            }
        ]
        results = self.calculator.calculate_capital_gains(debt_tx)
        processed = results["transactions"][0]
        
        # Should be STCG regardless of holding period (2 years) u/s 50AA
        self.assertEqual(processed["section"], "Sec 50AA")
        self.assertEqual(processed["type"], "STCG")
        self.assertEqual(processed["rate"], "Slab")
        
        # Should be sorted into STCG unlisted bucket
        self.assertAlmostEqual(results["net_gains"]["stcg_unlisted"], 200.0, places=2)

    def test_other_hybrid_fund(self):
        # Test a hybrid fund (equity between 35% and 65%) held for 2.5 years (LTCG)
        hybrid_tx = [
            {
                "symbol": "ICICI Hybrid Fund",
                "isin": "INF109K01010",
                "quantity": 50.0,
                "buy_date": date(2022, 1, 1),
                "buy_price_inr": 100.0,
                "sell_date": date(2024, 8, 1), # Held for > 24 months, sold after July 23, 2024
                "sell_price_inr": 130.0,
                "asset_type": "other_mf",
                "is_us": False
            }
        ]
        results = self.calculator.calculate_capital_gains(hybrid_tx)
        processed = results["transactions"][0]
        
        # Should be LTCG u/s 112 (non-equity LTCG threshold is 24 months)
        self.assertEqual(processed["section"], "Sec 112")
        self.assertEqual(processed["type"], "LTCG")
        self.assertEqual(processed["rate"], 12.5) # 12.5% rate without indexation post July 2024
        
        # Should be sorted into LTCG unlisted bucket
        self.assertAlmostEqual(results["net_gains"]["ltcg_unlisted"], 1500.0, places=2)

    def test_nps_deduction(self):
        # 1. Prepare inputs with 1.5L 80C and 50k NPS contribution
        inputs = {
            "form16": {
                "deduction_80c": 120000.0, # 1.2L EPF/80C
                "deduction_80ccd_1b": 30000.0 # 30k NPS in Form 16
            },
            "custom_80c": 40000.0, # Additional 40k PPF
            "custom_80ccd_1b": 25000.0, # Additional 25k NPS
            "home_loan_principal": 0.0,
            "custom_80d": 0.0,
            "savings_interest": 0.0,
            "fd_interest": 0.0,
            "dob": "1990-01-01"
        }
        res = self.calculator.compute_tax_liability(inputs)
        old_regime = res["regimes"]["old"]
        
        # 80C should be capped at 1.5L
        self.assertEqual(old_regime["deductions"]["80C"], 150000.0)
        # 80CCD_1B should be capped at 50k
        self.assertEqual(old_regime["deductions"]["80CCD_1B"], 50000.0)
        # Total Chapter VI-A deductions should sum to 2.0L
        self.assertEqual(old_regime["deductions"]["total"], 200000.0)

if __name__ == "__main__":
    unittest.main()
