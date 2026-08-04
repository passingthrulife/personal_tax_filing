import logging

logger = logging.getLogger(__name__)

class HousePropertyCalculator:
    def calculate_house_property_income(self, properties: list, is_new: bool) -> dict:
        """
        Calculates Net Income or Loss from House Property under Indian Tax laws.
        """
        detailed_properties = []
        sop_interest_total = 0.0
        lop_income_total = 0.0
        
        for idx, prop in enumerate(properties):
            prop_type = prop.get("property_type", "SOP").upper()
            gross_rent = float(prop.get("gross_rent") or 0.0)
            municipal_taxes = float(prop.get("municipal_taxes") or 0.0)
            interest = float(prop.get("home_loan_interest") or 0.0)
            
            if prop_type == "SOP":
                gav = 0.0
                taxes_paid = 0.0
                nav = 0.0
                std_deduction = 0.0
                
                sop_interest_total += interest
                net_income = 0.0
                
                detailed_properties.append({
                    "index": idx + 1,
                    "property_type": "Self-Occupied Property (SOP)",
                    "gross_annual_value": gav,
                    "municipal_taxes": taxes_paid,
                    "net_annual_value": nav,
                    "standard_deduction_24a": std_deduction,
                    "interest_24b": interest,
                    "net_income": net_income
                })
            else:
                gav = gross_rent
                taxes_paid = municipal_taxes
                nav = gav - taxes_paid
                std_deduction = round(0.3 * nav, 2) if nav > 0 else 0.0
                
                net_income = nav - std_deduction - interest
                lop_income_total += net_income
                
                detailed_properties.append({
                    "index": idx + 1,
                    "property_type": "Let-Out Property (LOP)" if prop_type == "LOP" else "Deemed Let-Out Property (DLOP)",
                    "gross_annual_value": gav,
                    "municipal_taxes": taxes_paid,
                    "net_annual_value": nav,
                    "standard_deduction_24a": std_deduction,
                    "interest_24b": interest,
                    "net_income": net_income
                })
                
        sop_interest_cap = 200000.0 if not is_new else 0.0
        allowed_sop_interest = min(sop_interest_cap, sop_interest_total)
        net_sop_income = -allowed_sop_interest
        
        for dp in detailed_properties:
            if dp["property_type"].startswith("Self-Occupied"):
                if sop_interest_total > allowed_sop_interest and sop_interest_total > 0:
                    fraction = allowed_sop_interest / sop_interest_total
                    dp["interest_24b"] = round(dp["interest_24b"] * fraction, 2)
                elif is_new:
                    dp["interest_24b"] = 0.0
                dp["net_income"] = -dp["interest_24b"]

        total_income_before_setoff = net_sop_income + lop_income_total
        
        if total_income_before_setoff >= 0:
            allowed_setoff = total_income_before_setoff
            carry_forward_loss = 0.0
        else:
            if not is_new:
                allowed_setoff = max(-200000.0, total_income_before_setoff)
                carry_forward_loss = total_income_before_setoff - allowed_setoff
            else:
                allowed_setoff = 0.0
                carry_forward_loss = total_income_before_setoff
                
        return {
            "properties": detailed_properties,
            "total_income_before_setoff": round(total_income_before_setoff, 2),
            "allowed_setoff": round(allowed_setoff, 2),
            "carry_forward_loss": round(carry_forward_loss, 2)
        }
