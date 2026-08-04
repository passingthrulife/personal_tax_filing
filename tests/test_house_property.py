import sys
import os
import unittest
import json
from unittest.mock import MagicMock

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tax_engine import HousePropertyCalculator
from backend import app

class TestHouseProperty(unittest.TestCase):
    def setUp(self):
        self.calculator = HousePropertyCalculator()
        self.client = app.test_client()

    def test_self_occupied_property_old_regime(self):
        # SOP with 2.5L interest -> Capped at 2L under Old Regime
        properties = [
            {
                "property_type": "SOP",
                "gross_rent": 0.0,
                "municipal_taxes": 0.0,
                "home_loan_interest": 250000.0
            }
        ]
        res = self.calculator.calculate_house_property_income(properties, is_new=False)
        self.assertEqual(res["allowed_setoff"], -200000.0)
        self.assertEqual(res["carry_forward_loss"], 0.0)
        
    def test_self_occupied_property_new_regime(self):
        # SOP interest is completely ignored under New Regime
        properties = [
            {
                "property_type": "SOP",
                "gross_rent": 0.0,
                "municipal_taxes": 0.0,
                "home_loan_interest": 150000.0
            }
        ]
        res = self.calculator.calculate_house_property_income(properties, is_new=True)
        self.assertEqual(res["allowed_setoff"], 0.0)
        self.assertEqual(res["carry_forward_loss"], 0.0)

    def test_let_out_property_deductions(self):
        # LOP: Rent 5L, taxes 50k, interest 1L
        # GAV = 5,00,000
        # Taxes = 50,000 -> NAV = 4,50,000
        # Standard deduction = 30% of 4.5L = 1,35,000
        # Net Income = NAV - Std Ded - Interest = 4.5L - 1.35L - 1L = 2,15,000
        properties = [
            {
                "property_type": "LOP",
                "gross_rent": 500000.0,
                "municipal_taxes": 50000.0,
                "home_loan_interest": 100000.0
            }
        ]
        res = self.calculator.calculate_house_property_income(properties, is_new=False)
        self.assertEqual(res["total_income_before_setoff"], 215000.0)
        self.assertEqual(res["allowed_setoff"], 215000.0)
        self.assertEqual(res["carry_forward_loss"], 0.0)
        
        # Standard deduction is the same under new regime
        res_new = self.calculator.calculate_house_property_income(properties, is_new=True)
        self.assertEqual(res_new["allowed_setoff"], 215000.0)

    def test_aggregate_setoff_limits(self):
        # SOP loss 1.5L, LOP loss 1.5L -> Total HP Loss 3L
        # Old Regime: setoff capped at -2L, carry-forward loss -1L
        # New Regime: setoff is 0, carry-forward loss -3L
        properties = [
            {
                "property_type": "SOP",
                "gross_rent": 0.0,
                "municipal_taxes": 0.0,
                "home_loan_interest": 150000.0
            },
            {
                "property_type": "LOP",
                "gross_rent": 100000.0,
                "municipal_taxes": 10000.0,
                "home_loan_interest": 200000.0
                # GAV=100k, taxes=10k -> NAV=90k, Std Ded=27k
                # Net LOP = 90k - 27k - 200k = -137,000
            }
        ]
        res_old = self.calculator.calculate_house_property_income(properties, is_new=False)
        # Total loss = -150k (SOP) + -137k (LOP) = -287,000
        self.assertEqual(res_old["total_income_before_setoff"], -287000.0)
        self.assertEqual(res_old["allowed_setoff"], -200000.0)
        self.assertEqual(res_old["carry_forward_loss"], -87000.0)
        
        res_new = self.calculator.calculate_house_property_income(properties, is_new=True)
        # SOP is 0 under new regime, so total loss is just LOP loss of -200k + 90k - 27k = -137,000
        self.assertEqual(res_new["total_income_before_setoff"], -137000.0)
        self.assertEqual(res_new["allowed_setoff"], 0.0)
        self.assertEqual(res_new["carry_forward_loss"], -137000.0)

    def test_legacy_fallback_compatibility(self):
        # Verify that if no properties list is sent, the app falls back to the home_loan_interest input
        response = self.client.post("/api/process", data={
            "pan": "ABCDE1234F",
            "dob": "31121990",
            "fy": "2025-26",
            "home_loan_interest": "150000.0"
        })
        self.assertEqual(response.status_code, 200)
        res_data = response.json
        self.assertTrue(res_data["success"])
        
        # Verify old regime has -150,000.0 house property income and new regime has 0.0
        old_res = res_data["results"]["regimes"]["old"]
        new_res = res_data["results"]["regimes"]["new"]
        self.assertEqual(old_res["house_property_income"], -150000.0)
        self.assertEqual(new_res["house_property_income"], 0.0)

if __name__ == "__main__":
    unittest.main()
