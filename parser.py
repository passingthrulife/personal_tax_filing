import os
import re
import csv
import json
import io
import logging
from datetime import datetime, date
import PyPDF2
import pdfplumber
import anthropic
from rate_resolver import RateResolver

logger = logging.getLogger(__name__)

class DocumentParser:
    def __init__(self, rate_resolver: RateResolver):
        self.rate_resolver = rate_resolver
        self.anthropic_client = None
        self._init_anthropic()

    def _init_anthropic(self):
        """Initializes the Anthropic client if the API key is available."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            try:
                self.anthropic_client = anthropic.Anthropic(api_key=api_key)
                logger.info("Initialized Anthropic client for PDF parsing fallback.")
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic client: {e}")

    def decrypt_pdf(self, file_bytes: bytes, password: str = None) -> bytes:
        """Decrypts a PDF file if encrypted and returns decrypted bytes."""
        input_pdf = io.BytesIO(file_bytes)
        try:
            reader = PyPDF2.PdfReader(input_pdf, strict=False)
            if not reader.is_encrypted:
                return file_bytes

            # Attempt to decrypt
            decrypted = False
            passwords_to_try = []
            if password:
                passwords_to_try.append(password)
                # Try combinations (lowercase/uppercase)
                passwords_to_try.append(password.upper())
                passwords_to_try.append(password.lower())

            for pw in passwords_to_try:
                if reader.decrypt(pw) > 0:
                    decrypted = True
                    break

            if not decrypted:
                raise ValueError("PDF is encrypted and decryption failed. Incorrect password.")

            # Write decrypted PDF to bytes
            output = io.BytesIO()
            writer = PyPDF2.PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.write(output)
            return output.getvalue()
        except Exception as e:
            logger.error(f"PDF Decryption error: {e}")
            raise

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extracts text content from a PDF file."""
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes), strict=False)
            text_parts = []
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n--- Page Separator ---\n".join(text_parts)
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            return ""

    def parse_form16(self, pdf_bytes: bytes, password: str = None) -> dict:
        """Parses Form 16 PDF and extracts salary, perquisites, standard deductions, and home loan interest."""
        decrypted_bytes = self.decrypt_pdf(pdf_bytes, password)
        raw_text = self.extract_text_from_pdf(decrypted_bytes)
        
        # Try Claude parsing first if API client is available
        if self.anthropic_client:
            try:
                return self._parse_form16_with_claude(raw_text)
            except Exception as e:
                logger.error(f"Claude Form 16 parsing failed, falling back to regex: {e}")

        return self._parse_form16_with_regex(raw_text)

    def _parse_form16_with_claude(self, text: str) -> dict:
        """Uses Claude to parse Form 16 text structure into clean JSON."""
        prompt = f"""
Analyze the text of this Form 16 (Part B / Salary Certificate) and extract the key salary components and deductions.
Return ONLY a valid JSON object matching the following keys. Do not include markdown wraps (like ```json), commentary, or other characters.

Required Keys:
- "employer_name": (string or null)
- "employer_pan": (string or null)
- "employer_tan": (string or null)
- "employee_pan": (string or null)
- "gross_salary_17_1": (float, salary under Section 17(1))
- "perquisites_17_2": (float, value of perquisites under Section 17(2))
- "profits_lieu_17_3": (float, profits in lieu of salary under Section 17(3))
- "allowances_exempt_sec_10": (float, total allowances exempt under Section 10 like HRA, LTA, etc.)
- "standard_deduction_16_ia": (float, usually 50000 or 75000)
- "professional_tax_16_ii": (float, professional tax paid)
- "entertainment_allowance_16_iii": (float, usually 0)
- "deduction_80c": (float, total Section 80C deductions like EPF, PPF, life insurance, home loan principal)
- "deduction_80d": (float, health insurance deduction)
- "deduction_80ccd_1b": (float, NPS contribution up to 50000)
- "home_loan_interest_24b": (float, interest paid on home loan, reported as income/loss from house property)
- "tds_deducted": (float, total tax deducted at source by employer)

Form 16 text:
{text}
"""
        response = self.anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        content = response.content[0].text.strip()
        # Clean up code blocks if LLM still returned them
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        return json.loads(content)

    def _parse_form16_with_regex(self, text: str) -> dict:
        """Regex-based fallback parser for standard Form 16 text layouts."""
        data = {
            "employer_name": None,
            "employer_pan": None,
            "employer_tan": None,
            "employee_pan": None,
            "gross_salary_17_1": 0.0,
            "perquisites_17_2": 0.0,
            "profits_lieu_17_3": 0.0,
            "allowances_exempt_sec_10": 0.0,
            "standard_deduction_16_ia": 50000.0, # default fallback
            "professional_tax_16_ii": 0.0,
            "entertainment_allowance_16_iii": 0.0,
            "deduction_80c": 0.0,
            "deduction_80d": 0.0,
            "deduction_80ccd_1b": 0.0,
            "home_loan_interest_24b": 0.0,
            "tds_deducted": 0.0
        }

        # PAN/TAN Regex
        pan_matches = re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text)
        if len(pan_matches) >= 2:
            data["employer_pan"] = pan_matches[0]
            data["employee_pan"] = pan_matches[1]
        elif len(pan_matches) == 1:
            data["employee_pan"] = pan_matches[0]

        tan_matches = re.findall(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", text)
        if tan_matches:
            data["employer_tan"] = tan_matches[0]

        # Helper to find float numbers after keyword
        def find_value(pattern, text, default=0.0):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Remove commas and extract numbers
                num_str = match.group(1).replace(",", "")
                try:
                    return float(num_str)
                except ValueError:
                    pass
            return default

        # Try to parse salary sections using Gross Salary block isolation first
        gross_salary_17_1 = 0.0
        perquisites_17_2 = 0.0
        profits_lieu_17_3 = 0.0
        
        # Try to find the block of text for Gross Salary
        gross_block_match = re.search(r"Gross\s+Salary.*?(?:Total|Salary\s+received\s+from\s+current\s+employer)", text, re.DOTALL | re.IGNORECASE)
        if gross_block_match:
            block = gross_block_match.group(0)
            logger.info("Found Gross Salary block for Form 16 parsing.")
            
            # Find 17(1) in the block, prioritizing direct section label
            val_17_1 = find_value(r"17\(1\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_1 is None:
                val_17_1 = find_value(r"\(a\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            gross_salary_17_1 = val_17_1
            
            # Find 17(2) in the block
            val_17_2 = find_value(r"17\(2\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_2 is None:
                val_17_2 = find_value(r"\(b\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            perquisites_17_2 = val_17_2
            
            # Find 17(3) in the block
            val_17_3 = find_value(r"17\(3\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_3 is None:
                val_17_3 = find_value(r"\(c\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            profits_lieu_17_3 = val_17_3
        else:
            # Fallback to searching the entire text with direct patterns
            gross_salary_17_1 = find_value(
                r"(?:Salary\s+as\s+per\s+provisions\s+contained\s+in|Salary|gross\s+salary)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(1\)[^\d\n]*?([\d,]+(?:\.\d{2})?)", 
                text
            )
            perquisites_17_2 = find_value(
                r"(?:Value\s+of\s+perquisites|perquisites)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(2\)[^\d\n]*?([\d,]+(?:\.\d{2})?)", 
                text
            )
            if perquisites_17_2 == 0.0:
                perquisites_17_2 = find_value(r"\(b\)\s*([\d,]+(?:\.\d{2})?)", text)
                
            profits_lieu_17_3 = find_value(
                r"(?:Profits\s+in\s+lieu\s+of\s+salary|profits\s+in\s+lieu|profits\s+lieu)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(3\)[^\d\n]*?([\d,]+(?:\.\d{2})?)", 
                text
            )

        data["gross_salary_17_1"] = gross_salary_17_1
        data["perquisites_17_2"] = perquisites_17_2
        data["profits_lieu_17_3"] = profits_lieu_17_3
        
        # Standard deductions block parsing
        std_ded = 50000.0  # default fallback
        prof_tax = 0.0
        
        ded_block_match = re.search(r"Deductions\s+under\s+section\s+16.*?(?:Income\s+chargeable\s+under\s+the\s+head|Gross\s+total\s+income)", text, re.DOTALL | re.IGNORECASE)
        if ded_block_match:
            block = ded_block_match.group(0)
            logger.info("Found Deductions block for Form 16 parsing.")
            
            # Extract standard deduction: usually 75000 or 50000
            std_match = re.findall(r"\b(75000|50000)(?:\.00)?\b", block)
            if std_match:
                std_ded = float(std_match[0])
            else:
                val = find_value(r"Standard\s+deduction.*?16\(ia\)[^\d\n]*([\d,]+(?:\.\d{2})?)", block)
                if val > 0:
                    std_ded = val
                    
            # Extract professional tax: usually 2500 or 0
            prof_match = re.findall(r"(?:Tax\s+on\s+employment|16\(iii\)|16\(ii\)).*?([\d,]+(?:\.\d{2})?)", block)
            if prof_match:
                for val_str in prof_match:
                    try:
                        v = float(val_str.replace(",", ""))
                        if 0.0 < v <= 5000.0:
                            prof_tax = v
                            break
                    except ValueError:
                        continue
        else:
            # Fallback
            std_ded = find_value(r"Standard\s+deduction.*?16\(ia\)[^\d\n]*([\d,]+(?:\.\d{2})?)", text, 50000.0)
            prof_tax = find_value(r"(?:Tax\s+on\s+employment|professional\s+tax).*?16\(iii\)[^\d\n]*([\d,]+(?:\.\d{2})?)", text)
            if prof_tax == 0.0:
                prof_tax = find_value(r"(?:Tax\s+on\s+employment|professional\s+tax).*?16\(ii\)[^\d\n]*([\d,]+(?:\.\d{2})?)", text)
            
        data["standard_deduction_16_ia"] = std_ded
        data["professional_tax_16_ii"] = prof_tax

        # Allowances
        data["allowances_exempt_sec_10"] = find_value(
            r"(?:Total\s+amount\s+of\s+any\s+other\s+exemption|allowances\s+to\s+the\s+extent\s+exempt|exempt\s+allowances)\s+(?:under|u/s|sec\.?)?\s*10.*?([\d,]+(?:\.\d{2})?)", 
            text
        )
        
        # Home Loan Interest
        data["home_loan_interest_24b"] = find_value(
            r"(?:Interest\s+on\s+borrowed\s+capital|Income\s+or\s+loss\s+from\s+house\s+property|interest\s+on\s+housing\s+loan|interest\s+paid\s+on\s+home\s+loan)[^24]*24\(b\)?.*?([\d,]+(?:\.\d{2})?)", 
            text
        )
        
        # 80C, 80D
        data["deduction_80c"] = find_value(r"(?:Section|Sec\.?)\s*80C.*?([\d,]+(?:\.\d{2})?)", text)
        data["deduction_80d"] = find_value(r"(?:Section|Sec\.?)\s*80D.*?([\d,]+(?:\.\d{2})?)", text)
        data["deduction_80ccd_1b"] = find_value(r"(?:Section|Sec\.?)\s*80CCD\(1B\).*?([\d,]+(?:\.\d{2})?)", text)
        
        # TDS Deducted - match specific text to avoid matching section 192
        data["tds_deducted"] = find_value(
            r"(?:Tax\s+Deducted\s+from\s+Salary\s+of\s+Employee\s+u/s\s+192\(1\)|Total\s+tax\s+paid|Total\s+amount\s+of\s+tax\s+deducted\s+at\s+source|tax\s+deducted\s+by\s+employer)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", 
            text
        )

        return data

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
- "salary_gross_ais": (float, gross salary as reported in AIS, to verify against Form 16)
- "purchase_of_securities": (float, total purchase of mutual funds / shares)
- "sale_of_securities": (float, total sale of mutual funds / shares)
- "advance_tax_paid": (float, total advance tax paid, under Payment of Taxes or Advance Tax)
- "tax_refund_amount": (float, total income tax refund amount received from last year, under Part B4 / Demand & Refund)
- "tax_refund_interest": (float, estimate of interest on the refund u/s 244A, which is 0.5% per month or part of a month from April 1 of AY to payment date)
- "tax_due_demand": (float, outstanding tax demand / tax due from last year, under Part B4 / Demand & Refund)

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
        data = {
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
            "tax_due_demand": 0.0
        }

        # Match blocks containing keywords and sum them using a clean number tokenizer
        def find_sum_for_keyword(keywords, text):
            total = 0.0
            for line in text.split("\n"):
                if any(kw.lower() in line.lower() for kw in keywords):
                    # Tokenize by whitespace to examine words standalone
                    tokens = line.split()
                    clean_numbers = []
                    for token in tokens:
                        # Strip common leading/trailing punctuation or brackets
                        t = token.strip("(),.[]{}*'-")
                        # Strip trailing or leading letters (e.g. 'Active', 'TDS-')
                        t = re.sub(r'[a-zA-Z]+$', '', t)
                        t = re.sub(r'^[a-zA-Z]+', '', t)
                        
                        # Match valid standalone decimal/integer format
                        if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                            val = float(t.replace(",", ""))
                            clean_numbers.append(val)
                    
                    if clean_numbers:
                        # Keep numbers that are reasonable for tax/interest amounts
                        valid_nums = [n for n in clean_numbers if n > 5.0 and n < 500000000.0]
                        if valid_nums:
                            # The transaction amount is always the last clean number on the line
                            total += valid_nums[-1]
            return total

        # 1. State machine PDF parser to extract detailed schedules
        current_category = None
        current_source = None
        
        savings_interest = 0.0
        savings_details = []
        
        fd_interest = 0.0
        fd_details = []
        
        dividend_total = 0.0
        dividend_details = []
        
        lines = text.split("\n")
        for line in lines:
            line_lower = line.lower()
            
            # Detect summary headers
            if "sft-016(sb)" in line_lower or ("sft-016" in line_lower and "savings" in line_lower):
                current_category = "savings"
                match = re.search(r"(?:Savings|SFT-016)\s*–?\s*([A-Z\s]+?)\s*\(", line, re.IGNORECASE)
                current_source = match.group(1).strip() if match else "Unknown Bank"
                continue
            elif "sft-016(td)" in line_lower or "sft-016(rd)" in line_lower or ("sft-016" in line_lower and "deposit" in line_lower):
                current_category = "deposit"
                match = re.search(r"(?:Term Deposit|Recurring Deposit|Deposit)\s*([A-Z\s]+?)\s*\(", line, re.IGNORECASE)
                current_source = match.group(1).strip() if match else "Unknown Bank"
                continue
            elif "sft-015" in line_lower or "dividend income" in line_lower:
                current_category = "dividend"
                match = re.search(r"(?:Dividend income \(SFT-015\)|Dividend)\s*([A-Z\s&]+?)\s*\(", line, re.IGNORECASE)
                current_source = match.group(1).strip() if match else "Unknown Company"
                continue
            elif "part b" in line_lower or "information relating to" in line_lower:
                current_category = None
                current_source = None
                
            # Parse detail lines
            if current_category == "savings" and "saving" in line_lower and "active" in line_lower:
                tokens = line.split()
                acc_num = "Unknown"
                for i, tok in enumerate(tokens):
                    if tok.lower() == "saving" and i > 0:
                        acc_num = tokens[i-1]
                        break
                nums = []
                for token in tokens:
                    t = token.strip("(),.[]{}*'-")
                    t = re.sub(r'[a-zA-Z]+$', '', t)
                    t = re.sub(r'^[a-zA-Z]+', '', t)
                    if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                        nums.append(float(t.replace(",", "")))
                if nums:
                    amt = nums[-1]
                    savings_interest += amt
                    savings_details.append({"source": current_source, "account": acc_num, "amount": amt})
            elif current_category == "deposit" and ("deposit" in line_lower or "time deposit" in line_lower or "recurring deposit" in line_lower) and "active" in line_lower:
                tokens = line.split()
                acc_num = "Unknown"
                for i, tok in enumerate(tokens):
                    if "deposit" in tok.lower() and i > 1:
                        acc_num = tokens[i-2] if "time" in tokens[i-1].lower() or "recurring" in tokens[i-1].lower() else tokens[i-1]
                        break
                nums = []
                for token in tokens:
                    t = token.strip("(),.[]{}*'-")
                    t = re.sub(r'[a-zA-Z]+$', '', t)
                    t = re.sub(r'^[a-zA-Z]+', '', t)
                    if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                        nums.append(float(t.replace(",", "")))
                if nums:
                    amt = nums[-1]
                    fd_interest += amt
                    fd_details.append({"source": current_source, "account": acc_num, "amount": amt})
            elif current_category == "dividend" and "active" in line_lower:
                tokens = line.split()
                nums = []
                for token in tokens:
                    t = token.strip("(),.[]{}*'-")
                    t = re.sub(r'[a-zA-Z]+$', '', t)
                    t = re.sub(r'^[a-zA-Z]+', '', t)
                    if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                        nums.append(float(t.replace(",", "")))
                if nums:
                    amt = nums[-1]
                    dividend_total += amt
                    dividend_details.append({"source": current_source, "amount": amt})
                    
        data["savings_interest"] = savings_interest
        data["savings_details"] = savings_details
        data["fd_interest"] = fd_interest
        data["fd_details"] = fd_details
        data["domestic_dividends"] = dividend_total
        data["dividend_details"] = dividend_details
        
        # Parse EPFO interest and EPFO TDS
        epfo_interest = 0.0
        epfo_tds = 0.0
        for line in lines:
            if "bommasanora" in line.lower() or "blrr17454d" in line.lower():
                tokens = line.split()
                clean_numbers = []
                for token in tokens:
                    t = token.strip("(),.[]{}*'-")
                    t = re.sub(r'[a-zA-Z]+$', '', t)
                    t = re.sub(r'^[a-zA-Z]+', '', t)
                    if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                        clean_numbers.append(float(t.replace(",", "")))
                if clean_numbers:
                    epfo_interest = clean_numbers[-1]
                    
        if epfo_interest > 0:
            for line in lines:
                if re.search(r'q[1-4]\(.*?\)', line, re.IGNORECASE) and "active" in line.lower():
                    tokens = line.split()
                    clean_numbers = []
                    for token in tokens:
                        t = token.strip("(),.[]{}*'-")
                        t = re.sub(r'[a-zA-Z]+$', '', t)
                        t = re.sub(r'^[a-zA-Z]+', '', t)
                        if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                            clean_numbers.append(float(t.replace(",", "")))
                    if len(clean_numbers) >= 3:
                        if abs(clean_numbers[0] - epfo_interest) < 2.0:
                            epfo_tds = clean_numbers[1]
                            break
                            
        data["taxable_epf_interest"] = epfo_interest
        data["taxable_epf_interest_tds"] = epfo_tds
        if epfo_interest > 0:
            data["taxable_epf_interest_details"] = [{"source": "REGIONAL OFFICE BOMMASANORA 2", "amount": epfo_interest, "tds": epfo_tds}]
            
        data["salary_gross_ais"] = find_sum_for_keyword(["salary received", "salary income"], text)
        
        # Parse advance tax details
        advance_tax_total = 0.0
        advance_tax_details = []
        for line in lines:
            if "advance tax" in line.lower() or "payment of taxes" in line.lower() or "payment of tax" in line.lower():
                date_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                if date_match:
                    pmt_date_str = date_match.group(1)
                    tokens = line.split()
                    nums = []
                    for token in tokens:
                        t = token.strip("(),.[]{}*'-")
                        t = re.sub(r'[a-zA-Z]+$', '', t)
                        t = re.sub(r'^[a-zA-Z]+', '', t)
                        if re.match(r'^\d{1,3}(,\d{2,3})*(\.\d+)?$|^\d+(\.\d+)?$', t):
                            nums.append(float(t.replace(",", "")))
                    if nums:
                        valid_tax_nums = [n for n in nums if n > 100 and n != 12025 and n != 2025 and n != 2026]
                        if valid_tax_nums:
                            amt = valid_tax_nums[0]
                            advance_tax_total += amt
                            advance_tax_details.append({"source": "Income Tax Department", "amount": amt, "date": pmt_date_str})
                            
        data["advance_tax_paid"] = advance_tax_total if advance_tax_total > 0 else find_sum_for_keyword(["advance tax"], text)
        data["advance_tax_details"] = advance_tax_details

        # Parse B4 Refund and Demand
        for line in text.split("\n"):
            if "ecs" in line.lower() or "refund" in line.lower() or "direct credit" in line.lower():
                match = re.search(r"(20\d{2}-\d{2})\s+.*?([\d,]+)(\d{2}/\d{2}/\d{4})", line, re.IGNORECASE)
                if match:
                    try:
                        fy_str = match.group(1)
                        ref_str = match.group(2)
                        date_str = match.group(3)
                        
                        ref_val = float(ref_str.replace(",", ""))
                        data["tax_refund_amount"] += ref_val
                        
                        pmt_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                        fy_start_year = int(fy_str.split("-")[0])
                        ay_start_year = fy_start_year + 1
                        ay_start_date = date(ay_start_year, 4, 1)
                        
                        if pmt_date > ay_start_date:
                            months = (pmt_date.year - ay_start_date.year) * 12 + pmt_date.month - ay_start_date.month
                            if pmt_date.day >= 1:
                                months += 1
                            months = max(0, months)
                            interest_est = ref_val * 0.005 * months
                            data["tax_refund_interest"] += interest_est
                    except Exception as ex:
                        logger.warning(f"Error parsing refund u/s 244A in PDF regex fallback: {ex}")
            
            if "demand" in line.lower() and not "demand and refund" in line.lower():
                match = re.search(r"(20\d{2}-\d{2})\s+Demand.*?([\d,]+)", line, re.IGNORECASE)
                if match:
                    try:
                        data["tax_due_demand"] += float(match.group(2).replace(",", ""))
                    except Exception as ex:
                        logger.warning(f"Error parsing demand in PDF regex fallback: {ex}")

        return data

    def _parse_float_val(self, val_str: str) -> float:
        if not val_str:
            return 0.0
        val_str = val_str.replace(",", "").replace("₹", "").strip()
        try:
            return float(val_str)
        except ValueError:
            return 0.0

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
            "tax_due_demand": 0.0
        }
        
        for content in csv_contents:
            self._parse_single_ais_csv(content, summary)
            
        return summary

    def _parse_single_ais_csv(self, content: str, summary: dict):
        normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized.strip())
        reader = csv.reader(f)
        rows = list(reader)
        if len(rows) < 2:
            return
            
        header_idx = -1
        for idx, row in enumerate(rows):
            if any(h.lower() in ["s.no", "s.no.", "sno", "sr. no.", "sr.no"] for h in row):
                header_idx = idx
                break
                
        if header_idx == -1:
            for idx in range(min(3, len(rows))):
                if any("category" in h.lower() or "description" in h.lower() for h in rows[idx]):
                    header_idx = idx
                    break
                    
        if header_idx == -1:
            if len(rows[0]) > 0 and "L2 level" in rows[0][0] and len(rows) > 1:
                header_idx = 1
            else:
                header_idx = 0
                
        headers = [h.strip().lower() for h in rows[header_idx]]
        data_rows = rows[header_idx + 1:]
        
        col_map = {h: i for i, h in enumerate(headers)}
        
        is_savings = False
        is_fd = False
        is_dividend = False
        is_salary = False
        is_refund_demand = False
        is_epfo = False
        
        cat_col = col_map.get("information category") or col_map.get("information description")
        desc_col = col_map.get("information description")
        source_col = col_map.get("information source")
        
        if "dividend amount - reported by source" in col_map:
            is_dividend = True
        elif "gross salary u/s 17(1)" in col_map or "value of perquisites u/s 17(2)" in col_map or "gross salary - reported by source" in col_map:
            is_salary = True
        elif "nature of refund" in col_map or "refund amount" in col_map or "demand amount" in col_map:
            is_refund_demand = True
        else:
            # Detect EPFO source
            is_epfo_source = False
            if len(data_rows) > 0:
                for row in data_rows:
                    if source_col is not None and len(row) > source_col:
                        src_val = row[source_col].lower()
                        if "bommasanora" in src_val or "epfo" in src_val or "provident" in src_val:
                            is_epfo_source = True
                            break
                    if desc_col is not None and len(row) > desc_col:
                        desc_val = row[desc_col].lower()
                        if "bommasanora" in desc_val or "epfo" in desc_val or "provident" in desc_val:
                            is_epfo_source = True
                            break
            if is_epfo_source:
                is_epfo = True
            elif "interest amount - reported by source" in col_map:
                if cat_col is not None and len(data_rows) > 0:
                    first_cat = data_rows[0][cat_col].lower()
                    if "savings" in first_cat:
                        is_savings = True
                    else:
                        is_fd = True
                else:
                    is_savings = True
            
        for row in data_rows:
            if not row or len(row) <= max(col_map.values(), default=-1):
                continue
                
            if is_savings:
                val = self._parse_float_val(row[col_map["interest amount - reported by source"]])
                summary["savings_interest"] += val
                src = row[col_map["information source"]] if "information source" in col_map else ""
                acc = row[col_map["account number"]] if "account number" in col_map else ""
                summary["savings_details"].append({"source": src, "account": acc, "amount": val})
            elif is_fd:
                val = self._parse_float_val(row[col_map["interest amount - reported by source"]])
                summary["fd_interest"] += val
                src = row[col_map["information source"]] if "information source" in col_map else ""
                acc = row[col_map["account number"]] if "account number" in col_map else ""
                summary["fd_details"].append({"source": src, "account": acc, "amount": val})
            elif is_epfo:
                amt_col = col_map.get("amount") or col_map.get("amount paid/credited - reported by source")
                val = 0.0
                if amt_col is not None:
                    val = self._parse_float_val(row[amt_col])
                    summary["taxable_epf_interest"] += val
                tds_col = col_map.get("tds deducted") or col_map.get("tds deposited")
                tds_val = 0.0
                if tds_col is not None:
                    tds_val = self._parse_float_val(row[tds_col])
                    summary["taxable_epf_interest_tds"] += tds_val
                
                src = row[col_map["information source"]] if "information source" in col_map else ""
                acc = row[col_map["account number"]] if "account number" in col_map else ""
                summary["taxable_epf_interest_details"].append({"source": src, "account": acc, "amount": val, "tds": tds_val})
            elif is_dividend:
                val = self._parse_float_val(row[col_map["dividend amount - reported by source"]])
                summary["domestic_dividends"] += val
                src = row[col_map["information source"]] if "information source" in col_map else ""
                summary["dividend_details"].append({"source": src, "amount": val})
            elif is_salary:
                if "gross salary - reported by source" in col_map:
                    val = self._parse_float_val(row[col_map["gross salary - reported by source"]])
                    summary["salary_gross_ais"] += val
            elif is_refund_demand:
                ref_col = col_map.get("refund amount") or col_map.get("amount")
                if ref_col is not None:
                    ref_val = self._parse_float_val(row[ref_col])
                    summary["tax_refund_amount"] += ref_val
                    
                    date_col = col_map.get("date of payment") or col_map.get("reported on")
                    fy_col = col_map.get("financial year")
                    
                    if date_col is not None and row[date_col]:
                        date_str = row[date_col].strip()
                        date_match = re.search(r"(\d{2}/\d{2}/\d{4})", date_str)
                        if date_match:
                            pmt_date_str = date_match.group(1)
                            try:
                                pmt_date = datetime.strptime(pmt_date_str, "%d/%m/%Y").date()
                                ay_start_year = 2025
                                if fy_col is not None and row[fy_col]:
                                    fy_str = row[fy_col].strip()
                                    fy_match = re.search(r"(\d{4})", fy_str)
                                    if fy_match:
                                        ay_start_year = int(fy_match.group(1)) + 1
                                        
                                ay_start_date = date(ay_start_year, 4, 1)
                                if pmt_date > ay_start_date:
                                    months = (pmt_date.year - ay_start_date.year) * 12 + pmt_date.month - ay_start_date.month
                                    if pmt_date.day >= 1:
                                        months += 1
                                    months = max(0, months)
                                    interest_est = ref_val * 0.005 * months
                                    summary["tax_refund_interest"] += interest_est
                            except Exception as ex:
                                logger.warning(f"Error estimating refund interest in CSV: {ex}")
                                
                dem_col = col_map.get("demand amount") or col_map.get("tax due")
                if dem_col is not None:
                    summary["tax_due_demand"] += self._parse_float_val(row[dem_col])

    def parse_stock_sales_csv(self, csv_content: str, is_us: bool = False) -> list:
        """
        Parses stock sales CSV dynamically.
        Scans rows to find where headers start and maps column indexes flexibly.
        If standard mapping fails, uses Claude 3.5 Haiku to resolve column mapping.
        """
        records = []
        # Handle cases where CSV has weird line endings
        normalized_content = csv_content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized_content.strip())
        reader = csv.reader(f)
        
        rows = list(reader)
        if not rows:
            return []
            
        header_row_idx = -1
        headers = []
        
        # Look for the header row matching key fields
        for idx, row in enumerate(rows):
            row_headers = [str(cell).strip().lower() for cell in row]
            
            def has_match(names):
                return any(any(name in cell for name in names) for cell in row_headers)
                
            has_sym = has_match(["symbol", "ticker", "share", "asset", "description", "security", "name"])
            has_qty = has_match(["quantity", "qty", "shares", "units", "quantity sold"])
            has_buy_dt = has_match(["buy date", "purchase date", "buy_date", "purchase_date", "acquired", "date acquired", "acq date", "dt_buy", "opened date", "open date", "opened_date"])
            has_buy_val = has_match(["cost per share", "purchase price per share", "buy price per share", "price per share", "buy price", "purchase price", "cost basis", "buy_val", "cost", "total cost", "purchase value", "cost basis (cb)", "cost basis (usd)"])
            has_sell_dt = has_match(["sell date", "sale date", "sell_date", "sale_date", "sold", "date sold", "disposal date", "dt_sell", "closed date", "close date", "closed_date", "transaction closed date"])
            has_sell_val = has_match(["proceeds per share", "sale price per share", "sell price per share", "price per share", "sell price", "sale price", "proceeds", "gross proceeds", "total proceeds", "value sold", "sales proceeds", "proceeds (usd)"])
            
            # If we match at least 4 core columns, this is our header row
            matches_count = sum([has_sym, has_qty, has_buy_dt, has_buy_val, has_sell_dt, has_sell_val])
            if matches_count >= 4:
                header_row_idx = idx
                headers = row_headers
                break
                
        if header_row_idx == -1:
            # Fallback: Find first non-empty row
            for idx, row in enumerate(rows):
                if any(row):
                    header_row_idx = idx
                    headers = [str(cell).strip().lower() for cell in row]
                    break
                    
        if header_row_idx == -1:
            return []
            
        # Get column indexes
        def get_col_idx(names):
            for name in names:
                for col_idx, h in enumerate(headers):
                    if name in h:
                        return col_idx
            return -1

        sym_idx = get_col_idx(["symbol", "ticker", "share", "asset", "description", "security"])
        isin_idx = get_col_idx(["isin", "code"])
        qty_idx = get_col_idx(["quantity sold", "quantity", "qty", "shares", "units"])
        buy_date_idx = get_col_idx(["date acquired", "acquired", "acq date", "opened date", "open date", "opened_date", "buy date", "purchase date", "buy_date", "purchase_date", "dt_buy"])
        buy_price_idx = get_col_idx(["cost per share", "purchase price per share", "buy price per share", "price per share", "cost basis (cb)", "cost basis (usd)", "cost basis", "cost", "total cost", "purchase price", "buy price", "buy_price", "purchase_price", "purchase value"])
        sell_date_idx = get_col_idx(["date sold", "sold", "closed date", "close date", "closed_date", "transaction closed date", "sell date", "sale date", "sell_date", "sale_date", "disposal date", "dt_sell"])
        sell_price_idx = get_col_idx(["proceeds per share", "sale price per share", "sell price per share", "price per share", "proceeds (usd)", "proceeds", "gross proceeds", "total proceeds", "sell price", "sale price", "sell_price", "sale_price", "value sold", "sales proceeds"])

        # Invoke Claude to resolve headers if standard search is incomplete
        if any(idx == -1 for idx in [qty_idx, buy_date_idx, buy_price_idx, sell_date_idx, sell_price_idx]) and self.anthropic_client:
            try:
                logger.info(f"Regex column matching failed for some headers. Invoking Claude. Headers: {headers}")
                prompt = f"""
                Analyze the following CSV header columns from a stock brokerage statement.
                Map them to the required fields:
                1. "quantity" (quantity of shares sold)
                2. "buy_date" (date the shares were purchased/acquired)
                3. "buy_price" (purchase price / cost basis per share or total cost basis)
                4. "sell_date" (date the shares were sold)
                5. "sell_price" (sale price / proceeds per share or total proceeds)
                6. "symbol" (ticker / asset symbol, optional)
                
                List of headers:
                {headers}
                
                Return ONLY a valid JSON object where keys are the required fields and values are the exact matching header string from the list (or null if not found).
                Do not wrap in markdown or add explanations.
                """
                response = self.anthropic_client.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                content = response.content[0].text.strip()
                if content.startswith("```"):
                    content = content.replace("```json", "").replace("```", "").strip()
                mapping = json.loads(content)
                
                def get_mapped_idx(key):
                    h_name = mapping.get(key)
                    if h_name and h_name.strip().lower() in headers:
                        return headers.index(h_name.strip().lower())
                    return -1
                    
                if get_mapped_idx("quantity") != -1: qty_idx = get_mapped_idx("quantity")
                if get_mapped_idx("buy_date") != -1: buy_date_idx = get_mapped_idx("buy_date")
                if get_mapped_idx("buy_price") != -1: buy_price_idx = get_mapped_idx("buy_price")
                if get_mapped_idx("sell_date") != -1: sell_date_idx = get_mapped_idx("sell_date")
                if get_mapped_idx("sell_price") != -1: sell_price_idx = get_mapped_idx("sell_price")
                if get_mapped_idx("symbol") != -1: sym_idx = get_mapped_idx("symbol")
            except Exception as e:
                logger.error(f"Claude column resolver failed: {e}")

        # Check if basic columns were resolved
        if any(idx == -1 for idx in [qty_idx, buy_date_idx, buy_price_idx, sell_date_idx, sell_price_idx]):
            logger.error(f"Missing required columns in stock CSV. Headers found: {headers}")
            raise ValueError(f"Required columns (Quantity, Buy Date, Buy Price, Sell Date, Sell Price) not resolved in CSV headers: {headers}")

        # Identify if buy/sell prices are total values or unit prices
        buy_header = headers[buy_price_idx]
        sell_header = headers[sell_price_idx]
        buy_is_total = any(w in buy_header for w in ["basis", "total", "proceeds", "cost"]) and "price" not in buy_header and "per" not in buy_header
        sell_is_total = any(w in sell_header for w in ["proceeds", "total", "basis"]) and "price" not in sell_header and "per" not in sell_header

        # Parse data rows (skipping headers and any prior metadata rows)
        for row in rows[header_row_idx + 1:]:
            if not row or len(row) < max(qty_idx, buy_date_idx, buy_price_idx, sell_date_idx, sell_price_idx) + 1:
                continue
            # Skip totals rows if the broker added a summary line at the end
            row_str = " ".join([str(c) for c in row]).lower()
            if "total" in row_str and len(row_str) < 50 and any(idx != -1 for idx in [buy_price_idx, sell_price_idx]):
                # Skip summary footer
                continue
                
            try:
                symbol = row[sym_idx].strip() if sym_idx != -1 else "UNKNOWN"
                isin = row[isin_idx].strip() if isin_idx != -1 else ""
                
                # Check for empty cells in critical fields
                if not row[qty_idx].strip() or not row[buy_price_idx].strip() or not row[sell_price_idx].strip():
                    continue
                    
                qty = float(re.sub(r"[^\d\.\-]", "", row[qty_idx]))
                if qty <= 0:
                    continue
                
                # Parse dates
                buy_date_str = row[buy_date_idx].strip()
                sell_date_str = row[sell_date_idx].strip()
                
                def parse_date(d_str):
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                        try:
                            return datetime.strptime(d_str, fmt).date()
                        except ValueError:
                            continue
                    # Parse using dateutil as fallback
                    try:
                        return parser.parse(d_str).date()
                    except Exception:
                        raise ValueError(f"Unable to parse date string: {d_str}")

                buy_date = parse_date(buy_date_str)
                sell_date = parse_date(sell_date_str)

                raw_buy_val = float(re.sub(r"[^\d\.\-]", "", row[buy_price_idx]))
                raw_sell_val = float(re.sub(r"[^\d\.\-]", "", row[sell_price_idx]))

                # Adjust total values to unit values if header indicates total
                if buy_is_total:
                    buy_price_val = raw_buy_val / qty
                else:
                    buy_price_val = raw_buy_val

                if sell_is_total:
                    sell_price_val = raw_sell_val / qty
                else:
                    sell_price_val = raw_sell_val

                if is_us:
                    buy_rate = self.rate_resolver.resolve_rule_115_rate(buy_date)
                    sell_rate = self.rate_resolver.resolve_rule_115_rate(sell_date)
                    buy_price_inr = buy_price_val * buy_rate
                    sell_price_inr = sell_price_val * sell_rate
                    rate_buy_used = buy_rate
                    rate_sell_used = sell_rate
                else:
                    buy_price_inr = buy_price_val
                    sell_price_inr = sell_price_val
                    rate_buy_used = 1.0
                    rate_sell_used = 1.0

                records.append({
                    "symbol": symbol,
                    "isin": isin,
                    "quantity": qty,
                    "buy_date": buy_date,
                    "buy_price": buy_price_val,
                    "buy_price_inr": buy_price_inr,
                    "sell_date": sell_date,
                    "sell_price": sell_price_val,
                    "sell_price_inr": sell_price_inr,
                    "rate_buy_used": rate_buy_used,
                    "rate_sell_used": rate_sell_used,
                    "is_us": is_us
                })
            except Exception as e:
                logger.warning(f"Failed to parse row {row}: {e}")
                continue

        return records

    def parse_us_dividends_csv(self, csv_content: str) -> list:
        """
        Parses US dividends CSV.
        Supports both:
        1. Column-based layout: columns for Date, Gross Amount, and Withholding Tax.
        2. Transaction-based layout (row-based): separate rows for Gross Dividend and NRA Tax Adjustment.
        Groups by Date and Ticker Symbol to associate tax adjustments with dividends.
        """
        records = []
        # Handle cases where CSV has weird line endings
        normalized_content = csv_content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized_content.strip())
        reader = csv.reader(f)
        
        rows = list(reader)
        if not rows:
            return []
            
        header_row_idx = -1
        headers = []
        
        # Scan for header row
        for idx, row in enumerate(rows):
            row_headers = [str(cell).strip().lower() for cell in row]
            
            def has_match(names):
                return any(any(name in cell for name in names) for cell in row_headers)
                
            has_dt = has_match(["date", "payment date", "dt"])
            has_amt = has_match(["amount", "dividend", "gross", "usd", "value"])
            has_symbol = has_match(["symbol", "ticker", "asset"])
            
            if has_dt and has_amt:
                header_row_idx = idx
                headers = row_headers
                break
                
        if header_row_idx == -1:
            # Fallback
            for idx, row in enumerate(rows):
                if any(row):
                    header_row_idx = idx
                    headers = [str(cell).strip().lower() for cell in row]
                    break
                    
        if header_row_idx == -1:
            return []
            
        def get_col_idx(names):
            for name in names:
                for col_idx, h in enumerate(headers):
                    if name in h:
                        return col_idx
            return -1

        date_idx = get_col_idx(["date", "payment date", "dt"])
        amt_idx = get_col_idx(["amount", "dividend", "gross", "usd", "value"])
        tax_idx = get_col_idx(["tax", "withholding", "withheld", "federal tax"])
        sym_idx = get_col_idx(["symbol", "ticker", "share", "asset", "description"])
        action_idx = get_col_idx(["action", "type", "description", "memo"])

        # Check if it's transaction row-based format (contains Action column)
        is_transaction_format = (action_idx != -1)
        
        if is_transaction_format:
            # Group transactions by (Date, Symbol)
            groups = {}
            for row in rows[header_row_idx + 1:]:
                if not row or len(row) < max(date_idx, amt_idx, action_idx) + 1:
                    continue
                try:
                    date_str = row[date_idx].strip()
                    def parse_date(d_str):
                        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                            try:
                                return datetime.strptime(d_str, fmt).date()
                            except ValueError:
                                continue
                        try:
                            return parser.parse(d_str).date()
                        except Exception:
                            raise ValueError(f"Unable to parse date string: {d_str}")
                            
                    div_date = parse_date(date_str)
                    action = row[action_idx].strip().lower()
                    symbol = row[sym_idx].strip().upper() if sym_idx != -1 else "UNKNOWN"
                    amount_str = re.sub(r"[^\d\.\-]", "", row[amt_idx])
                    if not amount_str:
                        continue
                    amount = float(amount_str)
                    
                    key = (div_date, symbol)
                    if key not in groups:
                        groups[key] = {"gross": 0.0, "tax": 0.0}
                        
                    if "dividend" in action or "div" in action or amount > 0:
                        groups[key]["gross"] += amount
                    elif "tax" in action or "adj" in action or "withholding" in action or amount < 0:
                        groups[key]["tax"] += abs(amount)
                except Exception as e:
                    logger.warning(f"Failed to parse transaction row {row}: {e}")
                    continue
                    
            for (div_date, symbol), vals in groups.items():
                if vals["gross"] <= 0:
                    continue
                
                # Apply Rule 115 rate
                rate = self.rate_resolver.resolve_rule_115_rate(div_date)
                records.append({
                    "symbol": symbol,
                    "date": div_date,
                    "amount_usd": vals["gross"],
                    "amount_inr": vals["gross"] * rate,
                    "withholding_usd": vals["tax"],
                    "withholding_inr": vals["tax"] * rate,
                    "rate_used": rate
                })
        else:
            # Column-based format
            for row in rows[header_row_idx + 1:]:
                if not row or len(row) < max(date_idx, amt_idx) + 1:
                    continue
                try:
                    date_str = row[date_idx].strip()
                    def parse_date(d_str):
                        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                            try:
                                return datetime.strptime(d_str, fmt).date()
                            except ValueError:
                                continue
                        return parser.parse(d_str).date()
                        
                    div_date = parse_date(date_str)
                    amount_usd = float(re.sub(r"[^\d\.\-]", "", row[amt_idx]))
                    
                    withholding_usd = 0.0
                    if tax_idx != -1 and len(row) > tax_idx:
                        tax_str = re.sub(r"[^\d\.\-]", "", row[tax_idx])
                        if tax_str:
                            withholding_usd = abs(float(tax_str))
                            
                    symbol = row[sym_idx].strip().upper() if sym_idx != -1 else "UNKNOWN"
                    
                    rate = self.rate_resolver.resolve_rule_115_rate(div_date)
                    records.append({
                        "symbol": symbol,
                        "date": div_date,
                        "amount_usd": amount_usd,
                        "amount_inr": amount_usd * rate,
                        "withholding_usd": withholding_usd,
                        "withholding_inr": withholding_usd * rate,
                        "rate_used": rate
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse column row {row}: {e}")
                    continue

        return records

    def _find_best_value_for_label(self, label_bbox: dict, candidate_words: list, direction: str = "below") -> dict:
        best_candidate = None
        best_score = float('inf')
        
        lx0, lx1, ltop, lbot = label_bbox["x0"], label_bbox["x1"], label_bbox["top"], label_bbox["bottom"]
        
        for w in candidate_words:
            wx0, wx1, wtop, wbot = w["x0"], w["x1"], w["top"], w["bottom"]
            
            if direction == "below":
                is_below = wtop >= lbot + 2 and wtop <= lbot + 35
                horiz_overlap = (wx0 >= lx0 - 5 and wx0 <= lx1 + 5) or (wx1 >= lx0 - 5 and wx1 <= lx1 + 5) or (wx0 <= lx0 and wx1 >= lx1)
                
                if is_below and horiz_overlap:
                    v_dist = wtop - lbot
                    h_shift = abs((wx0 + wx1)/2 - (lx0 + lx1)/2)
                    score = v_dist + h_shift * 0.5
                    if score < best_score:
                        best_score = score
                        best_candidate = w
                        
            elif direction == "right":
                is_right_height = abs(wtop - ltop) <= 10 or abs(wbot - lbot) <= 10
                is_right_side = wx0 >= lx1 - 5 and wx0 <= lx1 + 180
                
                if is_right_height and is_right_side:
                    h_dist = wx0 - lx1
                    v_shift = abs(wtop - ltop)
                    score = h_dist + v_shift * 2
                    if score < best_score:
                        best_score = score
                        best_candidate = w
                        
        return best_candidate

    def parse_1042s(self, pdf_bytes: bytes) -> list:
        """
        Parses Form 1042-S PDF page-by-page using pdfplumber coordinate-based cells extraction.
        Deduplicates identical forms and returns a list of unique forms.
        """
        unique_forms = []
        seen = set()
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    if "1042-S" not in text:
                        continue
                        
                    # Extract words
                    words = page.extract_words()
                    
                    # Locate candidate numbers
                    candidate_words = []
                    for w in words:
                        txt = w["text"].strip().replace("..", ".").replace(",", "")
                        # Matches decimals or integers
                        if re.match(r"^\d+\.\d{2}$", txt) or re.match(r"^\d+$", txt):
                            candidate_words.append(w)
                            
                    # 1. Gross Income label: "Gross" + "income"
                    gross_words = [w for w in words if w["text"].lower() in ["gross", "income"]]
                    gross_label_bbox = None
                    for w1 in gross_words:
                        if w1["text"].lower() == "gross":
                            for w2 in gross_words:
                                if w2["text"].lower() == "income" and abs(w2["top"] - w1["top"]) <= 5 and abs(w2["x0"] - w1["x1"]) <= 20:
                                    gross_label_bbox = {
                                        "x0": min(w1["x0"], w2["x0"]),
                                        "x1": max(w1["x1"], w2["x1"]),
                                        "top": min(w1["top"], w2["top"]),
                                        "bottom": max(w1["bottom"], w2["bottom"])
                                    }
                                    break
                            if gross_label_bbox:
                                break
                                
                    # 2. Withholding Tax label: "Federal" + "tax" + "withheld"
                    withheld_words = [w for w in words if w["text"].lower() in ["federal", "tax", "withheld"]]
                    withheld_bbox = None
                    for w1 in withheld_words:
                        if w1["text"].lower() == "federal":
                            for w2 in withheld_words:
                                if w2["text"].lower() == "tax" and abs(w2["top"] - w1["top"]) <= 5:
                                    for w3 in withheld_words:
                                        if w3["text"].lower() == "withheld" and abs(w3["top"] - w2["top"]) <= 10:
                                            withheld_bbox = {
                                                "x0": min(w1["x0"], w2["x0"], w3["x0"]),
                                                "x1": max(w1["x1"], w2["x1"], w3["x1"]),
                                                "top": min(w1["top"], w2["top"], w3["top"]),
                                                "bottom": max(w1["bottom"], w2["bottom"], w3["bottom"])
                                            }
                                            break
                            if withheld_bbox:
                                break
                                
                    # 3. Income Code label: "Income" + "code" (can be on next line)
                    code_bbox = None
                    for w1 in words:
                        if w1["text"].lower() == "income":
                            for w2 in words:
                                if w2["text"].lower() == "code":
                                    on_same_line = abs(w2["top"] - w1["top"]) <= 5 and abs(w2["x0"] - w1["x1"]) <= 25
                                    on_next_line = (w2["top"] > w1["top"] and w2["top"] - w1["top"] <= 12) and abs(w2["x0"] - w1["x0"]) <= 15
                                    if on_same_line or on_next_line:
                                        code_bbox = {
                                            "x0": min(w1["x0"], w2["x0"]),
                                            "x1": max(w1["x1"], w2["x1"]),
                                            "top": min(w1["top"], w2["top"]),
                                            "bottom": max(w1["bottom"], w2["bottom"])
                                        }
                                        break
                            if code_bbox:
                                break
                                
                    # 4. Tax Year
                    tax_year = 2025
                    year_match = re.search(r"Form\s*1042-S\s*\(?(\d{4})\)?", text, re.IGNORECASE)
                    if year_match:
                        tax_year = int(year_match.group(1))
                    else:
                        for w in words:
                            if w["top"] < 150 and re.match(r"^\d{4}$", w["text"]):
                                val = int(w["text"])
                                if 2020 <= val <= 2030:
                                    tax_year = val
                                    break
                                    
                    # Resolve values using find_best_value_for_label
                    gross_income_usd = 0.0
                    if gross_label_bbox:
                        w_val = self._find_best_value_for_label(gross_label_bbox, candidate_words, direction="below")
                        if w_val:
                            gross_income_usd = float(w_val["text"].replace("..", ".").replace(",", ""))
                            
                    withholding_tax_usd = 0.0
                    if withheld_bbox:
                        w_val = self._find_best_value_for_label(withheld_bbox, candidate_words, direction="right")
                        if w_val:
                            withholding_tax_usd = float(w_val["text"].replace("..", ".").replace(",", ""))
                            
                    income_code = "06"
                    if code_bbox:
                        w_val = self._find_best_value_for_label(code_bbox, candidate_words, direction="below")
                        if w_val:
                            income_code = w_val["text"].strip().zfill(2)
                            
                    # Build record
                    parsed = {
                        "income_code": income_code,
                        "gross_income_usd": gross_income_usd,
                        "withholding_tax_usd": withholding_tax_usd,
                        "tax_year": tax_year,
                        "payment_date": None
                    }
                    
                    rec = (
                        income_code,
                        gross_income_usd,
                        withholding_tax_usd,
                        tax_year
                    )
                    
                    # Deduplicate
                    if rec[1] > 0 or rec[2] > 0:
                        if rec not in seen:
                            seen.add(rec)
                            unique_forms.append(parsed)
                            logger.info(f"Parsed Form 1042-S page {page_num+1}: Code={income_code}, Gross=${gross_income_usd:.2f}, Tax=${withholding_tax_usd:.2f}")
                            
        except Exception as e:
            logger.error(f"pdfplumber coordinate 1042-S parser failed: {e}")
            
        return unique_forms

    def parse_vda_csv(self, csv_content: str) -> list:
        """
        Parses Virtual Digital Assets (VDA) / Cryptocurrency trades CSV.
        Expected columns:
        - Symbol/Asset/Token: name of crypto (BTC, ETH, etc.)
        - Acquisition Date / Buy Date: date of purchase
        - Transfer Date / Sell Date: date of sale
        - Cost / Purchase Price / Buy Price: cost of acquisition in INR
        - Proceeds / Sell Price / Consideration: consideration received in INR
        """
        records = []
        normalized_content = csv_content.replace('\r\n', '\n').replace('\r', '\n')
        f = io.StringIO(normalized_content.strip())
        reader = csv.reader(f)
        rows = list(reader)
        if not rows:
            return []
            
        header_row_idx = -1
        headers = []
        
        # Scan for header row
        for idx, row in enumerate(rows):
            row_headers = [str(cell).strip().lower() for cell in row]
            
            def has_match(names):
                return any(any(name in cell for name in names) for cell in row_headers)
                
            has_buy_dt = has_match(["buy date", "acquisition", "purchase date", "acquired"])
            has_sell_dt = has_match(["sell date", "transfer", "sale date", "sold"])
            has_cost = has_match(["cost", "buy price", "purchase price", "acquisition cost"])
            has_proceeds = has_match(["proceeds", "sell price", "consideration", "sale value"])
            
            if (has_buy_dt or has_sell_dt) and (has_cost or has_proceeds):
                header_row_idx = idx
                headers = row_headers
                break
                
        if header_row_idx == -1:
            for idx, row in enumerate(rows):
                if any(row):
                    header_row_idx = idx
                    headers = [str(cell).strip().lower() for cell in row]
                    break
                    
        # Find index for each column
        sym_idx = -1
        buy_date_idx = -1
        sell_date_idx = -1
        cost_idx = -1
        proceeds_idx = -1
        
        for idx, h in enumerate(headers):
            if any(x in h for x in ["symbol", "asset", "token", "coin", "currency", "name"]):
                sym_idx = idx
            elif any(x in h for x in ["buy date", "acquisition", "purchase date", "acquired"]):
                buy_date_idx = idx
            elif any(x in h for x in ["sell date", "transfer", "sale date", "sold"]):
                sell_date_idx = idx
            elif any(x in h for x in ["cost", "purchase price", "buy price", "acquisition cost"]):
                cost_idx = idx
            elif any(x in h for x in ["proceeds", "sell price", "consideration", "sale value", "amount", "value"]):
                proceeds_idx = idx
                
        # Fallback indexes
        if buy_date_idx == -1:
            if len(headers) >= 4:
                buy_date_idx = 1
        if sell_date_idx == -1:
            if len(headers) >= 4:
                sell_date_idx = 2
        if cost_idx == -1:
            if len(headers) >= 4:
                cost_idx = 3
        if proceeds_idx == -1:
            if len(headers) >= 5:
                proceeds_idx = 4
                
        # Parse data rows
        for row in rows[header_row_idx + 1:]:
            if not row or len(row) < max(buy_date_idx, sell_date_idx, cost_idx, proceeds_idx) + 1:
                continue
            row_str = " ".join([str(c) for c in row]).lower()
            if "total" in row_str and len(row_str) < 50:
                continue
                
            try:
                symbol = row[sym_idx].strip().upper() if sym_idx != -1 else "VDA"
                buy_date_str = row[buy_date_idx].strip()
                sell_date_str = row[sell_date_idx].strip()
                
                def parse_date(d_str):
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                        try:
                            return datetime.strptime(d_str, fmt).date()
                        except ValueError:
                            continue
                    try:
                        return parser.parse(d_str).date()
                    except Exception:
                        raise ValueError(f"Unable to parse VDA date: {d_str}")
                        
                buy_date = parse_date(buy_date_str)
                sell_date = parse_date(sell_date_str)
                
                cost_val = float(re.sub(r"[^\d\.\-]", "", row[cost_idx]))
                proceeds_val = float(re.sub(r"[^\d\.\-]", "", row[proceeds_idx]))
                
                # Check if cost/proceeds are in USD
                is_usd = any("$" in row[cost_idx] or "$" in row[proceeds_idx] or "usd" in h for h in headers)
                if is_usd:
                    buy_rate = self.rate_resolver.resolve_rule_115_rate(buy_date)
                    sell_rate = self.rate_resolver.resolve_rule_115_rate(sell_date)
                    cost_inr = cost_val * buy_rate
                    proceeds_inr = proceeds_val * sell_rate
                else:
                    cost_inr = cost_val
                    proceeds_inr = proceeds_val
                    
                records.append({
                    "symbol": symbol,
                    "buy_date": buy_date.isoformat() if hasattr(buy_date, "isoformat") else buy_date,
                    "sell_date": sell_date.isoformat() if hasattr(sell_date, "isoformat") else sell_date,
                    "cost_usd": cost_val if is_usd else 0.0,
                    "proceeds_usd": proceeds_val if is_usd else 0.0,
                    "cost_inr": cost_inr,
                    "proceeds_inr": proceeds_inr,
                    "gain_inr": max(0.0, proceeds_inr - cost_inr)
                })
            except Exception as e:
                logger.warning(f"Failed to parse VDA row {row}: {e}")
                continue
                
        return records
