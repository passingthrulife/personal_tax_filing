import logging

logger = logging.getLogger(__name__)

class ForeignReliefCalculatorMixin:
    def _generate_schedule_fa(self, stock_transactions: list, us_dividends: list) -> list:
        """
        Generates structured data for Schedule FA (Foreign Assets) for US stocks/RSUs.
        Groups by symbol/broker.
        """
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
            
            qty = tx["quantity"]
            holdings[symbol]["total_purchases_usd"] += tx["buy_price"] * qty
            holdings[symbol]["total_sales_usd"] += tx["sell_price"] * qty

        for div in us_dividends:
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

        fa_rows = []
        for sym, data in holdings.items():
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
