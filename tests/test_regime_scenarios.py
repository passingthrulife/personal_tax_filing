import sys
import os
import unittest
from datetime import date

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tax_engine import TaxCalculator

class TestRegimeScenarios(unittest.TestCase):
    def test_standard_deduction_fy_2025_26(self):
        # Salary = 6L
        calc = TaxCalculator(fy="2025-26")
        inputs = {
            "form16": {
                "gross_salary_17_1": 600000.0,
            },
            "dob": "01011990"
        }
        res = calc.compute_tax_liability(inputs)
        
        # We verify standard deduction implicitly by checking the taxable slab income after standard deduction
        # New Regime Standard Deduction: 75,000 -> 6,00,000 - 75,000 = 5,25,000
        # Old Regime Standard Deduction: 50,000 -> 6,00,000 - 50,000 = 5,50,000
        self.assertEqual(res["regimes"]["new"]["taxable_slab_income"], 525000.0)
        self.assertEqual(res["regimes"]["old"]["taxable_slab_income"], 550000.0)

    def test_standard_deduction_fy_2024_25(self):
        # Salary = 6L
        calc = TaxCalculator(fy="2024-25")
        inputs = {
            "form16": {
                "gross_salary_17_1": 600000.0,
            },
            "dob": "01011990"
        }
        res = calc.compute_tax_liability(inputs)
        
        # For FY 2024-25, Standard Deduction is 50,000 under both regimes
        # New: 6,00,000 - 50,000 = 5,50,000
        # Old: 6,00,000 - 50,000 = 5,50,000
        self.assertEqual(res["regimes"]["new"]["taxable_slab_income"], 550000.0)
        self.assertEqual(res["regimes"]["old"]["taxable_slab_income"], 550000.0)

    def test_hra_exemption(self):
        # Salary: 12L (gross_salary_17_1 = 12L)
        # HRA received: 5L, Rent paid: 3.6L, Non-Metro (40% limit)
        # Limits:
        # 1. Received HRA = 5,00,000
        # 2. Rent paid - 10% of basic = 3,60,000 - 10% of 12,00,000 = 2,40,000
        # 3. 40% of basic = 4,80,000
        # Minimum of these = 2,40,000
        calc = TaxCalculator(fy="2025-26")
        inputs = {
            "form16": {
                "gross_salary_17_1": 1200000.0,
            },
            "hra_basic": 1200000.0,
            "hra_received": 500000.0,
            "hra_rent": 360000.0,
            "hra_metro": False,
            "dob": "01011990"
        }
        res = calc.compute_tax_liability(inputs)
        
        # Old Regime: HRA exempt should be 2,40,000
        self.assertEqual(res["regimes"]["old"]["hra_exempt"], 240000.0)
        # New Regime: HRA exempt should be 0.0
        self.assertEqual(res["regimes"]["new"]["hra_exempt"], 0.0)

    def test_section_87a_rebate(self):
        calc = TaxCalculator(fy="2025-26")
        
        # Scenario 1: Taxable income <= 5L (e.g. Salary = 5L)
        # Net Slab Income (New): 5L - 75k = 4.25L. Slab Tax: 5% of 25k = 1,250. Rebate u/s 87A = 1,250. Net = 0.
        # Net Slab Income (Old): 5L - 50k = 4.50L. Slab Tax: 5% of 2L = 10,000. Rebate u/s 87A = 10,000. Net = 0.
        inputs_1 = {
            "form16": {
                "gross_salary_17_1": 500000.0,
            },
            "dob": "01011990"
        }
        res_1 = calc.compute_tax_liability(inputs_1)
        self.assertEqual(res_1["regimes"]["new"]["net_tax_payable"], 0.0)
        self.assertEqual(res_1["regimes"]["old"]["net_tax_payable"], 0.0)

        # Scenario 2: Taxable income = 11L (e.g. Salary = 11L)
        # Net Slab Income (New): 11L - 75k = 10.25L. Below 12L threshold -> Section 87A rebate covers all slab tax.
        # Net Slab Income (Old): 11L - 50k = 10.50L. Above 5L threshold -> No Section 87A rebate under Old Regime.
        inputs_2 = {
            "form16": {
                "gross_salary_17_1": 1100000.0,
            },
            "dob": "01011990"
        }
        res_2 = calc.compute_tax_liability(inputs_2)
        self.assertEqual(res_2["regimes"]["new"]["net_tax_payable"], 0.0)
        self.assertTrue(res_2["regimes"]["old"]["net_tax_payable"] > 0)

    def test_surcharge_capping(self):
        calc = TaxCalculator(fy="2025-26")
        
        # Scenario: Slab Income = 50L (Salary 50.75L - 75k SD = 50L), LTCG 112A = 2 Crore
        # Total Income = 2.5 Crore.
        # Surcharge rate on slab income of 50L: 15% (since total income > 2 Cr).
        # Surcharge rate on LTCG of 2 Crore: capped at 15%.
        inputs = {
            "form16": {
                "gross_salary_17_1": 5075000.0,
            },
            "dob": "01011990",
            "stock_sales": [
                {
                    "symbol": "TCS",
                    "isin": "INE467B01029",
                    "quantity": 1000,
                    "buy_date": "2020-04-10",
                    "buy_price_inr": 10000.0,
                    "sell_date": "2025-08-01",
                    "sell_price_inr": 30000.0,
                    "transfer_expenses": 0.0,
                    "is_us": False,
                    "asset_type": "stock"
                }
            ]
        }
        res = calc.compute_tax_liability(inputs)
        
        # Verify New Regime surcharge matches the engine's correct calculations
        new_reg = res["regimes"]["new"]
        self.assertAlmostEqual(new_reg["surcharge"], 534656.25, delta=100.0)

    def test_section_234b_and_234c_interest(self):
        calc = TaxCalculator(fy="2025-26")
        
        # Scenario where tax is due and no advance tax paid -> Should calculate 234B & 234C interest
        inputs = {
            "form16": {
                "gross_salary_17_1": 3000000.0,
            },
            "dob": "01011990",
            "advance_tax": 0.0
        }
        res = calc.compute_tax_liability(inputs)
        new_reg = res["regimes"]["new"]
        
        self.assertTrue(new_reg["interest_234b"] > 0)
        self.assertTrue(new_reg["interest_234c"] > 0)
        
        # Verify total tax, surcharge & interest ordering
        expected_total = new_reg["net_tax_payable"] + new_reg["interest_234b"] + new_reg["interest_234c"]
        self.assertAlmostEqual(new_reg["total_tax_surcharge_interest"], expected_total, places=2)

    def test_surcharge_capping_high_income_old_regime(self):
        calc = TaxCalculator(fy="2025-26")
        inputs = {
            "form16": {
                "gross_salary_17_1": 60050000.0,
            },
            "ais": {
                "domestic_dividends": 5000000.0
            },
            "dob": "01011990",
            "stock_sales": [
                {
                    "symbol": "TCS",
                    "isin": "INE467B01029",
                    "quantity": 10000,
                    "buy_date": "2025-05-10",
                    "buy_price_inr": 2000.0,
                    "sell_date": "2025-08-01",
                    "sell_price_inr": 3000.0,
                    "transfer_expenses": 0.0,
                    "is_us": False,
                    "asset_type": "stock" # STCG Listed u/s 111A
                }
            ]
        }
        res = calc.compute_tax_liability(inputs)
        old_reg = res["regimes"]["old"]
        
        # Slab Income: 6 Crore. STCG 111A: 1 Crore. Dividends: 50L. Total: 7.5 Crore.
        # Surcharge on special CG + dividends is capped at 15%.
        # Surcharge on salary is 37% (Old Regime).
        self.assertTrue(old_reg["surcharge"] > 0)
        # Surcharge is capped appropriately: 71,18,798.08 instead of uncapped 78,07,925
        self.assertAlmostEqual(old_reg["surcharge"], 7118798.08, delta=100.0)

    def test_surcharge_capping_high_income_new_regime(self):
        calc = TaxCalculator(fy="2025-26")
        inputs = {
            "form16": {
                "gross_salary_17_1": 60075000.0,
            },
            "ais": {
                "domestic_dividends": 5000000.0
            },
            "dob": "01011990",
            "stock_sales": [
                {
                    "symbol": "TCS",
                    "isin": "INE467B01029",
                    "quantity": 10000,
                    "buy_date": "2025-05-10",
                    "buy_price_inr": 2000.0,
                    "sell_date": "2025-08-01",
                    "sell_price_inr": 3000.0,
                    "transfer_expenses": 0.0,
                    "is_us": False,
                    "asset_type": "stock"
                }
            ]
        }
        res = calc.compute_tax_liability(inputs)
        new_reg = res["regimes"]["new"]
        
        # Surcharge on salary is 25% (New Regime). Surcharge on CG + div is 15%.
        self.assertTrue(new_reg["surcharge"] > 0)
        # Surcharge is capped appropriately: 49,23,230.77 instead of uncapped 52,75,625
        self.assertAlmostEqual(new_reg["surcharge"], 4923230.77, delta=100.0)

if __name__ == "__main__":
    unittest.main()
