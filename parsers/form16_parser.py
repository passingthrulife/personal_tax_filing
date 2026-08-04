import re
import json
import logging

logger = logging.getLogger(__name__)

class Form16ParserMixin:
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
            "standard_deduction_16_ia": 50000.0,
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
        
        gross_block_match = re.search(r"Gross\s+Salary.*?(?:Total|Salary\s+received\s+from\s+current\s+employer)", text, re.DOTALL | re.IGNORECASE)
        if gross_block_match:
            block = gross_block_match.group(0)
            logger.info("Found Gross Salary block for Form 16 parsing.")
            
            val_17_1 = find_value(r"17\(1\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_1 is None:
                val_17_1 = find_value(r"\(a\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            gross_salary_17_1 = val_17_1
            
            val_17_2 = find_value(r"17\(2\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_2 is None:
                val_17_2 = find_value(r"\(b\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            perquisites_17_2 = val_17_2
            
            val_17_3 = find_value(r"17\(3\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=None)
            if val_17_3 is None:
                val_17_3 = find_value(r"\(c\)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", block, default=0.0)
            profits_lieu_17_3 = val_17_3
        else:
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
        std_ded = 50000.0
        prof_tax = 0.0
        
        ded_block_match = re.search(r"Deductions\s+under\s+section\s+16.*?(?:Income\s+chargeable\s+under\s+the\s+head|Gross\s+total\s+income)", text, re.DOTALL | re.IGNORECASE)
        if ded_block_match:
            block = ded_block_match.group(0)
            logger.info("Found Deductions block for Form 16 parsing.")
            
            std_match = re.findall(r"\b(75000|50000)(?:\.00)?\b", block)
            if std_match:
                std_ded = float(std_match[0])
            else:
                val = find_value(r"Standard\s+deduction.*?16\(ia\)[^\d\n]*([\d,]+(?:\.\d{2})?)", block)
                if val > 0:
                    std_ded = val
                    
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
        
        # Deductions
        data["deduction_80c"] = find_value(r"(?:Section|Sec\.?)\s*80C.*?([\d,]+(?:\.\d{2})?)", text)
        data["deduction_80d"] = find_value(r"(?:Section|Sec\.?)\s*80D.*?([\d,]+(?:\.\d{2})?)", text)
        data["deduction_80ccd_1b"] = find_value(r"(?:Section|Sec\.?)\s*80CCD\(1B\).*?([\d,]+(?:\.\d{2})?)", text)
        
        # TDS Deducted
        data["tds_deducted"] = find_value(
            r"(?:Tax\s+Deducted\s+from\s+Salary\s+of\s+Employee\s+u/s\s+192\(1\)|Total\s+tax\s+paid|Total\s+amount\s+of\s+tax\s+deducted\s+at\s+source|tax\s+deducted\s+by\s+employer)[\s\S]*?(\b[\d,]+(?:\.\d{2})?\b)", 
            text
        )

        return data
