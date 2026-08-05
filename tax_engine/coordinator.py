import logging
from datetime import datetime, date

from .capital_gains import CapitalGainsCalculatorMixin
from .slabs_and_rebates import SlabsAndRebatesCalculatorMixin
from .interest_calculator import InterestCalculatorMixin
from .foreign_relief import ForeignReliefCalculatorMixin
from .deductions import DeductionsCalculatorMixin
from .house_property import HousePropertyCalculator

logger = logging.getLogger(__name__)

class TaxCalculator(
    CapitalGainsCalculatorMixin,
    SlabsAndRebatesCalculatorMixin,
    InterestCalculatorMixin,
    ForeignReliefCalculatorMixin,
    DeductionsCalculatorMixin
):
    def __init__(self, fy="2025-26"):
        self.fy = fy

    def set_fy(self, fy):
        self.fy = fy


    def compute_tax_liability(self, inputs: dict) -> dict:
        """
        Assembles all income sources, deductions, and computes tax
        under both Old and New regimes.
        """
        form16 = inputs.get("form16", {})
        ais = inputs.get("ais", {})
        stock_sales = inputs.get("stock_sales", [])
        us_dividends = inputs.get("us_dividends", [])
        us_interest = inputs.get("us_interest", [])
        dob_str = inputs.get("dob", "").strip()
        vda_trades = inputs.get("vda_trades", [])
        house_properties = inputs.get("house_properties", [])
        
        total_vda_gains = 0.0
        for t in vda_trades:
            cost = float(t.get("cost_inr", 0.0))
            proceeds = float(t.get("proceeds_inr", 0.0))
            gain = max(0.0, proceeds - cost)
            t["gain_inr"] = gain
            total_vda_gains += gain
        
        is_senior = False
        if dob_str and len(dob_str) == 8:
            try:
                dob_day = int(dob_str[:2])
                dob_month = int(dob_str[2:4])
                dob_year = int(dob_str[4:])
                fy_start_year = int(self.fy.split("-")[0])
                fy_end_date = date(fy_start_year + 1, 3, 31)
                
                age = fy_end_date.year - dob_year - ((fy_end_date.month, fy_end_date.day) < (dob_month, dob_day))
                if age >= 60:
                    is_senior = True
            except Exception as e:
                logger.warning(f"Failed to calculate age from DOB '{dob_str}': {e}")
        
        home_loan_principal = float(inputs.get("home_loan_principal", 0.0))
        advance_tax_paid = float(inputs.get("advance_tax_paid", ais.get("advance_tax_paid", 0.0)))

        hra_basic = float(inputs.get("hra_basic") or 0.0)
        hra_received = float(inputs.get("hra_received") or 0.0)
        hra_rent = float(inputs.get("hra_rent") or 0.0)
        hra_metro = inputs.get("hra_metro") in [True, "true", "True", 1, "1"]
        
        hra_exempt = 0.0
        if hra_received > 0 and hra_basic > 0:
            limit_1 = hra_received
            limit_2 = max(0.0, hra_rent - (0.10 * hra_basic))
            limit_3 = (0.50 * hra_basic) if hra_metro else (0.40 * hra_basic)
            hra_exempt = min(limit_1, limit_2, limit_3)

        gross_salary = (
            float(form16.get("gross_salary_17_1", 0.0)) +
            float(form16.get("perquisites_17_2", 0.0)) +
            float(form16.get("profits_lieu_17_3", 0.0))
        )
        exempt_allowances = float(form16.get("allowances_exempt_sec_10", 0.0))
        if hra_exempt > 0:
            exempt_allowances = max(exempt_allowances, hra_exempt)
            
        prof_tax = float(form16.get("professional_tax_16_ii", 0.0))

        savings_interest = float(ais.get("savings_interest", 0.0))
        fd_interest = float(ais.get("fd_interest", 0.0))
        domestic_dividends = float(ais.get("domestic_dividends", 0.0))
        taxable_epf_interest = float(ais.get("taxable_epf_interest", 0.0))
        
        tax_refund_amount = float(ais.get("tax_refund_amount", 0.0))
        tax_refund_interest = float(ais.get("tax_refund_interest", 0.0))
        tax_due_demand = float(ais.get("tax_due_demand", 0.0))
        
        total_us_dividends_inr = sum(item["amount_inr"] for item in us_dividends)
        total_us_withholding_inr = sum(item["withholding_inr"] for item in us_dividends)

        total_us_interest_inr = sum(item["amount_inr"] for item in us_interest)
        total_us_interest_withholding_inr = sum(item["withholding_inr"] for item in us_interest)

        other_sources_income = (
            savings_interest + 
            fd_interest + 
            domestic_dividends + 
            total_us_dividends_inr + 
            total_us_interest_inr + 
            taxable_epf_interest + 
            tax_refund_interest
        )

        bf_stcl = float(inputs.get("bf_stcl", 0.0) or 0.0)
        bf_ltcl = float(inputs.get("bf_ltcl", 0.0) or 0.0)
        cg_results = self.calculate_capital_gains(stock_sales, bf_stcl=bf_stcl, bf_ltcl=bf_ltcl)
        net_cg = cg_results["net_gains"]

        cg_exemptions = inputs.get("cg_exemptions", [])
        applied_exemptions = []
        exemptions_by_category = {
            "LTCG_Listed": 0.0,
            "LTCG_Unlisted": 0.0,
            "Other": 0.0
        }
        
        for ex in cg_exemptions:
            sec = ex.get("section", "54F")
            applied_to = ex.get("applied_to", "LTCG_Listed")
            reinvestment = float(ex.get("reinvestment_amount") or 0.0)
            net_cons = float(ex.get("net_consideration") or 0.0)
            
            if applied_to == "LTCG_Listed":
                eligible_gain = net_cg["ltcg_listed"] - exemptions_by_category["LTCG_Listed"]
            elif applied_to == "LTCG_Unlisted":
                eligible_gain = net_cg["ltcg_unlisted"] - exemptions_by_category["LTCG_Unlisted"]
            else:
                eligible_gain = 999999999999.0
            
            eligible_gain = max(0.0, eligible_gain)
            ex_amount = 0.0
            
            if reinvestment > 0:
                if sec == "54":
                    reinv_cap = min(reinvestment, 100000000.0)
                    ex_amount = min(eligible_gain, reinv_cap)
                elif sec == "54B":
                    ex_amount = min(eligible_gain, reinvestment)
                elif sec == "54EC":
                    reinv_cap = min(reinvestment, 5000000.0)
                    ex_amount = min(eligible_gain, reinv_cap)
                elif sec == "54F":
                    reinv_cap = min(reinvestment, 100000000.0)
                    if net_cons > 0:
                        if reinv_cap >= net_cons:
                            ex_amount = eligible_gain
                        else:
                            ex_amount = eligible_gain * (reinv_cap / net_cons)
                    else:
                        ex_amount = 0.0
            
            ex_amount = min(eligible_gain, ex_amount)
            ex_amount = round(ex_amount, 2)
            
            if applied_to in exemptions_by_category:
                exemptions_by_category[applied_to] += ex_amount
                
            applied_exemptions.append({
                "section": sec,
                "applied_to": applied_to,
                "reinvestment_amount": reinvestment,
                "net_consideration": net_cons,
                "computed_exemption": ex_amount
            })

        net_cg["ltcg_listed"] = max(0.0, net_cg["ltcg_listed"] - exemptions_by_category["LTCG_Listed"])
        net_cg["ltcg_unlisted"] = max(0.0, net_cg["ltcg_unlisted"] - exemptions_by_category["LTCG_Unlisted"])
        
        cg_results["exemptions"] = applied_exemptions
        cg_results["exemptions_by_category"] = exemptions_by_category

        special_cg_income = net_cg["stcg_listed"] + net_cg["ltcg_listed"] + net_cg["ltcg_unlisted"]
        slab_cg_income = net_cg["stcg_unlisted"]

        std_ded_new = 75000.0 if self.fy == "2025-26" else 50000.0
        std_ded_old = 50000.0

        results = {}
        for regime in ["new", "old"]:
            is_new = regime == "new"
            
            sal_std_ded = std_ded_new if is_new else std_ded_old
            sal_exempt = exempt_allowances if not is_new else 0.0
            sal_prof_tax = prof_tax if not is_new else 0.0
            
            net_salary = max(0.0, gross_salary - sal_exempt - sal_std_ded - sal_prof_tax)
            
            hp_calculator = HousePropertyCalculator()
            hp_res = hp_calculator.calculate_house_property_income(house_properties, is_new)
            house_property_income = hp_res["allowed_setoff"]

            net_slab_income = net_salary + other_sources_income + slab_cg_income + house_property_income

            ded_80c = 0.0
            ded_80d = 0.0
            ded_80ccd_1b = 0.0
            ded_80tta = 0.0
            ded_80ttb = 0.0
            total_deductions = 0.0

            if not is_new:
                ded_80c, ded_80d, ded_80ccd_1b, ded_80tta, ded_80ttb, total_deductions = self.calculate_deductions(
                    inputs, form16, is_senior, savings_interest, fd_interest
                )
            
            taxable_slab_income = max(0.0, net_slab_income - total_deductions)

            slab_tax, slab_breakdown = self.calculate_slab_tax(taxable_slab_income, is_new)

            txs_111a = [t for t in cg_results["transactions"] if t["section"] == "Sec 111A"]
            rate_111a = txs_111a[0]["rate"] / 100.0 if txs_111a else (0.20 if self.fy == "2025-26" else 0.15)
            stcg_listed_tax = net_cg["stcg_listed"] * rate_111a

            exemption_limit = 125000.0 if self.fy == "2025-26" else 100000.0
            taxable_ltcg_112a = max(0.0, net_cg["ltcg_listed"] - exemption_limit)
            txs_112a = [t for t in cg_results["transactions"] if t["section"] == "Sec 112A"]
            rate_112a = txs_112a[0]["rate"] / 100.0 if txs_112a else (0.125 if self.fy == "2025-26" else 0.10)
            ltcg_listed_tax = taxable_ltcg_112a * rate_112a

            txs_112 = [t for t in cg_results["transactions"] if t["section"] == "Sec 112"]
            rate_112 = txs_112[0]["rate"] / 100.0 if txs_112 else 0.125
            ltcg_unlisted_tax = net_cg["ltcg_unlisted"] * rate_112

            total_cg_tax = stcg_listed_tax + ltcg_listed_tax + ltcg_unlisted_tax
            vda_tax = total_vda_gains * 0.30
            
            basic_tax = slab_tax + total_cg_tax + vda_tax
            
            rates_info = {
                "rate_111a": rate_111a,
                "rate_112a": rate_112a,
                "rate_112": rate_112
            }
            
            surcharge = self.calculate_surcharge_with_relief(
                is_new, taxable_slab_income, special_cg_income,
                domestic_dividends + total_us_dividends_inr,
                basic_tax, slab_tax, total_cg_tax, total_vda_gains,
                net_cg["stcg_listed"], net_cg["ltcg_listed"], net_cg["ltcg_unlisted"],
                rates_info
            )
            
            cess = (basic_tax + surcharge) * 0.04
            total_tax_before_relief = basic_tax + surcharge + cess

            total_taxable_income = taxable_slab_income + special_cg_income + total_vda_gains
            avg_tax_rate = (total_tax_before_relief / total_taxable_income) if total_taxable_income > 0 else 0.0
            
            combined_us_income = total_us_dividends_inr + total_us_interest_inr
            combined_us_withholding = total_us_withholding_inr + total_us_interest_withholding_inr
            us_tax_in_india = combined_us_income * avg_tax_rate
            ftc_relief = min(combined_us_withholding, us_tax_in_india)

            net_tax_payable = max(0.0, total_tax_before_relief - ftc_relief)
            
            tds_employer = float(form16.get("tds_deducted", 0.0))
            tds_epfo = float(ais.get("taxable_epf_interest_tds", 0.0))
            tds_deposits = float(ais.get("tds_on_deposit_interest", 0.0))
            total_tds = tds_employer + tds_epfo + tds_deposits
            
            interest_234b, interest_234c = self.calculate_234_interest(
                net_tax_payable, total_tds, advance_tax_paid,
                basic_tax, slab_tax, total_cg_tax, special_cg_income,
                domestic_dividends + total_us_dividends_inr, taxable_slab_income, vda_tax,
                ais.get("advance_tax_details", []),
                stock_sales=stock_sales,
                us_dividends=us_dividends,
                is_new_regime=is_new,
                inputs=inputs
            )
            
            total_tax_surcharge_interest = net_tax_payable + interest_234b + interest_234c
            net_payable_refundable = total_tax_surcharge_interest - total_tds - advance_tax_paid + tax_due_demand
            
            est_refund_amount = 0.0
            est_refund_interest = 0.0
            est_due_demand_val = 0.0
            if net_payable_refundable < 0:
                est_refund_amount = abs(net_payable_refundable)
                est_refund_interest = round(est_refund_amount * 0.005 * 4, 2)
            else:
                est_due_demand_val = net_payable_refundable

            results[regime] = {
                "gross_salary": gross_salary,
                "net_salary": net_salary,
                "other_sources_income": other_sources_income,
                "house_property_income": house_property_income,
                "house_property": hp_res,
                "exempt_allowances": exempt_allowances if not is_new else 0.0,
                "deductions": {
                    "80C": ded_80c,
                    "80D": ded_80d,
                    "80CCD_1B": ded_80ccd_1b,
                    "80TTA": ded_80tta,
                    "80TTB": ded_80ttb,
                    "total": total_deductions
                },
                "taxable_slab_income": taxable_slab_income,
                "special_cg_income": special_cg_income,
                "total_taxable_income": total_taxable_income,
                "slab_tax": slab_tax,
                "slab_breakdown": slab_breakdown,
                "hra_exempt": hra_exempt if not is_new else 0.0,
                "cg_tax": {
                    "stcg_listed": stcg_listed_tax,
                    "ltcg_listed": ltcg_listed_tax,
                    "ltcg_unlisted": ltcg_unlisted_tax,
                    "total": total_cg_tax
                },
                "vda_income": total_vda_gains,
                "vda_tax": vda_tax,
                "basic_tax": basic_tax,
                "surcharge": surcharge,
                "cess": cess,
                "total_tax_before_relief": total_tax_before_relief,
                "avg_tax_rate_pct": avg_tax_rate * 100.0,
                "ftc_relief": ftc_relief,
                "net_tax_payable": net_tax_payable,
                "interest_234b": interest_234b,
                "interest_234c": interest_234c,
                "total_tax_surcharge_interest": total_tax_surcharge_interest,
                "tds_credited": total_tds,
                "advance_tax_paid": advance_tax_paid,
                "tax_refund_amount": tax_refund_amount,
                "tax_refund_interest": tax_refund_interest,
                "tax_due_demand": tax_due_demand,
                "est_refund_amount": est_refund_amount,
                "est_refund_interest": est_refund_interest,
                "est_due_demand": est_due_demand_val,
                "final_due_or_refund": net_payable_refundable
            }

        optimal_regime = "new" if results["new"]["net_tax_payable"] <= results["old"]["net_tax_payable"] else "old"
        
        # Build Schedule FA rows
        schedule_fa = self._generate_schedule_fa(stock_sales, us_dividends)
        
        return {
            "regimes": results,
            "optimal_regime": optimal_regime,
            "capital_gains": cg_results,
            "schedule_fa": schedule_fa,
            "form67_details": {
                "foreign_income_inr": total_us_dividends_inr + total_us_interest_inr,
                "foreign_dividend_inr": total_us_dividends_inr,
                "foreign_interest_inr": total_us_interest_inr,
                "tax_withheld_inr": total_us_withholding_inr + total_us_interest_withholding_inr,
                "ftc_claimed_inr": results[optimal_regime]["ftc_relief"],
                "country": "United States",
                "dtaa_article": "Article 10 (Dividends) & Article 11 (Interest)",
                "withholding_rate_pct": 25.0
            }
        }
