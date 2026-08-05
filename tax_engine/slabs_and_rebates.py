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

    def compute_basic_tax_components(self, is_new: bool, slab_income: float, stcg_listed: float, ltcg_listed: float, ltcg_unlisted: float, vda_gains: float, rates_info: dict) -> tuple:
        slab_tax, _ = self.calculate_slab_tax(slab_income, is_new)
        
        stcg_listed_tax = stcg_listed * rates_info.get("rate_111a", 0.15)
        
        exemption_limit = 125000.0 if self.fy == "2025-26" else 100000.0
        taxable_ltcg_112a = max(0.0, ltcg_listed - exemption_limit)
        ltcg_listed_tax = taxable_ltcg_112a * rates_info.get("rate_112a", 0.10)
        
        ltcg_unlisted_tax = ltcg_unlisted * rates_info.get("rate_112", 0.125)
        total_cg_tax = stcg_listed_tax + ltcg_listed_tax + ltcg_unlisted_tax
        
        vda_tax = vda_gains * 0.30
        basic_tax = slab_tax + total_cg_tax + vda_tax
        return basic_tax, slab_tax, total_cg_tax

    def calculate_surcharge_with_relief(
        self,
        is_new: bool,
        taxable_slab_income: float,
        special_cg_income: float,
        dividend_income: float,
        basic_tax: float,
        slab_tax: float,
        cg_tax: float,
        vda_income: float,
        stcg_listed: float,
        ltcg_listed: float,
        ltcg_unlisted: float,
        rates_info: dict
    ) -> float:
        # Standard surcharge
        surcharge = self.calculate_surcharge(
            is_new, taxable_slab_income, special_cg_income,
            dividend_income, basic_tax, slab_tax, cg_tax, vda_income
        )
        
        # Apply Surcharge Marginal Tax Relief
        total_income = taxable_slab_income + special_cg_income + vda_income
        if total_income > 5000000.0:
            if total_income <= 10000000.0:
                T = 5000000.0
            elif total_income <= 20000000.0:
                T = 10000000.0
            elif total_income <= 50000000.0:
                T = 20000000.0
            else:
                T = 50000000.0

            # Compute components at threshold T
            F = T / total_income
            slab_inc_T = taxable_slab_income * F
            stcg_l_T = stcg_listed * F
            ltcg_l_T = ltcg_listed * F
            ltcg_unl_T = ltcg_unlisted * F
            vda_gains_T = vda_income * F
            div_income_T = dividend_income * F
            special_cg_inc_T = stcg_l_T + ltcg_l_T + ltcg_unl_T

            # Compute basic tax components at T
            basic_tax_T, slab_tax_T, total_cg_tax_T = self.compute_basic_tax_components(
                is_new, slab_inc_T, stcg_l_T, ltcg_l_T, ltcg_unl_T, vda_gains_T, rates_info
            )

            # Compute surcharge at T
            surcharge_T = self.calculate_surcharge(
                is_new, slab_inc_T, special_cg_inc_T, div_income_T,
                basic_tax_T, slab_tax_T, total_cg_tax_T, vda_gains_T
            )

            # Max allowed tax + surcharge = Tax(T) + Surcharge(T) + (total_income - T)
            max_tax_surcharge = basic_tax_T + surcharge_T + (total_income - T)
            
            # Capped surcharge
            surcharge_capped = max(0.0, max_tax_surcharge - basic_tax)
            if surcharge > surcharge_capped:
                surcharge = surcharge_capped
                
        return surcharge
