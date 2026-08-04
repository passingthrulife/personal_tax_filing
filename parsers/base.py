import os
import io
import re
import pypdf
import logging
import anthropic
from rate_resolver import RateResolver

logger = logging.getLogger(__name__)

class BaseParser:
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
            reader = pypdf.PdfReader(input_pdf, strict=False)
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
            writer = pypdf.PdfWriter()
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
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes), strict=False)
            text_parts = []
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n--- Page Separator ---\n".join(text_parts)
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            return ""

    def _parse_float_val(self, val_str: str) -> float:
        if not val_str:
            return 0.0
        val_str = val_str.replace(",", "").replace("₹", "").strip()
        try:
            return float(val_str)
        except ValueError:
            return 0.0

    def classify_mf_asset_type(self, symbol: str) -> str:
        """Classifies mutual fund category based on its name keywords."""
        sym_lower = symbol.lower()
        if any(k in sym_lower for k in ["debt", "hybrid", "gold"]):
            return "other_mf"
        if any(k in sym_lower for k in ["conservative", "arbitrage", "liquid", "overnight", "money market", "specified"]):
            return "specified_mf"
        return "equity_mf"
