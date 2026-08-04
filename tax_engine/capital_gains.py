import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

class CapitalGainsCalculatorMixin:
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
            asset_type = tx.get("asset_type", "stock")

            if isinstance(buy_date, str):
                buy_date = datetime.strptime(buy_date[:10], "%Y-%m-%d").date()
            if isinstance(sell_date, str):
                sell_date = datetime.strptime(sell_date[:10], "%Y-%m-%d").date()

            # Apply Section 112A Grandfathering for equity_mf and Indian stocks
            if (asset_type in ["equity_mf", "stock"]) and not is_us:
                if buy_date <= date(2018, 1, 31):
                    fmv = tx.get("fmv_31_jan_2018", 0.0)
                    if fmv > 0:
                        buy_price_inr = max(buy_price_inr, min(fmv, sell_price_inr))

            holding_days = (sell_date - buy_date).days
            gain_inr = (sell_price_inr - buy_price_inr) * qty
            
            # Determine term & rate based on asset_type
            is_long_term = False
            rate = 0.0
            section = ""
            
            if is_us:
                is_long_term = holding_days > 730
                if is_long_term:
                    section = "Sec 112"
                    if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                        rate = 20.0
                    else:
                        rate = 12.5
                else:
                    section = "Slab Rate"
                    rate = -1.0
            else:
                if asset_type in ["equity_mf", "stock"]:
                    is_long_term = holding_days > 365
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
                            
                elif asset_type == "specified_mf":
                    if buy_date >= date(2023, 4, 1):
                        is_long_term = False
                        section = "Sec 50AA"
                        rate = -1.0
                    else:
                        is_long_term = holding_days > 1095
                        if is_long_term:
                            section = "Sec 112"
                            if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                                rate = 20.0
                            else:
                                rate = 12.5
                        else:
                            section = "Slab Rate"
                            rate = -1.0
                            
                elif asset_type == "other_mf":
                    threshold = 730 if sell_date >= date(2024, 7, 23) else 1095
                    is_long_term = holding_days > threshold
                    if is_long_term:
                        section = "Sec 112"
                        if self.fy == "2024-25" and sell_date < date(2024, 7, 23):
                            rate = 20.0
                        else:
                            rate = 12.5
                    else:
                        section = "Slab Rate"
                        rate = -1.0

            tx_info = {
                "symbol": tx["symbol"],
                "quantity": qty,
                "buy_date": buy_date.strftime("%Y-%m-%d"),
                "sell_date": sell_date.strftime("%Y-%m-%d"),
                "holding_days": holding_days,
                "buy_val_inr": buy_price_inr * qty,
                "sell_val_inr": sell_price_inr * qty,
                "transfer_expenses": tx.get("transfer_expenses", 0.0),
                "gain_inr": gain_inr,
                "type": "LTCG" if is_long_term else "STCG",
                "is_us": is_us,
                "asset_type": asset_type,
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
                if asset_type in ["equity_mf", "stock"]:
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
                else:
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

        # Set-off logic implementation
        total_ltcg_gains = ltcg_listed_gains + ltcg_unlisted_gains
        total_ltcg_losses = ltcg_listed_losses + ltcg_unlisted_losses
        
        net_ltcg_unlisted = ltcg_unlisted_gains
        net_ltcg_listed = ltcg_listed_gains
        
        if total_ltcg_losses > 0:
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

        total_stcg_gains = stcg_listed_gains + stcg_unlisted_gains
        total_stcg_losses = stcg_listed_losses + stcg_unlisted_losses
        
        net_stcg_unlisted = stcg_unlisted_gains
        net_stcg_listed = stcg_listed_gains
        
        if total_stcg_losses > 0:
            remaining_stc_loss = total_stcg_losses
            
            if net_stcg_unlisted >= remaining_stc_loss:
                net_stcg_unlisted -= remaining_stc_loss
                remaining_stc_loss = 0.0
            else:
                remaining_stc_loss -= net_stcg_unlisted
                net_stcg_unlisted = 0.0
                
            if remaining_stc_loss > 0:
                if net_stcg_listed >= remaining_stc_loss:
                    net_stcg_listed -= remaining_stc_loss
                    remaining_stc_loss = 0.0
                else:
                    remaining_stc_loss -= net_stcg_listed
                    net_stcg_listed = 0.0
                    
            if remaining_stc_loss > 0:
                if net_ltcg_unlisted >= remaining_stc_loss:
                    net_ltcg_unlisted -= remaining_stc_loss
                    remaining_stc_loss = 0.0
                else:
                    remaining_stc_loss -= net_ltcg_unlisted
                    net_ltcg_unlisted = 0.0
                    
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
