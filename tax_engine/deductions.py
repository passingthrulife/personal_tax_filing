import logging

logger = logging.getLogger(__name__)

class DeductionsCalculatorMixin:
    def calculate_deductions(
        self,
        inputs: dict,
        form16: dict,
        is_senior: bool,
        savings_interest: float,
        fd_interest: float
    ) -> tuple:
        """
        Calculates Chapter VIA deductions under the Old Regime.
        Returns a tuple of (ded_80c, ded_80d, ded_80ccd_1b, ded_80tta, ded_80ttb, total_deductions).
        """
        home_loan_principal = float(inputs.get("home_loan_principal", 0.0))
        custom_80c = float(inputs.get("custom_80c", 0.0))
        custom_80d = float(inputs.get("custom_80d", 0.0))
        custom_80ccd_1b = float(inputs.get("custom_80ccd_1b", 0.0))

        total_80c_investment = float(form16.get("deduction_80c", 0.0)) + home_loan_principal + custom_80c
        ded_80c = min(150000.0, total_80c_investment)
        
        ded_80d = min(25000.0, float(form16.get("deduction_80d", 0.0)) + custom_80d)

        total_nps_1b = float(form16.get("deduction_80ccd_1b", 0.0)) + custom_80ccd_1b
        ded_80ccd_1b = min(50000.0, total_nps_1b)
        
        ded_80tta = 0.0
        ded_80ttb = 0.0
        if is_senior:
            ded_80ttb = min(50000.0, savings_interest + fd_interest)
        else:
            ded_80tta = min(10000.0, savings_interest)
        
        total_deductions = ded_80c + ded_80d + ded_80tta + ded_80ttb + ded_80ccd_1b
        return ded_80c, ded_80d, ded_80ccd_1b, ded_80tta, ded_80ttb, total_deductions
