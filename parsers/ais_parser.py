import re
import json
import csv
import io
import logging

logger = logging.getLogger(__name__)

class AISParserMixin:
    def parse_ais_tis(self, pdf_bytes: bytes, password: str = None) -> dict:
        """Parses AIS/TIS PDF to extract FD/savings interest, domestic dividends, and taxable EPF interest."""
        decrypted_bytes = self.decrypt_pdf(pdf_bytes, password)
        raw_text = self.extract_text_from_pdf(decrypted_bytes)

        if self.anthropic_client:
            try:
                return self._parse_ais_tis_with_claude(raw_text)
            except Exception as e:
                logger.error(f"Claude AIS/TIS parsing failed, falling back to regex: {e}")

        return self._parse_ais_tis_with_regex(raw_text)

    def _parse_ais_tis_with_claude(self, text: str) -> dict:
        """Uses Claude to parse AIS/TIS text into clean JSON summaries."""
        prompt = f"""
Analyze the text of this AIS/TIS (Annual Information Statement / Taxpayer Information Summary) document. 
Extract the summary of incomes and tax payments. Sum up values if there are multiple entries.
Return ONLY a valid JSON object matching the following keys. Do not include markdown wraps (like ```json), commentary, or other characters.

Required Keys:
- "savings_interest": (float, total interest from savings accounts)
- "fd_interest": (float, total interest from fixed deposits / recurring deposits)
- "domestic_dividends": (float, total dividend income from Indian companies)
- "taxable_epf_interest": (float, taxable interest on EPF contributions exceeding 2.5L u/s 10(11)/10(12))
- "taxable_epf_interest_tds": (float, total TDS deducted on EPFO interest)
- "salary_gross_ais": (float, gross salary as reported in AIS, to verify against Form 16)
- "purchase_of_securities": (float, total purchase of mutual funds / shares)
- "sale_of_securities": (float, total sale of mutual funds / shares)
- "advance_tax_paid": (float, total advance tax paid, under Payment of Taxes or Advance Tax)
- "tax_refund_amount": (float, total income tax refund amount received from last year, under Part B4 / Demand & Refund)
- "tax_refund_interest": (float, estimate of interest on the refund u/s 244A, which is 0.5% per month or part of a month from April 1 of AY to payment date)
- "tax_due_demand": (float, outstanding tax demand / tax due from last year, under Part B4 / Demand & Refund)
- "tds_on_deposit_interest": (float, total TDS deducted on interest other than salary and EPFO under Section 194A)
- "tds_on_deposit_interest_details": (list of dicts, detailed breakdown of TDS deducted on deposits, e.g. [{"source": "ICICI Bank", "amount": 16758.0, "tds": 1676.0}])

AIS/TIS text:
{text}
"""
        response = self.anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        content = response.content[0].text.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        return json.loads(content)

    def _parse_ais_tis_with_regex(self, text: str) -> dict:
        """Regex-based fallback parser for AIS/TIS text."""
        savings_interest = 0.0
        savings_details = []
        fd_interest = 0.0
        fd_details = []
        domestic_dividends = 0.0
        dividend_details = []
        taxable_epf_interest = 0.0
        taxable_epf_interest_tds = 0.0
        taxable_epf_interest_details = []
        salary_gross_ais = 0.0
        purchase_of_securities = 0.0
        sale_of_securities = 0.0
        advance_tax_paid = 0.0
        tax_refund_amount = 0.0
        tax_refund_interest = 0.0
        tax_due_demand = 0.0
        tds_on_deposit_interest = 0.0
        tds_on_deposit_interest_details = []
        
        current_section = None
        current_deductor = "Unknown"
        is_epf_deductor = False
        
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Section detection
            if "TDS-192" in line or "Salary received" in line:
                current_section = "salary"
                # Extract salary amount if present on this line
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    salary_gross_ais += float(match.group(1).replace(",", ""))
            elif "TDS-194A" in line or "Interest other than" in line:
                current_section = "tds_194a"
            elif "SFT-016(SB)" in line or "Interest income (SFT-016) – Savings" in line:
                current_section = "savings"
            elif "SFT-016(TD)" in line or "SFT-016(RD)" in line or "Term Deposit" in line or "Recurring Deposit" in line:
                current_section = "deposits"
            elif "SFT-015" in line or "Dividend income" in line:
                current_section = "dividends"
            elif "Advance Tax" in line or "Payment of Taxes" in line:
                current_section = "advance_tax"
            elif "Refund issued" in line or "Income Tax Refund" in line:
                current_section = "refund"
            elif "Outstanding demand" in line or "Tax due demand" in line:
                current_section = "demand"
            elif "Purchase of mutual fund" in line or "Purchase of equity shares" in line or "Outward remittance" in line:
                current_section = "purchase_securities"
            elif "Sale of mutual fund" in line or "Sale of equity shares" in line or "Redemption of mutual fund" in line or "Receipt of shares" in line:
                current_section = "sale_securities"
                
            # Parsing within section
            if current_section == "savings":
                match = re.search(r"(?:SFT-016\(SB\)|Savings)\b[\s\S]+?([A-Z0-9\s&.,\-]+?)\s*\((?:[A-Z0-9\s.]+)\)\s+\d+\s+([\d,]+(?:\.\d+)?)\s*$", line, re.IGNORECASE)
                if match:
                    inst = match.group(1).strip()
                    val = float(match.group(2).replace(",", ""))
                    savings_interest += val
                    savings_details.append({"source": inst, "amount": val})
            elif current_section == "deposits":
                match = re.search(r"(?:SFT-016\(TD\)|SFT-016\(RD\)|Term Deposit|Recurring Deposit)\b[\s\S]+?([A-Z0-9\s&.,\-]+?)\s*\((?:[A-Z0-9\s.]+)\)\s+\d+\s+([\d,]+(?:\.\d+)?)\s*$", line, re.IGNORECASE)
                if match:
                    inst = match.group(1).strip()
                    val = float(match.group(2).replace(",", ""))
                    fd_interest += val
                    fd_details.append({"source": inst, "amount": val})
            elif current_section == "dividends":
                match = re.search(r"(?:SFT-015|Dividend)\b[\s\S]+?([A-Z0-9\s&.,\-]+?)\s*\((?:[A-Z0-9\s.]+)\)\s+\d+\s+([\d,]+(?:\.\d+)?)\s*$", line, re.IGNORECASE)
                if match:
                    inst = match.group(1).strip()
                    val = float(match.group(2).replace(",", ""))
                    domestic_dividends += val
                    dividend_details.append({"source": inst, "amount": val})
            elif current_section == "tds_194a":
                # Check for bank/deductor name row: e.g. "REGIONAL OFFICE BOMMASANORA 2 (BLRR17454D) 1 32,103"
                ded_match = re.search(r"^([A-Z0-9\s&.,\-]+?)\s*\(([^)]+)\)\s+\d+\s+([\d,]+(?:\.\d+)?)\s*$", line, re.IGNORECASE)
                if ded_match:
                    current_deductor = ded_match.group(1).strip()
                    gross_amt = float(ded_match.group(3).replace(",", ""))
                    
                    if any(x in current_deductor.upper() for x in ["REGIONAL OFFICE", "BOMMASANORA", "BOMMASANDRA", "PROVIDENT", "EPFO"]):
                        is_epf_deductor = True
                        taxable_epf_interest += gross_amt
                        taxable_epf_interest_details.append({
                            "source": current_deductor,
                            "amount": gross_amt,
                            "tds": 0.0
                        })
                    else:
                        is_epf_deductor = False
                
                # Check detail row
                tds_match = re.search(r"^\d+\s+Q\d(?:\([^)]+\))?\s+\d{2}/\d{2}/\d{4}\s+[\d,]+\s+([\d,]+)\s+([\d,]+)\s+\w+", line)
                if tds_match:
                    tds_amt = float(tds_match.group(1).replace(",", ""))
                    if is_epf_deductor:
                        taxable_epf_interest_tds += tds_amt
                        if taxable_epf_interest_details:
                            taxable_epf_interest_details[-1]["tds"] += tds_amt
                    else:
                        tds_on_deposit_interest += tds_amt
                        tds_on_deposit_interest_details.append({
                            "source": current_deductor,
                            "amount": round(tds_amt * 10, 2),  # estimate gross amount
                            "tds": tds_amt
                        })
            elif current_section == "advance_tax":
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    advance_tax_paid += float(match.group(1).replace(",", ""))
            elif current_section == "refund":
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    tax_refund_amount += float(match.group(1).replace(",", ""))
            elif current_section == "demand":
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    tax_due_demand += float(match.group(1).replace(",", ""))
            elif current_section == "purchase_securities":
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    purchase_of_securities += float(match.group(1).replace(",", ""))
            elif current_section == "sale_securities":
                match = re.search(r"([\d,]+(?:\.\d+)?)\s*$", line)
                if match:
                    sale_of_securities += float(match.group(1).replace(",", ""))
                    
        if tax_refund_amount > 0:
            tax_refund_interest = round(tax_refund_amount * 0.005 * 4, 2)
            
        return {
            "savings_interest": savings_interest,
            "savings_details": savings_details,
            "fd_interest": fd_interest,
            "fd_details": fd_details,
            "domestic_dividends": domestic_dividends,
            "dividend_details": dividend_details,
            "taxable_epf_interest": taxable_epf_interest,
            "taxable_epf_interest_tds": taxable_epf_interest_tds,
            "taxable_epf_interest_details": taxable_epf_interest_details,
            "salary_gross_ais": salary_gross_ais,
            "purchase_of_securities": purchase_of_securities,
            "sale_of_securities": sale_of_securities,
            "advance_tax_paid": advance_tax_paid,
            "advance_tax_details": [],
            "tax_refund_amount": tax_refund_amount,
            "tax_refund_interest": tax_refund_interest,
            "tax_due_demand": tax_due_demand,
            "tds_on_deposit_interest": tds_on_deposit_interest,
            "tds_on_deposit_interest_details": tds_on_deposit_interest_details
        }

    def parse_ais_csv_list(self, csv_contents: list) -> dict:
        """Parses multiple AIS CSV file contents and merges them into a single summary."""
        summary = {
            "savings_interest": 0.0,
            "savings_details": [],
            "fd_interest": 0.0,
            "fd_details": [],
            "domestic_dividends": 0.0,
            "dividend_details": [],
            "taxable_epf_interest": 0.0,
            "taxable_epf_interest_tds": 0.0,
            "taxable_epf_interest_details": [],
            "salary_gross_ais": 0.0,
            "purchase_of_securities": 0.0,
            "sale_of_securities": 0.0,
            "advance_tax_paid": 0.0,
            "advance_tax_details": [],
            "tax_refund_amount": 0.0,
            "tax_refund_interest": 0.0,
            "tax_due_demand": 0.0,
            "tds_on_deposit_interest": 0.0,
            "tds_on_deposit_interest_details": []
        }
        
        for content in csv_contents:
            self._parse_single_ais_csv(content, summary)
            
        return summary

    def _parse_single_ais_csv(self, content: str, summary: dict):
        normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized.strip())
        reader = csv.reader(f)
        
        current_section = None
        for row in reader:
            if not row:
                continue
            row_str = "".join(row).lower()
            
            # Identify current CSV section
            if "savings bank" in row_str:
                current_section = "savings"
                continue
            elif "interest on deposits" in row_str:
                current_section = "fd"
                continue
            elif "dividend" in row_str:
                current_section = "dividend"
                continue
            elif "epfo" in row_str or "provident fund" in row_str:
                current_section = "epf"
                continue
            elif "salary" in row_str:
                current_section = "salary"
                continue
            elif "advance tax" in row_str or "payment of taxes" in row_str:
                current_section = "advance_tax"
                continue
            elif "refund issued" in row_str or "income tax refund" in row_str:
                current_section = "refund"
                continue
            elif "outstanding demand" in row_str or "tax demand" in row_str:
                current_section = "demand"
                continue
            elif "tds on interest" in row_str or "section 194a" in row_str:
                current_section = "tds_deposit"
                continue
                
            # Parse values based on section
            if len(row) >= 2:
                # Expecting first column to contain description/bank and second to contain amount
                desc = row[0].strip()
                val_str = row[1].strip()
                val = self._parse_float_val(val_str)
                if val <= 0:
                    continue
                    
                if current_section == "savings":
                    summary["savings_interest"] += val
                    summary["savings_details"].append({"source": desc, "amount": val})
                elif current_section == "fd":
                    summary["fd_interest"] += val
                    summary["fd_details"].append({"source": desc, "amount": val})
                elif current_section == "dividend":
                    summary["domestic_dividends"] += val
                    summary["dividend_details"].append({"source": desc, "amount": val})
                elif current_section == "epf":
                    # Taxable EPF interest u/s 10(11)/10(12)
                    summary["taxable_epf_interest"] += val
                    tds_val = 0.0
                    if len(row) >= 3:
                        tds_val = self._parse_float_val(row[2])
                        summary["taxable_epf_interest_tds"] += tds_val
                    summary["taxable_epf_interest_details"].append({"source": desc, "amount": val, "tds": tds_val})
                elif current_section == "salary":
                    summary["salary_gross_ais"] += val
                elif current_section == "advance_tax":
                    summary["advance_tax_paid"] += val
                    summary["advance_tax_details"].append({"source": desc, "amount": val})
                elif current_section == "refund":
                    summary["tax_refund_amount"] += val
                    # Extract refund interest u/s 244A if present in row
                    if len(row) >= 3:
                        summary["tax_refund_interest"] += self._parse_float_val(row[2])
                elif current_section == "demand":
                    summary["tax_due_demand"] += val
                elif current_section == "tds_deposit":
                    summary["tds_on_deposit_interest"] += val
                    tds_val = val
                    gross_est = round(tds_val * 10, 2)
                    summary["tds_on_deposit_interest_details"].append({"source": desc, "amount": gross_est, "tds": tds_val})
