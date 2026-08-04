import logging

logger = logging.getLogger(__name__)

class SlabsAndRebatesCalculatorMixin:
    def calculate_slab_tax(self, taxable_income: float, is_new_regime: bool) -> tuple:
        """
        Calculates basic tax according to slabs for the given regime and FY.
        Returns (tax_amount, slab_breakdown_list).
        """
        breakdown = []
        tax = 0.0
        
        if is_new_regime:
            if self.fy == "2025-26":
                # FY 2025-26 New Regime Slabs
                slabs = [
                    (400000, 0.0),
                    (800000, 0.05),
                    (1200000, 0.10),
                    (1600000, 0.15),
                    (2000000, 0.20),
                    (2400000, 0.25),
                    (float('inf'), 0.30)
                ]
            else:
                # FY 2024-25 New Regime Slabs
                slabs = [
                    (300000, 0.0),
                    (600000, 0.05),
                    (900000, 0.10),
                    (1200000, 0.15),
                    (1500000, 0.20),
                    (float('inf'), 0.30)
                ]
        else:
            # Old Regime (same for both years)
            slabs = [
                (250000, 0.0),
                (500000, 0.05),
                (1000000, 0.20),
                (float('inf'), 0.30)
            ]

        remaining_income = taxable_income
        previous_limit = 0
        
        for limit, rate in slabs:
            slab_width = limit - previous_limit
            if remaining_income > slab_width:
                taxable_in_slab = slab_width
            else:
                taxable_in_slab = max(0.0, remaining_income)
                
            slab_tax = taxable_in_slab * rate
            tax += slab_tax
            
            if taxable_in_slab > 0:
                def format_limit_lakhs(limit_val: float) -> str:
                    if limit_val == 0:
                        return "₹0"
                    if limit_val == float('inf'):
                        return "Above"
                    val = limit_val / 100000.0
                    if val.is_integer():
                        return f"₹{int(val)}L"
                    else:
                        return f"₹{val:.1f}L"
                
                slab_str = f"Above {format_limit_lakhs(previous_limit)}" if limit == float('inf') else f"{format_limit_lakhs(previous_limit)} to {format_limit_lakhs(limit)}"
                breakdown.append({
                    "slab": slab_str,
                    "taxable_amount": taxable_in_slab,
                    "rate": f"{int(rate * 100)}%",
                    "tax": slab_tax
                })
                
            remaining_income -= slab_width
            if remaining_income <= 0:
                break
            previous_limit = limit

        # Apply Section 87A rebate
        rebate = 0.0
        if is_new_regime:
            if self.fy == "2025-26" and taxable_income <= 1200000:
                rebate = tax
            elif self.fy == "2024-25" and taxable_income <= 700000:
                rebate = tax
        else:
            if taxable_income <= 500000:
                rebate = min(tax, 12500.0)

        tax = max(0.0, tax - rebate)
        if rebate > 0:
            breakdown.append({
                "slab": "Section 87A Rebate",
                "taxable_amount": 0,
                "rate": "Rebate",
                "tax": -rebate
            })

        return tax, breakdown

    def calculate_surcharge(self, is_new: bool, taxable_slab_income: float, special_cg_income: float, dividend_income: float, basic_tax: float, slab_tax: float, cg_tax: float, vda_income: float = 0.0) -> float:
        total_income = taxable_slab_income + special_cg_income + vda_income
        if total_income <= 5000000.0:
            return 0.0
            
        if total_income <= 10000000.0:
            return basic_tax * 0.10
        elif total_income <= 20000000.0:
            return basic_tax * 0.15
            
        cg_special_tax = cg_tax
        if taxable_slab_income > 0:
            slab_tax_on_div = slab_tax * (min(dividend_income, taxable_slab_income) / taxable_slab_income)
        else:
            slab_tax_on_div = 0.0
            
        tax_capped = cg_special_tax + slab_tax_on_div
        tax_other = max(0.0, basic_tax - tax_capped)
        
        surcharge_capped = tax_capped * 0.15
        
        other_income = total_income - (dividend_income + special_cg_income)
        if other_income <= 20000000.0:
            rate_other = 0.15
        elif other_income <= 50000000.0:
            rate_other = 0.25
        else:
            rate_other = 0.25 if is_new else 0.37
            
        surcharge_other = tax_other * rate_other
        return surcharge_capped + surcharge_other
