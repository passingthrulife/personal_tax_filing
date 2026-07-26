import os
import csv
import urllib.request
import io

currencies = [
    "AED", "AUD", "BDT", "BHD", "CAD", "CHF", "CNY", "DKK", "EUR", "GBP",
    "HKD", "IDR", "JPY", "KES", "KRW", "KWD", "LKR", "MYR", "NOK", "NZD",
    "OMR", "PKR", "QAR", "RUB", "SAR", "SEK", "SGD", "THB", "TRY", "USD", "ZAR"
]

base_url = "https://raw.githubusercontent.com/sahilgupta/sbi-fx-ratekeeper/main/csv_files/"
local_dir = "/Users/Karthik/Documents/Projects/personal_tax_filing/csv_files"

def sync_currency(currency):
    filename = f"SBI_REFERENCE_RATES_{currency}.csv"
    local_path = os.path.join(local_dir, filename)
    remote_url = base_url + filename
    
    # 1. Load local rows
    local_data = {}
    fieldnames = []
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get("DATE"):
                    local_data[row["DATE"]] = row
                    
    # 2. Fetch remote rows
    try:
        req = urllib.request.Request(
            remote_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            remote_csv = response.read().decode('utf-8')
            
        reader = csv.DictReader(io.StringIO(remote_csv))
        if not fieldnames and reader.fieldnames:
            fieldnames = reader.fieldnames
            
        remote_count = 0
        added_count = 0
        for row in reader:
            date_val = row.get("DATE")
            if date_val:
                remote_count += 1
                if date_val not in local_data:
                    local_data[date_val] = row
                    added_count += 1
                else:
                    # Update/overwrite with remote values to ensure correctness
                    local_data[date_val] = row
                    
        print(f"{currency}: Remote had {remote_count} rows. Added/updated {added_count} new entries locally.")
    except Exception as e:
        print(f"Error syncing {currency}: {e}")
        return
        
    # 3. Write back sorted by DATE
    if not fieldnames:
        fieldnames = ["DATE", "PDF FILE", "TT BUY", "TT SELL", "BILL BUY", "BILL SELL", "FOREX TRAVEL CARD BUY", "FOREX TRAVEL CARD SELL", "CN BUY", "CN SELL"]
        
    sorted_dates = sorted(local_data.keys())
    os.makedirs(local_dir, exist_ok=True)
    with open(local_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for date_val in sorted_dates:
            writer.writerow(local_data[date_val])

def main():
    print("Starting historical rates sync...")
    for curr in currencies:
        sync_currency(curr)
    print("Rates sync finished!")

if __name__ == "__main__":
    main()
