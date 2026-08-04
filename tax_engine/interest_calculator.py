import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

class InterestCalculatorMixin:
    def calculate_234_interest(self, net_tax_payable: float, tds_credited: float, advance_tax_paid: float, basic_tax: float, slab_tax: float, cg_tax: float, special_cg_income: float, dividend_income: float, taxable_slab_income: float, vda_tax: float = 0.0, advance_tax_details: list = None, stock_sales: list = None, us_dividends: list = None, is_new_regime: bool = True, inputs: dict = None) -> tuple:
        """
        Calculates interest under Section 234B and 234C for advance tax shortfalls.
        """
        assessed_tax = max(0.0, net_tax_payable - tds_credited)
        
        # Section 234B Interest (1% per month on shortfall if advance tax paid is < 90% of assessed tax)
        # Outstanding is from April of AY to assessment date (assumed to be 4 months for estimation)
        interest_234b = 0.0
        total_advance_paid = advance_tax_paid
        if total_advance_paid < (0.90 * assessed_tax):
            shortfall_234b = assessed_tax - total_advance_paid
            # round down to nearest 100
            shortfall_234b_rounded = (shortfall_234b // 100) * 100
            interest_234b = shortfall_234b_rounded * 0.01 * 4  # 4 months default

        # Section 234C Interest (Deals with quarterly installments)
        # Installment dates: June 15 (15%), Sept 15 (45%), Dec 15 (75%), March 15 (100%)
        def get_item_date(item):
            d = item.get("date") or item.get("sell_date")
            if not d:
                return None
            if isinstance(d, date):
                return d
            try:
                return datetime.strptime(d[:10], "%Y-%m-%d").date()
            except Exception:
                return None

        fy_start_year = int(self.fy.split("-")[0])
        june_15 = date(fy_start_year, 6, 15)
        sept_15 = date(fy_start_year, 9, 15)
        dec_15 = date(fy_start_year, 12, 15)
        march_15 = date(fy_start_year + 1, 3, 15)
        
        # Bucket advance tax payments
        tax_june = 0.0
        tax_sept = 0.0
        tax_dec = 0.0
        tax_march = 0.0
        
        if advance_tax_details:
            for pmt in advance_tax_details:
                amt = float(pmt.get("amount", 0.0) or 0.0)
                date_str = pmt.get("date", "")
                if date_str:
                    try:
                        pmt_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                    except Exception:
                        try:
                            pmt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        except Exception:
                            pmt_date = date(fy_start_year + 1, 3, 15)
                            
                    if pmt_date <= june_15:
                        tax_june += amt
                        tax_sept += amt
                        tax_dec += amt
                        tax_march += amt
                    elif pmt_date <= sept_15:
                        tax_sept += amt
                        tax_dec += amt
                        tax_march += amt
                    elif pmt_date <= dec_15:
                        tax_dec += amt
                        tax_march += amt
                    elif pmt_date <= march_15:
                        tax_march += amt
        else:
            tax_march = advance_tax_paid

        # Calculate annual unlisted STCG
        annual_cg = self.calculate_capital_gains(stock_sales or [])
        unlisted_stcg_annual = annual_cg["net_gains"]["stcg_unlisted"]
        
        # regular_slab_income = slab income excluding unlisted STCG & US dividends & VDA slab
        regular_slab_income = max(0.0, taxable_slab_income - unlisted_stcg_annual - dividend_income)
        
        # Calculate slab tax on regular income
        slab_tax_regular, _ = self.calculate_slab_tax(regular_slab_income, is_new_regime)
        surcharge_regular = self.calculate_surcharge(is_new_regime, regular_slab_income, 0.0, 0.0, slab_tax_regular, slab_tax_regular, 0.0)
        cess_regular = (slab_tax_regular + surcharge_regular) * 0.04
        tax_regular = slab_tax_regular + surcharge_regular + cess_regular
        assessed_tax_regular = max(0.0, tax_regular - tds_credited)
        
        # Resolve rates for special CG tax
        txs_111a = [t for t in (stock_sales or []) if t.get("section") == "Sec 111A"]
        rate_111a = txs_111a[0]["rate"] / 100.0 if txs_111a else (0.20 if self.fy == "2025-26" else 0.15)
        
        txs_112a = [t for t in (stock_sales or []) if t.get("section") == "Sec 112A"]
        rate_112a = txs_112a[0]["rate"] / 100.0 if txs_112a else (0.125 if self.fy == "2025-26" else 0.10)
        
        txs_112 = [t for t in (stock_sales or []) if t.get("section") == "Sec 112"]
        rate_112 = txs_112[0]["rate"] / 100.0 if txs_112 else 0.125

        exemption_limit = 125000.0 if self.fy == "2025-26" else 100000.0

        def calculate_tax_up_to(end_date):
            filtered_sales = [tx for tx in (stock_sales or []) if get_item_date(tx) and get_item_date(tx) <= end_date]
            filtered_divs = [div for div in (us_dividends or []) if get_item_date(div) and get_item_date(div) <= end_date]
            filtered_vdas = [v for v in (inputs.get("vda_trades", []) if inputs else []) if get_item_date(v) and get_item_date(v) <= end_date]
            
            cg_results_D = self.calculate_capital_gains(filtered_sales)
            net_cg_D = cg_results_D["net_gains"]
            stcg_unlisted_D = net_cg_D["stcg_unlisted"]
            special_cg_income_D = net_cg_D["stcg_listed"] + net_cg_D["ltcg_listed"] + net_cg_D["ltcg_unlisted"]
            
            us_divs_D = sum(item["amount_inr"] for item in filtered_divs)
            
            vda_income_D = sum(max(0.0, float(t.get("proceeds_inr", 0.0)) - float(t.get("cost_inr", 0.0))) for t in filtered_vdas)
            vda_tax_D = vda_income_D * 0.30
            
            dom_divs_D = dividend_income if end_date >= march_15 else 0.0
            slab_income_D = regular_slab_income + stcg_unlisted_D + us_divs_D + dom_divs_D
            
            slab_tax_D, _ = self.calculate_slab_tax(slab_income_D, is_new_regime)
            
            stcg_listed_tax_D = net_cg_D["stcg_listed"] * rate_111a
            ltcg_listed_tax_D = max(0.0, net_cg_D["ltcg_listed"] - exemption_limit) * rate_112a
            ltcg_unlisted_tax_D = net_cg_D["ltcg_unlisted"] * rate_112
            special_cg_tax_D = stcg_listed_tax_D + ltcg_listed_tax_D + ltcg_unlisted_tax_D
            
            basic_tax_D = slab_tax_D + special_cg_tax_D + vda_tax_D
            
            surcharge_D = self.calculate_surcharge(
                is_new_regime, slab_income_D, special_cg_income_D,
                us_divs_D + dom_divs_D, basic_tax_D, slab_tax_D, special_cg_tax_D, vda_income_D
            )
            
            cess_D = (basic_tax_D + surcharge_D) * 0.04
            total_tax_before_relief_D = basic_tax_D + surcharge_D + cess_D
            
            total_taxable_income_D = slab_income_D + special_cg_income_D + vda_income_D
            avg_tax_rate_D = (total_tax_before_relief_D / total_taxable_income_D) if total_taxable_income_D > 0 else 0.0
            
            us_withholding_D = sum(item["withholding_inr"] for item in filtered_divs)
            ftc_relief_D = min(us_withholding_D, us_divs_D * avg_tax_rate_D)
            
            net_payable_D = max(0.0, total_tax_before_relief_D - ftc_relief_D)
            assessed_tax_D = max(0.0, net_payable_D - tds_credited)
            return assessed_tax_D

        if stock_sales or us_dividends:
            assessed_tax_june = calculate_tax_up_to(june_15)
            assessed_tax_sept = calculate_tax_up_to(sept_15)
            assessed_tax_dec = calculate_tax_up_to(dec_15)
            assessed_tax_march = calculate_tax_up_to(march_15)
        else:
            assessed_tax_june = assessed_tax_regular
            assessed_tax_sept = assessed_tax_regular
            assessed_tax_dec = assessed_tax_regular
            assessed_tax_march = assessed_tax

        # June 15: 15% (Buffer 12%)
        if tax_june >= (0.12 * assessed_tax_june):
            shortfall_june = 0.0
        else:
            shortfall_june = max(0.0, 0.15 * assessed_tax_june - tax_june)
        interest_june = ((shortfall_june // 100) * 100) * 0.03
        
        # Sept 15: 45% (Buffer 36%)
        if tax_sept >= (0.36 * assessed_tax_sept):
            shortfall_sept = 0.0
        else:
            shortfall_sept = max(0.0, 0.45 * assessed_tax_sept - tax_sept)
        interest_sept = ((shortfall_sept // 100) * 100) * 0.03
        
        shortfall_dec = max(0.0, 0.75 * assessed_tax_dec - tax_dec)
        interest_dec = ((shortfall_dec // 100) * 100) * 0.03
        
        shortfall_march = max(0.0, assessed_tax - tax_march)
        interest_march = ((shortfall_march // 100) * 100) * 0.01
        
        interest_234c = interest_june + interest_sept + interest_dec + interest_march
        return interest_234b, interest_234c
