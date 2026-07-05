import os
import re
import csv
import json
import io
import logging
from datetime import datetime
import PyPDF2
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

        # Try to parse salary sections
        data["gross_salary_17_1"] = find_value(
            r"(?:Salary\s+as\s+per\s+provisions\s+contained\s+in|Salary|gross\s+salary)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(1\)[^\d\n]*([\d,]+\.?\d*)", 
            text
        )
        data["perquisites_17_2"] = find_value(
            r"(?:Value\s+of\s+perquisites|perquisites)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(2\)[^\d\n]*([\d,]+\.?\d*)", 
            text
        )
        data["profits_lieu_17_3"] = find_value(
            r"(?:Profits\s+in\s+lieu\s+of\s+salary|profits\s+in\s+lieu|profits\s+lieu)\s+(?:under|u/s|in)?\s*(?:section|sec\.?)?\s*17\(3\)[^\d\n]*([\d,]+\.?\d*)", 
            text
        )
        
        # Standard deductions
        data["standard_deduction_16_ia"] = find_value(
            r"Standard\s+deduction\s+(?:under|u/s)?\s*(?:section|sec\.?)?\s*16\(ia\)[^\d\n]*([\d,]+\.?\d*)", 
            text, 
            50000.0
        )
        data["professional_tax_16_ii"] = find_value(
            r"(?:Tax\s+on\s+employment|professional\s+tax)\s+(?:under|u/s)?\s*(?:section|sec\.?)?\s*16\(ii\)[^\d\n]*([\d,]+\.?\d*)", 
            text
        )

        # Allowances
        data["allowances_exempt_sec_10"] = find_value(
            r"(?:Total\s+amount\s+of\s+any\s+other\s+exemption|allowances\s+to\s+the\s+extent\s+exempt|exempt\s+allowances)\s+(?:under|u/s|sec\.?)?\s*10[^\d\n]*([\d,]+\.?\d*)", 
            text
        )
        
        # Home Loan Interest
        data["home_loan_interest_24b"] = find_value(
            r"(?:Interest\s+on\s+borrowed\s+capital|Income\s+or\s+loss\s+from\s+house\s+property|interest\s+on\s+housing\s+loan|interest\s+paid\s+on\s+home\s+loan)[^24]*24\(b\)?\s*[^\d\n\-]*\-?([\d,]+\.?\d*)", 
            text
        )
        
        # 80C, 80D
        data["deduction_80c"] = find_value(r"(?:Section|Sec\.?)\s*80C[^\d\n]*([\d,]+\.?\d*)", text)
        data["deduction_80d"] = find_value(r"(?:Section|Sec\.?)\s*80D[^\d\n]*([\d,]+\.?\d*)", text)
        data["deduction_80ccd_1b"] = find_value(r"(?:Section|Sec\.?)\s*80CCD\(1B\)[^\d\n]*([\d,]+\.?\d*)", text)
        
        # TDS Deducted
        data["tds_deducted"] = find_value(
            r"(?:Total\s+amount\s+of\s+tax\s+deducted|tax\s+deducted|tds\s+deducted)[^\d\n]*([\d,]+\.?\d*)", 
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
            "fd_interest": 0.0,
            "domestic_dividends": 0.0,
            "taxable_epf_interest": 0.0,
            "salary_gross_ais": 0.0,
            "purchase_of_securities": 0.0,
            "sale_of_securities": 0.0,
            "advance_tax_paid": 0.0
        }

        # Match blocks containing keywords and sum them
        # Let's look for sections like "Interest from savings bank" or "Interest on deposit"
        # Since TIS is a summary, it has blocks like:
        # "Interest from savings bank" followed by amount
        def find_sum_for_keyword(keywords, text):
            total = 0.0
            for line in text.split("\n"):
                if any(kw.lower() in line.lower() for kw in keywords):
                    # Find a number at the end of the line or nearby
                    nums = re.findall(r"([\d,]+\.\d+|[\d,]+)", line)
                    for n in nums:
                        val = float(n.replace(",", ""))
                        if val > 100:  # heuristic to ignore small codes/IDs
                            total += val
                            break
            return total

        data["savings_interest"] = find_sum_for_keyword(["savings bank", "saving bank interest"], text)
        data["fd_interest"] = find_sum_for_keyword(["interest on deposit", "fixed deposit interest", "time deposit"], text)
        data["domestic_dividends"] = find_sum_for_keyword(["dividend", "dividend income"], text)
        data["taxable_epf_interest"] = find_sum_for_keyword(["taxable epf interest", "accumulated balance of epf"], text)
        data["salary_gross_ais"] = find_sum_for_keyword(["salary received", "salary income"], text)
        data["advance_tax_paid"] = find_sum_for_keyword(["advance tax", "payment of taxes", "payment of tax"], text)

        return data

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
            has_buy_dt = has_match(["buy date", "purchase date", "buy_date", "purchase_date", "acquired", "date acquired", "acq date", "dt_buy"])
            has_buy_val = has_match(["buy price", "purchase price", "cost basis", "buy_val", "cost", "total cost", "purchase value", "cost basis", "cost basis (usd)"])
            has_sell_dt = has_match(["sell date", "sale date", "sell_date", "sale_date", "sold", "date sold", "disposal date", "dt_sell"])
            has_sell_val = has_match(["sell price", "sale price", "proceeds", "gross proceeds", "total proceeds", "value sold", "sales proceeds", "proceeds (usd)"])
            
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
        buy_date_idx = get_col_idx(["date acquired", "acquired", "acq date", "buy date", "purchase date", "buy_date", "purchase_date", "dt_buy"])
        buy_price_idx = get_col_idx(["cost basis (usd)", "cost basis", "cost", "total cost", "purchase price", "buy price", "buy_price", "purchase_price", "purchase value"])
        sell_date_idx = get_col_idx(["date sold", "sold", "sell date", "sale date", "sell_date", "sale_date", "disposal date", "dt_sell"])
        sell_price_idx = get_col_idx(["proceeds (usd)", "proceeds", "gross proceeds", "total proceeds", "sell price", "sale price", "sell_price", "sale_price", "value sold", "sales proceeds"])

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
        buy_is_total = any(w in buy_header for w in ["basis", "total", "proceeds", "cost"]) and "price" not in buy_header
        sell_is_total = any(w in sell_header for w in ["proceeds", "total", "basis"]) and "price" not in sell_header

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
                    
                qty = float(row[qty_idx].replace(",", ""))
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

                raw_buy_val = float(row[buy_price_idx].replace(",", "").replace("$", ""))
                raw_sell_val = float(row[sell_price_idx].replace(",", "").replace("$", ""))

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
        Expected columns: Date (YYYY-MM-DD), Amount (USD), Withholding Tax (USD) (optional)
        """
        records = []
        f = io.StringIO(csv_content.strip())
        reader = csv.reader(f)
        try:
            headers = [h.strip().lower() for h in next(reader)]
        except StopIteration:
            return []

        def get_col_idx(names):
            for name in names:
                for idx, h in enumerate(headers):
                    if name in h:
                        return idx
            return -1

        date_idx = get_col_idx(["date", "payment date", "dt"])
        amt_idx = get_col_idx(["amount", "dividend", "gross", "usd"])
        tax_idx = get_col_idx(["tax", "withholding", "withheld", "federal tax"])

        if date_idx == -1 or amt_idx == -1:
            raise ValueError(f"Missing required columns (Date, Amount) in US Dividends CSV. Headers: {headers}")

        for row in reader:
            if not row:
                continue
            try:
                date_str = row[date_idx].strip()
                def parse_date(d_str):
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                        try:
                            return datetime.strptime(d_str, fmt).date()
                        except ValueError:
                            continue
                    raise ValueError(f"Unable to parse date string: {d_str}")

                div_date = parse_date(date_str)
                amount_usd = float(row[amt_idx].replace(",", "").replace("$", ""))
                
                withholding_usd = 0.0
                if tax_idx != -1 and len(row) > tax_idx:
                    withholding_usd = float(row[tax_idx].replace(",", "").replace("$", ""))

                # Apply Rule 115 exchange rate conversion
                rate = self.rate_resolver.resolve_rule_115_rate(div_date)
                amount_inr = amount_usd * rate
                withholding_inr = withholding_usd * rate

                records.append({
                    "date": div_date,
                    "amount_usd": amount_usd,
                    "amount_inr": amount_inr,
                    "withholding_usd": withholding_usd,
                    "withholding_inr": withholding_inr,
                    "rate_used": rate
                })
            except Exception as e:
                logger.warning(f"Failed to parse dividend row {row}: {e}")
                continue

        return records

    def parse_1042s(self, pdf_bytes: bytes) -> dict:
        """
        Parses Form 1042-S PDF to extract:
        - Income Code (Box 1) - "06" for dividends, "01"/"29"/"30" for interest.
        - Gross Income (Box 2) in USD.
        - Federal Tax Withheld (Box 7) in USD.
        - Tax Year (e.g. 2025)
        - Payment Date (if any)
        """
        raw_text = self.extract_text_from_pdf(pdf_bytes)
        
        if self.anthropic_client:
            try:
                return self._parse_1042s_with_claude(raw_text)
            except Exception as e:
                logger.error(f"Claude 1042-S parsing failed, falling back to regex: {e}")

        return self._parse_1042s_with_regex(raw_text)

    def _parse_1042s_with_claude(self, text: str) -> dict:
        """Uses Claude to parse IRS 1042-S PDF text into structured JSON."""
        prompt = f"""
Analyze the text of this IRS Form 1042-S (Foreign Person's U.S. Source Income Subject to Withholding).
Extract the key fields. 
Return ONLY a valid JSON object matching the following keys. Do not include markdown wraps (like ```json), commentary, or other characters.

Required Keys:
- "income_code": (string, Box 1, e.g. "06" for dividends, "01" for interest)
- "gross_income_usd": (float, Box 2)
- "withholding_tax_usd": (float, Box 7, Federal tax withheld)
- "tax_year": (integer, e.g. 2025, from header or Box 24)
- "payment_date": (string or null, if a specific payment date is mentioned in format YYYY-MM-DD, otherwise null)

Form 1042-S text:
{text}
"""
        response = self.anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
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

    def _parse_1042s_with_regex(self, text: str) -> dict:
        """Regex-based fallback parser for IRS 1042-S text."""
        data = {
            "income_code": "06", # Default to dividend
            "gross_income_usd": 0.0,
            "withholding_tax_usd": 0.0,
            "tax_year": 2025, # Default to current tax year
            "payment_date": None
        }

        # Regex for Box 1 (Income code)
        code_match = re.search(r"(?:1\s*Income\s*code|Income\s*code\b)[^\d]*(\d+)", text, re.IGNORECASE)
        if code_match:
            data["income_code"] = code_match.group(1).zfill(2)

        # Regex for Box 2 (Gross income)
        gross_match = re.search(r"(?:2\s*Gross\s*income|Gross\s*income\b)[^\d]*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if gross_match:
            data["gross_income_usd"] = float(gross_match.group(1).replace(",", ""))

        # Regex for Box 7 (Federal tax withheld)
        tax_match = re.search(r"(?:7\s*Federal\s*tax\s*withheld|Federal\s*tax\s*withheld\b|tax\s*withheld\b)[^\d]*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if tax_match:
            data["withholding_tax_usd"] = float(tax_match.group(1).replace(",", ""))

        # Regex for Tax Year (e.g. 2024, 2025)
        year_match = re.search(r"Form\s*1042-S\s*\((\d{4})\)", text, re.IGNORECASE)
        if year_match:
            data["tax_year"] = int(year_match.group(1))
        else:
            # Fallback to look for general 4-digit years in headers
            years = re.findall(r"\b(202\d)\b", text)
            if years:
                data["tax_year"] = int(years[0])

        # Regex for specific date (if any)
        date_match = re.search(r"\b(202\d-\d{2}-\d{2})\b", text)
        if date_match:
            data["payment_date"] = date_match.group(1)

        return data
