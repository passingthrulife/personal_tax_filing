import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

class TaxCalculator:
    def __init__(self, fy="2025-26"):
        self.fy = fy  # "2024-25" or "2025-26"

    def set_fy(self, fy):
        self.fy = fy

    def calculate_capital_gains(self, stock_transactions: list) -> dict:
        """
        Calculates capital gains and applies set-off rules.
        Separates into:
        - STCG Listed (Sec 111A)
        - LTCG Listed (Sec 112A)
        - STCG Unlisted (Slab rates)
        - LTCG Unlisted (Sec 112)
        """
        # Sells date-based splits or standard rules depending on FY
        # For FY 2024-25: Trades before July 23, 2024 have old rates (STCG 15%, LTCG 10%), on or after have new rates (STCG 20%, LTCG 12.5%).
        # For FY 2025-26: All trades have new rates (STCG 20%, LTCG 12.5%).
        
        # Initialize buckets
        stcg_listed_gains = 0.0
        stcg_listed_losses = 0.0
        
        ltcg_listed_gains = 0.0
        ltcg_listed_losses = 0.0
        
        stcg_unlisted_gains = 0.0
        stcg_unlisted_losses = 0.0
        
        ltcg_unlisted_gains = 0.0
        ltcg_unlisted_losses = 0.0

        # Detailed breakdown of transactions
        processed_txs = []

        for tx in stock_transactions:
            buy_date = tx["buy_date"]
            sell_date = tx["sell_date"]
            qty = tx["quantity"]
            buy_price_inr = tx["buy_price_inr"]
            sell_price_inr = tx["sell_price_inr"]
            is_us = tx["is_us"]
            
            holding_days = (sell_date - buy_date).days
            gain_inr = (sell_price_inr - buy_price_inr) * qty
            
            # Determine term
            if is_us:
                # Unlisted shares holding period for long term is 24 months (approx 730 days)
                is_long_term = holding_days > 730
            else:
                # Listed shares holding period for long term is 12 months (approx 365 days)
                is_long_term = holding_days > 365

            # Determine rate based on FY and sell date
            rate = 0.0
            section = ""
            
            if is_us:
                if is_long_term:
                    section = "Sec 112"
                    # For LTCG US:
                    if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                        rate = 20.0  # with indexation (simplified to 20% in summary)
                    else:
                        rate = 12.5  # without indexation
                else:
                    section = "Slab Rate"
                    rate = -1.0  # Taxed at slab rates
            else:
                if is_long_term:
                    section = "Sec 112A"
                    if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                        rate = 10.0
                    else:
                        rate = 12.5
                else:
                    section = "Sec 111A"
                    if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                        rate = 15.0
                    else:
                        rate = 20.0

            tx_info = {
                "symbol": tx["symbol"],
                "quantity": qty,
                "buy_date": buy_date.strftime("%Y-%m-%d"),
                "sell_date": sell_date.strftime("%Y-%m-%d"),
                "holding_days": holding_days,
                "buy_val_inr": buy_price_inr * qty,
                "sell_val_inr": sell_price_inr * qty,
                "gain_inr": gain_inr,
                "type": "LTCG" if is_long_term else "STCG",
                "is_us": is_us,
                "section": section,
                "rate": rate if rate != -1.0 else "Slab"
            }
            processed_txs.append(tx_info)

            # Sort into buckets
            if is_us:
                if is_long_term:
                    if gain_inr >= 0:
                        ltcg_unlisted_gains += gain_inr
                    else:
                        ltcg_unlisted_losses += abs(gain_inr)
                else:
                    if gain_inr >= 0:
                        stcg_unlisted_gains += gain_inr
                    else:
                        stcg_unlisted_losses += abs(gain_inr)
            else:
                if is_long_term:
                    if gain_inr >= 0:
                        ltcg_listed_gains += gain_inr
                    else:
                        ltcg_listed_losses += abs(gain_inr)
                else:
                    if gain_inr >= 0:
                        stcg_listed_gains += gain_inr
                    else:
                        stcg_listed_losses += abs(gain_inr)

        # Set-off logic implementation
        # Step 1: Set off LTCG losses against LTCG gains
        total_ltcg_gains = ltcg_listed_gains + ltcg_unlisted_gains
        total_ltcg_losses = ltcg_listed_losses + ltcg_unlisted_losses
        
        net_ltcg_unlisted = ltcg_unlisted_gains
        net_ltcg_listed = ltcg_listed_gains
        
        if total_ltcg_losses > 0:
            # Deduct from unlisted first, then listed
            remaining_ltc_loss = total_ltcg_losses
            
            if net_ltcg_unlisted >= remaining_ltc_loss:
                net_ltcg_unlisted -= remaining_ltc_loss
                remaining_ltc_loss = 0.0
            else:
                remaining_ltc_loss -= net_ltcg_unlisted
                net_ltcg_unlisted = 0.0
                
            if remaining_ltc_loss > 0:
                if net_ltcg_listed >= remaining_ltc_loss:
                    net_ltcg_listed -= remaining_ltc_loss
                    remaining_ltc_loss = 0.0
                else:
                    remaining_ltc_loss -= net_ltcg_listed
                    net_ltcg_listed = 0.0
            cf_ltcg_loss = remaining_ltc_loss
        else:
            cf_ltcg_loss = 0.0

        # Step 2: Set off STCG losses against STCG gains, then LTCG gains
        total_stcg_gains = stcg_listed_gains + stcg_unlisted_gains
        total_stcg_losses = stcg_listed_losses + stcg_unlisted_losses
        
        net_stcg_unlisted = stcg_unlisted_gains
        net_stcg_listed = stcg_listed_gains
        
        if total_stcg_losses > 0:
            remaining_stc_loss = total_stcg_losses
            
            # 1. Deduct from unlisted STCG
            if net_stcg_unlisted >= remaining_stc_loss:
                net_stcg_unlisted -= remaining_stc_loss
                remaining_stc_loss = 0.0
            else:
                remaining_stc_loss -= net_stcg_unlisted
                net_stcg_unlisted = 0.0
                
            # 2. Deduct from listed STCG
            if remaining_stc_loss > 0:
                if net_stcg_listed >= remaining_stc_loss:
                    net_stcg_listed -= remaining_stc_loss
                    remaining_stc_loss = 0.0
                else:
                    remaining_stc_loss -= net_stcg_listed
                    net_stcg_listed = 0.0
                    
            # 3. Deduct from unlisted LTCG
            if remaining_stc_loss > 0:
                if net_ltcg_unlisted >= remaining_stc_loss:
                    net_ltcg_unlisted -= remaining_stc_loss
                    remaining_stc_loss = 0.0
                else:
                    remaining_stc_loss -= net_ltcg_unlisted
                    net_ltcg_unlisted = 0.0
                    
            # 4. Deduct from listed LTCG
            if remaining_stc_loss > 0:
                if net_ltcg_listed >= remaining_stc_loss:
                    net_ltcg_listed -= remaining_stc_loss
                    remaining_stc_loss = 0.0
                else:
                    remaining_stc_loss -= net_ltcg_listed
                    net_ltcg_listed = 0.0
            cf_stcg_loss = remaining_stc_loss
        else:
            cf_stcg_loss = 0.0

        return {
            "transactions": processed_txs,
            "raw_gains": {
                "stcg_listed": stcg_listed_gains - stcg_listed_losses,
                "ltcg_listed": ltcg_listed_gains - ltcg_listed_losses,
                "stcg_unlisted": stcg_unlisted_gains - stcg_unlisted_losses,
                "ltcg_unlisted": ltcg_unlisted_gains - ltcg_unlisted_losses
            },
            "net_gains": {
                "stcg_listed": net_stcg_listed,
                "stcg_unlisted": net_stcg_unlisted,
                "ltcg_listed": net_ltcg_listed,
                "ltcg_unlisted": net_ltcg_unlisted,
                "cf_stcg_loss": cf_stcg_loss,
                "cf_ltcg_loss": cf_ltcg_loss
            }
        }

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
            
        # For total income > 2 Crores, we split the tax and apply rates:
        # - Surcharge on tax of capital gains (Sec 111A, 112A, 112) and dividends is capped at 15%.
        # - Surcharge on other tax (slab tax on other income) is 25% or 37% depending on other income.
        cg_special_tax = cg_tax
        if taxable_slab_income > 0:
            slab_tax_on_div = slab_tax * (min(dividend_income, taxable_slab_income) / taxable_slab_income)
        else:
            slab_tax_on_div = 0.0
            
        tax_capped = cg_special_tax + slab_tax_on_div
        tax_other = max(0.0, basic_tax - tax_capped)
        
        surcharge_capped = tax_capped * 0.15
        
        # Surcharge rate on regular slab tax (other than dividends)
        other_income = total_income - (dividend_income + special_cg_income)
        if other_income <= 20000000.0:
            rate_other = 0.15
        elif other_income <= 50000000.0:
            rate_other = 0.25
        else:
            rate_other = 0.25 if is_new else 0.37
            
        surcharge_other = tax_other * rate_other
        return surcharge_capped + surcharge_other

    def calculate_234_interest(self, net_tax_payable: float, tds_credited: float, advance_tax_paid: float, basic_tax: float, slab_tax: float, cg_tax: float, special_cg_income: float, dividend_income: float, taxable_slab_income: float, vda_tax: float = 0.0, advance_tax_details: list = None, stock_sales: list = None, us_dividends: list = None, is_new_regime: bool = True, inputs: dict = None) -> tuple:
        assessed_tax = max(0.0, net_tax_payable - tds_credited)
        if assessed_tax < 10000.0:
            return 0.0, 0.0
            
        # 1. Section 234B Interest
        interest_234b = 0.0
        if advance_tax_paid < (0.90 * assessed_tax):
            shortfall = assessed_tax - advance_tax_paid
            shortfall_rounded = (shortfall // 100) * 100
            interest_234b = shortfall_rounded * 0.04
            
        # Helper to extract date from record
        def get_item_date(item):
            d = item.get("date") or item.get("sell_date")
            if not d:
                return None
            if isinstance(d, date):
                return d
            if isinstance(d, datetime):
                return d.date()
            if isinstance(d, str):
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(d, fmt).date()
                    except ValueError:
                        continue
                try:
                    parts = d.split()[0].split("-")
                    if len(parts) == 3:
                        return date(int(parts[0]), int(parts[1]), int(parts[2]))
                except Exception:
                    pass
            return None

        # Determine year of FY
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
        
        # Resolve rates for special CG tax
        txs_111a = [t for t in (stock_sales or []) if t.get("section") == "Sec 111A"]
        rate_111a = txs_111a[0]["rate"] / 100.0 if txs_111a else (0.20 if self.fy == "2025-26" else 0.15)
        
        txs_112a = [t for t in (stock_sales or []) if t.get("section") == "Sec 112A"]
        rate_112a = txs_112a[0]["rate"] / 100.0 if txs_112a else (0.125 if self.fy == "2025-26" else 0.10)
        
        txs_112 = [t for t in (stock_sales or []) if t.get("section") == "Sec 112"]
        rate_112 = txs_112[0]["rate"] / 100.0 if txs_112 else 0.125

        exemption_limit = 125000.0 if self.fy == "2025-26" else 100000.0

        # Helper to calculate cumulative tax up to a given date
        def calculate_tax_up_to(end_date):
            # 1. Filter transactions
            filtered_sales = [tx for tx in (stock_sales or []) if get_item_date(tx) and get_item_date(tx) <= end_date]
            filtered_divs = [div for div in (us_dividends or []) if get_item_date(div) and get_item_date(div) <= end_date]
            filtered_vdas = [v for v in (inputs.get("vda_trades", []) if inputs else []) if get_item_date(v) and get_item_date(v) <= end_date]
            
            # 2. Capital gains for period
            cg_results_D = self.calculate_capital_gains(filtered_sales)
            net_cg_D = cg_results_D["net_gains"]
            stcg_unlisted_D = net_cg_D["stcg_unlisted"]
            special_cg_income_D = net_cg_D["stcg_listed"] + net_cg_D["ltcg_listed"] + net_cg_D["ltcg_unlisted"]
            
            # 3. US Dividends for period
            us_divs_D = sum(item["amount_inr"] for item in filtered_divs)
            
            # 4. VDA for period
            vda_income_D = sum(max(0.0, float(t.get("proceeds_inr", 0.0)) - float(t.get("cost_inr", 0.0))) for t in filtered_vdas)
            vda_tax_D = vda_income_D * 0.30
            
            # 5. Total slab income for period (excluding domestic dividends unless it's March 15)
            dom_divs_D = dividend_income if end_date >= march_15 else 0.0
            slab_income_D = regular_slab_income + stcg_unlisted_D + us_divs_D + dom_divs_D
            
            # 6. Basic tax
            slab_tax_D, _ = self.calculate_slab_tax(slab_income_D, is_new_regime)
            
            stcg_listed_tax_D = net_cg_D["stcg_listed"] * rate_111a
            ltcg_listed_tax_D = max(0.0, net_cg_D["ltcg_listed"] - exemption_limit) * rate_112a
            ltcg_unlisted_tax_D = net_cg_D["ltcg_unlisted"] * rate_112
            special_cg_tax_D = stcg_listed_tax_D + ltcg_listed_tax_D + ltcg_unlisted_tax_D
            
            basic_tax_D = slab_tax_D + special_cg_tax_D + vda_tax_D
            
            # 7. Surcharge
            surcharge_D = self.calculate_surcharge(
                is_new_regime, slab_income_D, special_cg_income_D,
                us_divs_D + dom_divs_D, basic_tax_D, slab_tax_D, special_cg_tax_D, vda_income_D
            )
            
            # 8. Cess
            cess_D = (basic_tax_D + surcharge_D) * 0.04
            total_tax_before_relief_D = basic_tax_D + surcharge_D + cess_D
            
            # 9. FTC relief
            total_taxable_income_D = slab_income_D + special_cg_income_D + vda_income_D
            avg_tax_rate_D = (total_tax_before_relief_D / total_taxable_income_D) if total_taxable_income_D > 0 else 0.0
            
            us_withholding_D = sum(item["withholding_inr"] for item in filtered_divs)
            ftc_relief_D = min(us_withholding_D, us_divs_D * avg_tax_rate_D)
            
            # 10. Net Payable
            net_payable_D = max(0.0, total_tax_before_relief_D - ftc_relief_D)
            
            # 11. Assessed Tax
            assessed_tax_D = max(0.0, net_payable_D - tds_credited)
            return assessed_tax_D

        # Compute period assessed taxes u/s the proviso
        if stock_sales or us_dividends:
            assessed_tax_june = calculate_tax_up_to(june_15)
            assessed_tax_sept = calculate_tax_up_to(sept_15)
            assessed_tax_dec = calculate_tax_up_to(dec_15)
            assessed_tax_march = calculate_tax_up_to(march_15)
        else:
            # Fallback
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
        
        # Dec 15: 75%
        shortfall_dec = max(0.0, 0.75 * assessed_tax_dec - tax_dec)
        interest_dec = ((shortfall_dec // 100) * 100) * 0.03
        
        # March 15: 100%
        # Must use the final computed assessed_tax for March 15
        shortfall_march = max(0.0, assessed_tax - tax_march)
        interest_march = ((shortfall_march // 100) * 100) * 0.01
        
        interest_234c = interest_june + interest_sept + interest_dec + interest_march
        return interest_234b, interest_234c

    def compute_tax_liability(self, inputs: dict) -> dict:
        """
        Assembles all income sources, deductions, and computes tax
        under both Old and New regimes.
        """
        # Parse inputs
        form16 = inputs.get("form16", {})
        ais = inputs.get("ais", {})
        stock_sales = inputs.get("stock_sales", [])
        us_dividends = inputs.get("us_dividends", [])
        us_interest = inputs.get("us_interest", [])
        dob_str = inputs.get("dob", "").strip()
        vda_trades = inputs.get("vda_trades", [])
        
        total_vda_gains = 0.0
        for t in vda_trades:
            cost = float(t.get("cost_inr", 0.0))
            proceeds = float(t.get("proceeds_inr", 0.0))
            gain = max(0.0, proceeds - cost)
            t["gain_inr"] = gain
            total_vda_gains += gain
        
        # Determine senior status based on age at end of FY
        is_senior = False
        if dob_str and len(dob_str) == 8:
            try:
                dob_day = int(dob_str[:2])
                dob_month = int(dob_str[2:4])
                dob_year = int(dob_str[4:])
                fy_start_year = int(self.fy.split("-")[0])
                fy_end_date = date(fy_start_year + 1, 3, 31)
                
                # Calculate age on March 31 of FY end
                age = fy_end_date.year - dob_year - ((fy_end_date.month, fy_end_date.day) < (dob_month, dob_day))
                if age >= 60:
                    is_senior = True
            except Exception as e:
                logger.warning(f"Failed to calculate age from DOB '{dob_str}': {e}")
        
        # Explicit inputs
        home_loan_interest = float(inputs.get("home_loan_interest", form16.get("home_loan_interest_24b", 0.0)))
        home_loan_principal = float(inputs.get("home_loan_principal", 0.0))
        custom_80c = float(inputs.get("custom_80c", 0.0))
        custom_80d = float(inputs.get("custom_80d", 0.0))
        advance_tax_paid = float(inputs.get("advance_tax_paid", ais.get("advance_tax_paid", 0.0)))

        # HRA Calculator Inputs
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

        # 1. Salary components
        gross_salary = (
            float(form16.get("gross_salary_17_1", 0.0)) +
            float(form16.get("perquisites_17_2", 0.0)) +
            float(form16.get("profits_lieu_17_3", 0.0))
        )
        exempt_allowances = float(form16.get("allowances_exempt_sec_10", 0.0))
        if hra_exempt > 0:
            exempt_allowances = max(exempt_allowances, hra_exempt)
            
        prof_tax = float(form16.get("professional_tax_16_ii", 0.0))

        # 2. Other Sources
        savings_interest = float(ais.get("savings_interest", 0.0))
        fd_interest = float(ais.get("fd_interest", 0.0))
        domestic_dividends = float(ais.get("domestic_dividends", 0.0))
        taxable_epf_interest = float(ais.get("taxable_epf_interest", 0.0))
        
        tax_refund_amount = float(ais.get("tax_refund_amount", 0.0))
        tax_refund_interest = float(ais.get("tax_refund_interest", 0.0))
        tax_due_demand = float(ais.get("tax_due_demand", 0.0))
        
        # US Dividends Sum
        total_us_dividends_inr = sum(item["amount_inr"] for item in us_dividends)
        total_us_withholding_inr = sum(item["withholding_inr"] for item in us_dividends)

        # US Interest Sum
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

        # 3. Capital Gains calculation
        cg_results = self.calculate_capital_gains(stock_sales)
        net_cg = cg_results["net_gains"]

        # Parse and apply Capital Gains Exemptions (Sec 54 / 54B / 54EC / 54F)
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
            
            # Determine currently available gain in this category to offset
            if applied_to == "LTCG_Listed":
                eligible_gain = net_cg["ltcg_listed"] - exemptions_by_category["LTCG_Listed"]
            elif applied_to == "LTCG_Unlisted":
                eligible_gain = net_cg["ltcg_unlisted"] - exemptions_by_category["LTCG_Unlisted"]
            else:
                eligible_gain = 999999999999.0  # other general assets
            
            eligible_gain = max(0.0, eligible_gain)
            ex_amount = 0.0
            
            if reinvestment > 0:
                if sec == "54":
                    # Sec 54 cap is 10 Crores
                    reinv_cap = min(reinvestment, 100000000.0)
                    ex_amount = min(eligible_gain, reinv_cap)
                elif sec == "54B":
                    ex_amount = min(eligible_gain, reinvestment)
                elif sec == "54EC":
                    # Sec 54EC cap is 50 Lakhs
                    reinv_cap = min(reinvestment, 5000000.0)
                    ex_amount = min(eligible_gain, reinv_cap)
                elif sec == "54F":
                    # Sec 54F cap on reinvestment base is 10 Crores
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

        # Apply computed deductions to net capital gains
        net_cg["ltcg_listed"] = max(0.0, net_cg["ltcg_listed"] - exemptions_by_category["LTCG_Listed"])
        net_cg["ltcg_unlisted"] = max(0.0, net_cg["ltcg_unlisted"] - exemptions_by_category["LTCG_Unlisted"])
        
        # Save exemptions inside cg_results to bubble up to frontend
        cg_results["exemptions"] = applied_exemptions
        cg_results["exemptions_by_category"] = exemptions_by_category

        # Special tax heads (STCG 111A and LTCG 112A/112 are taxed at special rates, not slabs)
        special_cg_income = net_cg["stcg_listed"] + net_cg["ltcg_listed"] + net_cg["ltcg_unlisted"]
        # STCG unlisted is taxed at slab rates, so it goes to slab income
        slab_cg_income = net_cg["stcg_unlisted"]

        # Slabs limits
        std_ded_new = 75000.0 if self.fy == "2025-26" else 50000.0
        std_ded_old = 50000.0

        # REGIME COMPUTATIONS
        results = {}
        for regime in ["new", "old"]:
            is_new = regime == "new"
            
            # --- Salary Income ---
            sal_std_ded = std_ded_new if is_new else std_ded_old
            sal_exempt = exempt_allowances if not is_new else 0.0
            sal_prof_tax = prof_tax if not is_new else 0.0
            
            net_salary = max(0.0, gross_salary - sal_exempt - sal_std_ded - sal_prof_tax)
            
            # --- House Property ---
            house_property_income = -home_loan_interest if not is_new else 0.0
            # Under old regime, loss up to 2L is capped
            house_property_income = max(-200000.0, house_property_income)

            # --- Slabs Income (Salary + Other Sources + STCG Unlisted + House Property) ---
            net_slab_income = net_salary + other_sources_income + slab_cg_income + house_property_income

            # --- Deductions (Chapter VIA) ---
            ded_80c = 0.0
            ded_80d = 0.0
            ded_80tta = 0.0
            ded_80ttb = 0.0
            total_deductions = 0.0

            if not is_new:
                # 80C calculation (Form 16 80C + home loan principal + custom 80c)
                total_80c_investment = float(form16.get("deduction_80c", 0.0)) + home_loan_principal + custom_80c
                ded_80c = min(150000.0, total_80c_investment)
                
                # 80D
                ded_80d = min(25000.0, float(form16.get("deduction_80d", 0.0)) + custom_80d)
                
                # 80TTA / 80TTB
                if is_senior:
                    # 80TTB: Capped at 50,000 on savings bank + FD interest combined
                    ded_80ttb = min(50000.0, savings_interest + fd_interest)
                else:
                    # 80TTA: Capped at 10,000 on savings interest only
                    ded_80tta = min(10000.0, savings_interest)
                
                total_deductions = ded_80c + ded_80d + ded_80tta + ded_80ttb
            
            # Taxable Slab Income
            taxable_slab_income = max(0.0, net_slab_income - total_deductions)

            # Calculate basic tax on slab income
            slab_tax, slab_breakdown = self.calculate_slab_tax(taxable_slab_income, is_new)

            # --- Calculate tax on Special Capital Gains ---
            # 1. STCG 111A
            stcg_listed_rate = 0.20 if (self.fy == "2025-26") else 0.15 # Note: simplifying for FY 24-25 to 15% or 20% based on date, but here using flat for summary or blending
            # Let's compute actual rates based on processed transactions
            stcg_listed_tax = 0.0
            for tx in cg_results["transactions"]:
                if tx["section"] == "Sec 111A" and tx["gain_inr"] > 0:
                    # Apply transaction level rate since we processed dates
                    # Wait, if there are losses, we apply the rate to the net proportional gain
                    pass
            # Simplifying: since we have net_cg, let's look at the average rate used in transaction list
            txs_111a = [t for t in cg_results["transactions"] if t["section"] == "Sec 111A"]
            rate_111a = txs_111a[0]["rate"] / 100.0 if txs_111a else (0.20 if self.fy == "2025-26" else 0.15)
            stcg_listed_tax = net_cg["stcg_listed"] * rate_111a

            # 2. LTCG 112A (Indian listed) - first 1.25L (or 1L) is exempt
            exemption_limit = 125000.0 if self.fy == "2025-26" else 100000.0
            # LTCG 112A tax is on gains exceeding exemption
            taxable_ltcg_112a = max(0.0, net_cg["ltcg_listed"] - exemption_limit)
            txs_112a = [t for t in cg_results["transactions"] if t["section"] == "Sec 112A"]
            rate_112a = txs_112a[0]["rate"] / 100.0 if txs_112a else (0.125 if self.fy == "2025-26" else 0.10)
            ltcg_listed_tax = taxable_ltcg_112a * rate_112a

            # 3. LTCG 112 (US/unlisted)
            txs_112 = [t for t in cg_results["transactions"] if t["section"] == "Sec 112"]
            rate_112 = txs_112[0]["rate"] / 100.0 if txs_112 else 0.125
            ltcg_unlisted_tax = net_cg["ltcg_unlisted"] * rate_112

            total_cg_tax = stcg_listed_tax + ltcg_listed_tax + ltcg_unlisted_tax
            vda_tax = total_vda_gains * 0.30
            
            # Total basic tax (slab tax + capital gains tax + VDA tax)
            basic_tax = slab_tax + total_cg_tax + vda_tax
            
            # Calculate Surcharge
            surcharge = self.calculate_surcharge(
                is_new, taxable_slab_income, special_cg_income,
                domestic_dividends + total_us_dividends_inr,
                basic_tax, slab_tax, total_cg_tax, total_vda_gains
            )
            
            # Health & Education Cess (4%) on (basic tax + surcharge)
            cess = (basic_tax + surcharge) * 0.04
            total_tax_before_relief = basic_tax + surcharge + cess

            # --- Foreign Tax Credit (FTC) Relief u/s 90 ---
            # Calculated based on average tax rate in India
            total_taxable_income = taxable_slab_income + special_cg_income + total_vda_gains
            avg_tax_rate = (total_tax_before_relief / total_taxable_income) if total_taxable_income > 0 else 0.0
            
            # Relief u/s 90 on combined US Dividend & Interest Income
            combined_us_income = total_us_dividends_inr + total_us_interest_inr
            combined_us_withholding = total_us_withholding_inr + total_us_interest_withholding_inr
            us_tax_in_india = combined_us_income * avg_tax_rate
            ftc_relief = min(combined_us_withholding, us_tax_in_india)

            # Net Tax Payable (before interest u/s 234)
            net_tax_payable = max(0.0, total_tax_before_relief - ftc_relief)
            
            # TDS and Advance Tax credits
            tds_employer = float(form16.get("tds_deducted", 0.0))
            tds_epfo = float(ais.get("taxable_epf_interest_tds", 0.0))
            total_tds = tds_employer + tds_epfo
            
            # Calculate Section 234B and 234C interest
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
            
            results[regime] = {
                "gross_salary": gross_salary,
                "net_salary": net_salary,
                "other_sources_income": other_sources_income,
                "house_property_income": house_property_income,
                "exempt_allowances": exempt_allowances if not is_new else 0.0,
                "deductions": {
                    "80C": ded_80c,
                    "80D": ded_80d,
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
                "final_due_or_refund": net_payable_refundable
            }

        # Compare and select optimal
        optimal_regime = "new" if results["new"]["net_tax_payable"] <= results["old"]["net_tax_payable"] else "old"

        # Generate Schedule FA details (Calendar Year 2025)
        # Filters stock purchases or holdings
        # Since we have transactions, we can aggregate holdings
        # Let's build a nice helper structure for Schedule FA
        # Check if Schedule FA is provided in inputs (user manual override)
        schedule_fa_data = inputs.get("schedule_fa")
        if schedule_fa_data is None:
            schedule_fa_data = self._generate_schedule_fa(stock_sales, us_dividends)

        return {
            "regimes": results,
            "optimal_regime": optimal_regime,
            "capital_gains": cg_results,
            "schedule_fa": schedule_fa_data,
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

    def _generate_schedule_fa(self, stock_transactions: list, us_dividends: list) -> list:
        """
        Generates structured data for Schedule FA (Foreign Assets) for US stocks/RSUs.
        Groups by symbol/broker.
        """
        # Group transactions by stock symbol
        holdings = {}
        for tx in stock_transactions:
            if not tx["is_us"]:
                continue
            symbol = tx["symbol"]
            if symbol not in holdings:
                holdings[symbol] = {
                    "symbol": symbol,
                    "peak_value_usd": 0.0,
                    "closing_value_usd": 0.0,
                    "total_purchases_usd": 0.0,
                    "total_sales_usd": 0.0,
                    "gross_dividend_usd": 0.0
                }
            
            # Summarize sells and buys
            qty = tx["quantity"]
            holdings[symbol]["total_purchases_usd"] += tx["buy_price"] * qty
            holdings[symbol]["total_sales_usd"] += tx["sell_price"] * qty

        # Aggregate dividends
        # Note: dividends file might not contain symbol, but if it does, we map it, else map to a general portfolio
        for div in us_dividends:
            # Add to a general placeholder symbol or divide if symbol is present
            sym = div.get("symbol", "US PORTFOLIO")
            if sym not in holdings:
                holdings[sym] = {
                    "symbol": sym,
                    "peak_value_usd": 0.0,
                    "closing_value_usd": 0.0,
                    "total_purchases_usd": 0.0,
                    "total_sales_usd": 0.0,
                    "gross_dividend_usd": 0.0
                }
            holdings[sym]["gross_dividend_usd"] += div["amount_usd"]

        # Format for display in Schedule FA table
        fa_rows = []
        for sym, data in holdings.items():
            # Estimate peak value as purchase cost + some buffer, or max proceeds
            peak = max(data["total_purchases_usd"], data["total_sales_usd"] if data["total_sales_usd"] > 0 else data["total_purchases_usd"])
            fa_rows.append({
                "asset_description": f"Equity shares of {sym}",
                "institution_name": "Charles Schwab / US Broker",
                "institution_address": "USA",
                "peak_value_usd": peak,
                "closing_value_usd": max(0.0, data["total_purchases_usd"] - data["total_sales_usd"]),
                "gross_interest_dividend_usd": data["gross_dividend_usd"],
                "proceeds_from_sale_usd": data["total_sales_usd"]
            })

        return fa_rows
