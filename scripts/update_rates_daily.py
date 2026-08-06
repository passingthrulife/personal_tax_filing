import os
import re
import csv
import urllib.request
import io
from datetime import datetime

# Import pypdf or PyPDF2 to parse PDF text
try:
    import pypdf
except ImportError:
    try:
        import PyPDF2 as pypdf
    except ImportError:
        pypdf = None

currencies = [
    "AED", "AUD", "BDT", "BHD", "CAD", "CHF", "CNY", "DKK", "EUR", "GBP",
    "HKD", "IDR", "JPY", "KES", "KRW", "KWD", "LKR", "MYR", "NOK", "NZD",
    "OMR", "PKR", "QAR", "RUB", "SAR", "SEK", "SGD", "THB", "TRY", "USD", "ZAR"
]

SBI_PDF_URLS = [
    "https://sbi.bank.in/documents/16012/1400784/FOREX_CARD_RATES.pdf",
    "https://bank.sbi/documents/16012/1400784/FOREX_CARD_RATES.pdf"
]

LOCAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "csv_files")
COMMUNITY_BASE_URL = "https://raw.githubusercontent.com/sahilgupta/sbi-fx-ratekeeper/main/csv_files/"

def download_sbi_pdf():
    """Downloads the SBI PDF file and returns its bytes, or None if failed."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    for url in SBI_PDF_URLS:
        if not url.lower().startswith(('http://', 'https://')):
            raise ValueError(f"Forbidden URL scheme: {url}")
        try:
            print(f"Attempting to download daily PDF from: {url}")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except Exception as e:
            print(f"Failed to download from {url}: {e}")
    return None

def parse_sbi_pdf(pdf_bytes):
    """Parses text from PDF bytes and returns dict of rates and date/time."""
    if pypdf is None:
        print("pypdf library not installed. Cannot parse PDF directly.")
        return None
        
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        
        if not text.strip():
            print("Extracted text is empty. PDF might be scanned (image-based).")
            return None
            
        # Parse date and time (making colon optional and allowing AM/PM time)
        date_match = re.search(r"date\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})", text, re.IGNORECASE)
        time_match = re.search(r"time\s*:?\s*(\d+:\d{2}(?::\d{2})?\s*[AP]M|\d{2}:\d{2}(?::\d{2})?)", text, re.IGNORECASE)
        
        if not date_match or not time_match:
            print("Could not find Date or Time headers in PDF text.")
            return None
            
        date_str = date_match.group(1).replace("-", "/")  # normalize to DD/MM/YYYY
        time_str = time_match.group(1)
        dt_str = f"{date_str} {time_str}"
        
        # Parse to datetime object
        parsed_dt = None
        for fmt in ["%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M:%S %p"]:
            try:
                parsed_dt = datetime.strptime(dt_str, fmt)
                break
            except ValueError:
                continue
                
        if not parsed_dt:
            print(f"Failed to parse datetime from '{dt_str}'")
            return None
                
        formatted_date = parsed_dt.strftime("%Y-%m-%d %H:%M")
        print(f"Successfully parsed PDF date/time: {formatted_date}")
        
        # Parse currency rates
        # Look for currency code like USD followed by "/INR" and 8 rate values
        currency_rates = {}
        for curr in currencies:
            pattern = re.compile(rf"{curr}\s*/\s*INR\s+(" + r"\s+".join([r"\d+(?:\.\d+)?"] * 8) + r")", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                vals = re.split(r"\s+", match.group(1).strip())
                if len(vals) == 8:
                    currency_rates[curr] = vals
                    
        if "USD" not in currency_rates:
            print("Failed to find USD/INR rates in PDF text.")
            return None
            
        return {
            "date": formatted_date,
            "rates": currency_rates
        }
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return None

def update_local_csv(currency, date_str, rate_values, pdf_url="https://sbi.bank.in/documents/16012/1400784/FOREX_CARD_RATES.pdf"):
    """Appends or updates a rate entry in the local CSV file."""
    filename = f"SBI_REFERENCE_RATES_{currency}.csv"
    filepath = os.path.join(LOCAL_DIR, filename)
    
    local_data = {}
    fieldnames = ["DATE", "PDF FILE", "TT BUY", "TT SELL", "BILL BUY", "BILL SELL", "FOREX TRAVEL CARD BUY", "FOREX TRAVEL CARD SELL", "CN BUY", "CN SELL"]
    
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or fieldnames
            for row in reader:
                if row.get("DATE"):
                    local_data[row["DATE"]] = row
                    
    new_row = {
        "DATE": date_str,
        "PDF FILE": pdf_url
    }
    cols = ["TT BUY", "TT SELL", "BILL BUY", "BILL SELL", "FOREX TRAVEL CARD BUY", "FOREX TRAVEL CARD SELL", "CN BUY", "CN SELL"]
    for i, col in enumerate(cols):
        new_row[col] = rate_values[i]
        
    local_data[date_str] = new_row
    
    sorted_dates = sorted(local_data.keys())
    os.makedirs(LOCAL_DIR, exist_ok=True)
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for dt in sorted_dates:
            writer.writerow(local_data[dt])
    print(f"Updated {currency} CSV with entry for {date_str}")

def fallback_sync_from_community():
    """Tries to download the latest rates from the community archive repository."""
    print("PDF parsing unavailable or failed. Falling back to community archive sync...")
    for curr in currencies:
        filename = f"SBI_REFERENCE_RATES_{curr}.csv"
        remote_url = COMMUNITY_BASE_URL + filename
        local_path = os.path.join(LOCAL_DIR, filename)
        
        local_dates = set()
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("DATE"):
                        local_dates.add(row["DATE"])
                        
        if not remote_url.lower().startswith(('http://', 'https://')):
            raise ValueError(f"Forbidden URL scheme: {remote_url}")
        try:
            req = urllib.request.Request(remote_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                remote_csv = response.read().decode('utf-8')
                
            reader = csv.DictReader(io.StringIO(remote_csv))
            added = 0
            rows_to_append = []
            for row in reader:
                dt = row.get("DATE")
                if dt and dt not in local_dates:
                    rows_to_append.append(row)
                    added += 1
                    
            if rows_to_append:
                local_rows = {}
                if os.path.exists(local_path):
                    with open(local_path, "r", encoding="utf-8") as f:
                        r_reader = csv.DictReader(f)
                        for r_row in r_reader:
                            if r_row.get("DATE"):
                                local_rows[r_row["DATE"]] = r_row
                for r_row in rows_to_append:
                    local_rows[r_row["DATE"]] = r_row
                    
                sorted_dts = sorted(local_rows.keys())
                fieldnames = reader.fieldnames or ["DATE", "PDF FILE", "TT BUY", "TT SELL", "BILL BUY", "BILL SELL", "FOREX TRAVEL CARD BUY", "FOREX TRAVEL CARD SELL", "CN BUY", "CN SELL"]
                with open(local_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for dt in sorted_dts:
                        writer.writerow(local_rows[dt])
                        
            print(f"{curr}: Synced {added} new rates from community fallback.")
        except Exception as e:
            print(f"Failed to sync {curr} from community fallback: {e}")

def save_pdf_file(pdf_bytes, date_str):
    """Saves the PDF bytes to the pdf_files/YYYY/MM/YYYY-MM-DD.pdf structure."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        year = str(dt.year)
        month = str(dt.month)
        day_str = dt.strftime("%Y-%m-%d")
        
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_dir = os.path.join(script_dir, "pdf_files", year, month)
        os.makedirs(pdf_dir, exist_ok=True)
        
        pdf_filename = f"{day_str}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
            
        print(f"Saved raw PDF file to: {pdf_path}")
        return f"pdf_files/{year}/{month}/{pdf_filename}"
    except Exception as e:
        print(f"Error saving PDF file: {e}")
        return None

def main():
    print("Starting daily rates update...")
    pdf_bytes = download_sbi_pdf()
    parsed_data = None
    if pdf_bytes:
        parsed_data = parse_sbi_pdf(pdf_bytes)
        
    if parsed_data:
        date_str = parsed_data["date"]
        rates = parsed_data["rates"]
        print(f"PDF parsed successfully for date {date_str}. Updating local CSV files...")
        
        # Save raw PDF file and get the reference path
        saved_pdf_path = save_pdf_file(pdf_bytes, date_str)
        pdf_ref = saved_pdf_path if saved_pdf_path else "https://sbi.bank.in/documents/16012/1400784/FOREX_CARD_RATES.pdf"
        
        for curr in currencies:
            if curr in rates:
                update_local_csv(curr, date_str, rates[curr], pdf_url=pdf_ref)
            else:
                print(f"Currency {curr} missing from PDF card. Syncing from community fallback...")
                fallback_sync_from_community()
    else:
        print("Could not download or parse daily PDF.")
        fallback_sync_from_community()
        
    print("Daily rates update complete!")

if __name__ == "__main__":
    main()
