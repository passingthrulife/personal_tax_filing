import os
import json
from datetime import datetime, date
import logging
from flask import Flask, request, jsonify, render_template
from rate_resolver import RateResolver
from parser import DocumentParser
from calculator import TaxCalculator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize dependencies
rate_resolver = RateResolver()
doc_parser = DocumentParser(rate_resolver=rate_resolver)
tax_calculator = TaxCalculator()

BASE_DIR = "/Users/Karthik/Documents/Karthik Personal/Taxes/Tax AY 2026-27"

@app.route("/")
def index():
    # Renders the single-page HTML template from the local templates folder
    try:
        return render_template("index.html")
    except Exception as e:
        logger.error(f"Failed to load frontend template: {e}")
        return f"<h1>Error loading UI dashboard: {e}</h1>", 500

@app.route("/api/process", methods=["POST"])
def process_tax():
    # Read text fields from form-data
    pan = request.form.get("pan", "").strip()
    dob = request.form.get("dob", "").strip()  # Format: DDMMYYYY
    form16_password = request.form.get("form16_password", "").strip()
    fy = request.form.get("fy", "2025-26")
    
    # Override settings
    home_loan_interest_override = request.form.get("home_loan_interest", None)
    if home_loan_interest_override == "":
        home_loan_interest_override = None
    elif home_loan_interest_override is not None:
        home_loan_interest_override = float(home_loan_interest_override)

    home_loan_principal_override = float(request.form.get("home_loan_principal", 0.0) or 0.0)
    custom_80c = float(request.form.get("custom_80c", 0.0) or 0.0)
    custom_80d = float(request.form.get("custom_80d", 0.0) or 0.0)
    custom_80ccd_1b = float(request.form.get("custom_80ccd_1b", 0.0) or 0.0)
    
    advance_tax_override = request.form.get("advance_tax", None)
    if advance_tax_override == "":
        advance_tax_override = None
    elif advance_tax_override is not None:
        advance_tax_override = float(advance_tax_override)

    # Set active financial year
    tax_calculator.set_fy(fy)

    # Retrieve uploaded files
    form16_file = request.files.get("form16")
    ais_tis_file = request.files.get("ais_tis")
    indian_stock_files = request.files.getlist("indian_stock")
    us_stock_files = request.files.getlist("us_stock")
    mutual_funds_files = request.files.getlist("mutual_funds")
    us_dividends_files = request.files.getlist("us_dividends_csv")
    us_1042s_files = request.files.getlist("us_1042s")

    # Validation: US dividends input is mandatory
    if not us_dividends_files or not any(f.filename for f in us_dividends_files):
        return jsonify({
            "success": False,
            "error": "US Dividends statement file is mandatory. Please upload your Charles Schwab statement (CSV or Excel)."
        }), 400

    parsed_data = {
        "form16": {},
        "ais": {},
        "stock_sales": [],
        "us_dividends": [],
        "us_dividends_1042s": [],
        "us_interest": [],
        "pan": pan.upper()
    }
    
    warnings = []

    # 1. Parse Form 16
    if form16_file and form16_file.filename:
        try:
            form16_pdf = form16_file.read()
            pw_list = [form16_password] if form16_password else []
            if pan:
                pw_list.extend([pan.upper(), pan.lower()])
            pw = pw_list[0] if pw_list else None
            
            parsed_data["form16"] = doc_parser.parse_form16(form16_pdf, pw)
            logger.info("Successfully parsed Form 16.")
        except Exception as e:
            logger.error(f"Error parsing Form 16: {e}")
            warnings.append(f"Failed to decrypt/parse Form 16 PDF. Ensure password/PAN is correct. Details: {e}")

    # 2. Parse AIS or TIS (CSV list and/or PDF merge)
    ais_csv_data = {}
    ais_pdf_data = {}

    ais_files = request.files.getlist("ais_files")
    if ais_files and any(f.filename for f in ais_files):
        try:
            csv_contents = []
            for f in ais_files:
                if f and f.filename:
                    csv_contents.append(f.read().decode('utf-8'))
            if csv_contents:
                ais_csv_data = doc_parser.parse_ais_csv_list(csv_contents)
                logger.info(f"Successfully parsed {len(csv_contents)} uploaded AIS CSV files.")
        except Exception as e:
            logger.error(f"Error parsing AIS CSVs: {e}")
            warnings.append(f"Failed to parse uploaded AIS CSV files. Details: {e}")

    ais_tis_file = request.files.get("ais_tis")
    if ais_tis_file and ais_tis_file.filename:
        try:
            ais_tis_pdf = ais_tis_file.read()
            pw_list = []
            if pan and dob:
                pw_list.append(f"{pan.lower()}{dob}")
                pw_list.append(f"{pan.upper()}{dob}")
            pw = pw_list[0] if pw_list else None
            
            ais_pdf_data = doc_parser.parse_ais_tis(ais_tis_pdf, pw)
            logger.info("Successfully parsed AIS/TIS PDF.")
        except Exception as e:
            logger.error(f"Error parsing AIS/TIS PDF: {e}")
            warnings.append(f"Failed to decrypt/parse AIS/TIS PDF. Ensure PAN and Date of Birth (DDMMYYYY) are correct. Details: {e}")

    # Merge the parsed data from both sources (CSV and PDF)
    if ais_csv_data and ais_pdf_data:
        merged_ais = {}
        all_keys = set(list(ais_csv_data.keys()) + list(ais_pdf_data.keys()))
        detail_keys = ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details", "tds_on_deposit_interest_details"]
        
        for key in all_keys:
            if key in detail_keys:
                list_csv = ais_csv_data.get(key) or []
                list_pdf = ais_pdf_data.get(key) or []
                seen = set()
                merged_list = []
                for item in (list_csv + list_pdf):
                    src = item.get("source", "")
                    if "(" in src:
                        src = src.split("(")[0].strip()
                    acc = item.get("account", "")
                    amt = round(float(item.get("amount", 0.0) or 0.0), 2)
                    uniq_key = (src.lower(), acc.lower(), amt)
                    if uniq_key not in seen and amt > 0:
                        seen.add(uniq_key)
                        item["source"] = src
                        merged_list.append(item)
                merged_ais[key] = merged_list
            else:
                val_csv = float(ais_csv_data.get(key, 0.0) or 0.0)
                val_pdf = float(ais_pdf_data.get(key, 0.0) or 0.0)
                merged_ais[key] = max(val_csv, val_pdf)
        parsed_data["ais"] = merged_ais
        logger.info("Successfully merged AIS data from both CSV and PDF files.")
    elif ais_csv_data:
        for key in ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details", "tds_on_deposit_interest_details"]:
            if key in ais_csv_data:
                for item in ais_csv_data[key]:
                    if "(" in item.get("source", ""):
                        item["source"] = item["source"].split("(")[0].strip()
        parsed_data["ais"] = ais_csv_data
    elif ais_pdf_data:
        for key in ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details", "tds_on_deposit_interest_details"]:
            if key in ais_pdf_data:
                for item in ais_pdf_data[key]:
                    if "(" in item.get("source", ""):
                        item["source"] = item["source"].split("(")[0].strip()
        parsed_data["ais"] = ais_pdf_data

    # 3. Parse Stock Sales
    # 3.1 Indian Stock Sales (multiple files: CSV, Excel, PDF)
    if indian_stock_files:
        for f in indian_stock_files:
            if f and f.filename:
                try:
                    filename = f.filename.lower()
                    if filename.endswith(('.xlsx', '.xls')):
                        excel_bytes = f.read()
                        import io
                        import openpyxl
                        try:
                            wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), read_only=True)
                            is_zerodha = any(name.strip().lower().startswith("tradewise exits") for name in wb.sheetnames)
                        except Exception:
                            is_zerodha = False
                        
                        if is_zerodha:
                            records = doc_parser.parse_zerodha_excel(excel_bytes)
                        else:
                            records = doc_parser.parse_hdfc_sec_excel(excel_bytes)
                    elif filename.endswith('.pdf'):
                        pdf_bytes = f.read()
                        records = doc_parser.parse_indian_stock_pdf(pdf_bytes)
                    else:
                        csv_content = f.read().decode('utf-8')
                        records = doc_parser.parse_stock_sales_csv(csv_content, is_us=False)
                    
                    parsed_data["stock_sales"].extend(records)
                    logger.info(f"Parsed {len(records)} Indian stock sales from {f.filename}.")
                except Exception as e:
                    logger.error(f"Error parsing Indian stock sales file {f.filename}: {e}")
                    warnings.append(f"Error parsing Indian Stock Sales file '{f.filename}': {e}")

    # 3.2 Parse Mutual Funds Statement (multiple files: PDF)
    if mutual_funds_files:
        for f in mutual_funds_files:
            if f and f.filename:
                try:
                    filename = f.filename.lower()
                    if filename.endswith('.pdf'):
                        mf_bytes = f.read()
                        records = doc_parser.parse_mutual_funds_pdf(mf_bytes)
                    else:
                        records = []
                    
                    parsed_data["stock_sales"].extend(records)
                    logger.info(f"Parsed {len(records)} Mutual Fund transaction lots from {f.filename}.")
                except Exception as e:
                    logger.error(f"Error parsing Mutual Funds file {f.filename}: {e}")
                    warnings.append(f"Error parsing Mutual Funds file '{f.filename}': {e}")

    # 3.3 US Stock Sales (multiple files: CSV, Excel, PDF)
    if us_stock_files:
        for f in us_stock_files:
            if f and f.filename:
                try:
                    filename = f.filename.lower()
                    if filename.endswith(('.xlsx', '.xls')):
                        excel_bytes = f.read()
                        records = doc_parser.parse_us_stock_excel(excel_bytes)
                    elif filename.endswith('.pdf'):
                        pdf_bytes = f.read()
                        records = doc_parser.parse_us_stock_pdf(pdf_bytes)
                    else:
                        csv_content = f.read().decode('utf-8')
                        records = doc_parser.parse_stock_sales_csv(csv_content, is_us=True)
                    
                    parsed_data["stock_sales"].extend(records)
                    logger.info(f"Parsed {len(records)} US stock sales from {f.filename}.")
                except Exception as e:
                    logger.error(f"Error parsing US stock sales file {f.filename}: {e}")
                    warnings.append(f"Error parsing US Stock Sales file '{f.filename}': {e}")

    # 3.5 Parse US Dividends (multiple files: CSV, Excel)
    csv_divs = []
    if us_dividends_files:
        for f in us_dividends_files:
            if f and f.filename:
                try:
                    filename = f.filename.lower()
                    if filename.endswith(('.xlsx', '.xls')):
                        excel_bytes = f.read()
                        records = doc_parser.parse_us_dividends_excel(excel_bytes)
                    else:
                        csv_content = f.read().decode('utf-8')
                        records = doc_parser.parse_us_dividends_csv(csv_content)
                    
                    for r in records:
                        r["source"] = f.filename
                    csv_divs.extend(records)
                    logger.info(f"Parsed {len(records)} US dividends from {f.filename}.")
                except Exception as e:
                    logger.error(f"Error parsing US dividends file {f.filename}: {e}")
                    warnings.append(f"Error parsing US Dividends file '{f.filename}': {e}")

    # 4. Parse multiple Form 1042-S PDFs
    us_dividends_1042s = []
    if us_1042s_files:
        for f in us_1042s_files:
            if not f or not f.filename:
                continue
            try:
                logger.info(f"Parsing 1042-S file {f.filename}")
                f_bytes = f.read()
                parsed_list = doc_parser.parse_1042s(f_bytes)
                
                for parsed in parsed_list:
                    # Resolve date for Rule 115 TT Buying rate lookup
                    if parsed.get("payment_date"):
                        try:
                            txn_date = datetime.strptime(parsed["payment_date"], "%Y-%m-%d").date()
                        except Exception:
                            txn_date = date(int(parsed["tax_year"]), 12, 31)
                    else:
                        txn_date = date(int(parsed["tax_year"]), 12, 31)

                    rate = rate_resolver.resolve_rule_115_rate(txn_date)
                    gross_usd = float(parsed["gross_income_usd"])
                    withholding_usd = float(parsed["withholding_tax_usd"])
                    
                    record = {
                        "source": f.filename,
                        "date": txn_date.isoformat() if hasattr(txn_date, "isoformat") else txn_date,
                        "amount_usd": gross_usd,
                        "amount_inr": gross_usd * rate,
                        "withholding_usd": withholding_usd,
                        "withholding_inr": withholding_usd * rate,
                        "rate_used": rate,
                        "tax_year": parsed.get("tax_year", 2025),
                        "income_code": parsed.get("income_code", "06")
                    }
                    
                    code = str(parsed["income_code"]).strip().zfill(2)
                    if code in ["06", "52"]:
                        us_dividends_1042s.append(record)
                    elif code in ["01", "29", "30"]:
                        parsed_data["us_interest"].append(record)
                    else:
                        us_dividends_1042s.append(record)
            except Exception as e:
                logger.error(f"Error parsing 1042-S PDF: {e}")
                warnings.append(f"Failed to parse 1042-S PDF '{f.filename}': {e}")
                
    parsed_data["us_dividends_csv"] = csv_divs
    parsed_data["us_dividends_1042s"] = us_dividends_1042s
    
    # Reconciliation logic: The detailed CSV statement is the source of truth when uploaded.
    # We compare it against Form 1042-S with a $5.00 tolerance check.
    total_csv_usd = sum(r["amount_usd"] for r in csv_divs)
    total_1042s_usd = sum(r["amount_usd"] for r in us_dividends_1042s)
    
    # Pre-calculate December 31st reconciled 1042s for fallback use and fallback table display
    reconciled_1042s = []
    for r in us_dividends_1042s:
        tax_year = r.get("tax_year", 2025)
        dec_31 = date(int(tax_year), 12, 31)
        rate_dec_31 = rate_resolver.resolve_rule_115_rate(dec_31)
        
        gross_usd = r["amount_usd"]
        withholding_usd = r["withholding_usd"]
        
        reconciled_1042s.append({
            "source": r["source"],
            "date": dec_31.isoformat() if hasattr(dec_31, "isoformat") else dec_31,
            "amount_usd": gross_usd,
            "amount_inr": gross_usd * rate_dec_31,
            "withholding_usd": withholding_usd,
            "withholding_inr": withholding_usd * rate_dec_31,
            "rate_used": rate_dec_31,
            "is_reconciled_fallback": True
        })
        
    if csv_divs:
        parsed_data["us_dividends"] = csv_divs
        if us_dividends_1042s:
            # Check if they match within $5.00 tolerance
            parsed_data["us_dividends_match"] = abs(total_csv_usd - total_1042s_usd) <= 5.0
        else:
            parsed_data["us_dividends_match"] = True
    else:
        # Fallback to December 31st reconciled 1042-S if no CSV statement uploaded
        parsed_data["us_dividends"] = reconciled_1042s
        parsed_data["us_dividends_match"] = True
        
    # Save the reconciled 1042s in parsed_raw for the official 1042s table display
    parsed_data["us_dividends_1042s"] = reconciled_1042s

    # 5. Parse VDA/Crypto CSV and JSON manual entry
    vda_trades_file = request.files.get("vda_trades_csv")
    vda_trades_json = request.form.get("vda_trades_json")
    vda_trades = []
    
    if vda_trades_file and vda_trades_file.filename:
        try:
            vda_csv = vda_trades_file.read().decode('utf-8')
            records = doc_parser.parse_vda_csv(vda_csv)
            vda_trades.extend(records)
            logger.info(f"Parsed {len(records)} VDA trades from uploaded CSV.")
        except Exception as e:
            logger.error(f"Error parsing VDA trades CSV: {e}")
            warnings.append(f"Error parsing VDA Trades CSV: {e}")
            
    if vda_trades_json:
        try:
            manual_records = json.loads(vda_trades_json)
            for r in manual_records:
                cost = float(r.get("cost_inr", 0.0) or 0.0)
                proceeds = float(r.get("proceeds_inr", 0.0) or 0.0)
                r["gain_inr"] = max(0.0, proceeds - cost)
                vda_trades.append(r)
            logger.info(f"Loaded {len(manual_records)} manual VDA trades from request form.")
        except Exception as e:
            logger.error(f"Error parsing manual VDA JSON: {e}")
            
    parsed_data["vda_trades"] = vda_trades

    # 6. Parse Schedule AL JSON
    schedule_al_str = request.form.get("schedule_al")
    schedule_al = {}
    if schedule_al_str:
        try:
            schedule_al = json.loads(schedule_al_str)
            logger.info("Loaded Schedule AL data from request form.")
        except Exception as e:
            logger.error(f"Error parsing Schedule AL JSON: {e}")
    parsed_data["schedule_al"] = schedule_al

    # Extract HRA inputs
    hra_basic = float(request.form.get("hra_basic", 0.0) or 0.0)
    hra_received = float(request.form.get("hra_received", 0.0) or 0.0)
    hra_rent = float(request.form.get("hra_rent", 0.0) or 0.0)
    hra_metro = request.form.get("hra_metro", "false")
    
    parsed_data["hra_inputs"] = {
        "hra_basic": hra_basic,
        "hra_received": hra_received,
        "hra_rent": hra_rent,
        "hra_metro": hra_metro
    }

    if hra_basic > 0 or hra_received > 0 or hra_rent > 0:
        try:
            hra_path = os.path.join(BASE_DIR, "Karthik_HRA_Inputs.json")
            with open(hra_path, "w", encoding="utf-8") as f:
                json.dump(parsed_data["hra_inputs"], f, indent=2)
            logger.info("Successfully saved latest HRA inputs locally.")
        except Exception as e:
            logger.error(f"Error saving HRA inputs: {e}")

    # Parse Schedule FA JSON from request form
    schedule_fa_str = request.form.get("schedule_fa")
    schedule_fa = []
    if schedule_fa_str:
        try:
            schedule_fa = json.loads(schedule_fa_str)
            logger.info("Loaded Schedule FA data from request form.")
        except Exception as e:
            logger.error(f"Error parsing Schedule FA JSON: {e}")

    if not schedule_fa:
        # Fallback to automatic generation from cost basis stock sales & US dividends
        schedule_fa = tax_calculator._generate_schedule_fa(parsed_data["stock_sales"], parsed_data["us_dividends"])

    parsed_data["schedule_fa"] = schedule_fa

    if schedule_fa:
        try:
            fa_path = os.path.join(BASE_DIR, "Karthik_Schedule_FA.json")
            with open(fa_path, "w", encoding="utf-8") as f:
                json.dump(schedule_fa, f, indent=2)
            logger.info("Successfully saved latest Schedule FA data locally.")
        except Exception as e:
            logger.error(f"Error saving Schedule FA data: {e}")

    # Parse Capital Gains Exemptions JSON from request form
    cg_exemptions_str = request.form.get("cg_exemptions")
    cg_exemptions = []
    if cg_exemptions_str:
        try:
            cg_exemptions = json.loads(cg_exemptions_str)
            logger.info("Loaded Capital Gains Exemptions from request form.")
        except Exception as e:
            logger.error(f"Error parsing Capital Gains Exemptions JSON: {e}")

    parsed_data["cg_exemptions"] = cg_exemptions

    if cg_exemptions:
        try:
            cg_path = os.path.join(BASE_DIR, "Karthik_CG_Exemptions.json")
            with open(cg_path, "w", encoding="utf-8") as f:
                json.dump(cg_exemptions, f, indent=2)
            logger.info("Successfully saved latest Capital Gains Exemptions locally.")
        except Exception as e:
            logger.error(f"Error saving Capital Gains Exemptions: {e}")

    # Assemble calculator inputs
    calculator_inputs = {
        "form16": parsed_data["form16"],
        "ais": parsed_data["ais"],
        "stock_sales": parsed_data["stock_sales"],
        "us_dividends": parsed_data["us_dividends"],
        "us_interest": parsed_data["us_interest"],
        "vda_trades": parsed_data["vda_trades"],
        "home_loan_interest": home_loan_interest_override if home_loan_interest_override is not None else parsed_data["form16"].get("home_loan_interest_24b", 0.0),
        "home_loan_principal": home_loan_principal_override,
        "custom_80c": custom_80c,
        "custom_80d": custom_80d,
        "custom_80ccd_1b": custom_80ccd_1b,
        "advance_tax_paid": advance_tax_override if advance_tax_override is not None else parsed_data["ais"].get("advance_tax_paid", 0.0),
        "dob": dob,
        "hra_basic": hra_basic,
        "hra_received": hra_received,
        "hra_rent": hra_rent,
        "hra_metro": hra_metro,
        "schedule_fa": schedule_fa,
        "cg_exemptions": cg_exemptions
    }

    # Run tax computations
    try:
        tax_results = tax_calculator.compute_tax_liability(calculator_inputs)
        
        # Serialize datetime date objects for JSON compatibility
        def date_serializer(obj):
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            raise TypeError ("Type %s not serializable" % type(obj))

        # Check uploaded flags
        has_f16 = form16_file is not None and form16_file.filename != ""
        has_ais = ais_tis_file is not None and ais_tis_file.filename != ""
        has_ind = len(indian_stock_files) > 0 and any(f.filename != "" for f in indian_stock_files)
        has_us = len(us_stock_files) > 0 and any(f.filename != "" for f in us_stock_files)
        has_mf = len(mutual_funds_files) > 0 and any(f.filename != "" for f in mutual_funds_files)
        has_div = len(us_dividends_files) > 0 and any(f.filename != "" for f in us_dividends_files)
        has_1042s = len(us_1042s_files) > 0 and any(f.filename != "" for f in us_1042s_files)

        response_data = {
            "success": True,
            "pan": pan.upper(),
            "results": tax_results,
            "parsed_raw": parsed_data,
            "warnings": warnings,
            "has_files": {
                "form16": has_f16,
                "ais_tis": has_ais,
                "indian_stock": has_ind,
                "us_stock": has_us,
                "mutual_funds": has_mf,
                "us_dividends": has_div,
                "us_1042s": has_1042s
            }
        }
        
        # Cache results locally to file
        try:
            cache_path = os.path.join(BASE_DIR, "Karthik_Computation_Result.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, default=date_serializer, indent=2)
            logger.info("Successfully cached calculation result locally.")
        except Exception as cache_err:
            logger.error(f"Error caching calculation result: {cache_err}")
            
        # Custom jsonify serializer since standard jsonify doesn't handle date objects
        return app.response_class(
            response=json.dumps(response_data, default=date_serializer),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        logger.exception("Tax calculation error")
        return jsonify({
            "success": False,
            "error": f"Failed to compute tax liability: {e}",
            "warnings": warnings
        }), 500

def load_cached_result():
    cache_path = os.path.join(BASE_DIR, "Karthik_Computation_Result.json")
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading cached result: {e}")
        return None

@app.route("/api/dividends/foreign", methods=["GET"])
def get_foreign_dividends():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    parsed_raw = data.get("parsed_raw", {})
    us_divs = parsed_raw.get("us_dividends", [])
    csv_truth = parsed_raw.get("us_dividends_csv", [])
    source_of_truth = "1042-S Forms"
    if csv_truth:
        source_of_truth = csv_truth[0].get("source", "US Dividends CSV")
        
    total_usd = sum(r.get("amount_usd", 0.0) for r in us_divs)
    total_inr = sum(r.get("amount_inr", 0.0) for r in us_divs)
    
    return jsonify({
        "success": True,
        "total_dividends_usd": round(total_usd, 2),
        "total_dividends_inr": round(total_inr, 2),
        "source_of_truth": source_of_truth,
        "dividends": us_divs
    })

@app.route("/api/capital-gains/foreign", methods=["GET"])
def get_foreign_capital_gains():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    results = data.get("results", {})
    cg = results.get("capital_gains", {})
    txs = cg.get("transactions", [])
    
    # Filter profitable foreign stock transactions (gain_inr > 0 and is_us == True)
    foreign_gains = [
        t for t in txs 
        if t.get("is_us") and t.get("gain_inr", 0.0) > 0
    ]
    
    stcg_unlisted_gains = sum(t.get("gain_inr", 0.0) for t in foreign_gains if t.get("type") == "STCG")
    ltcg_unlisted_gains = sum(t.get("gain_inr", 0.0) for t in foreign_gains if t.get("type") == "LTCG")
    
    return jsonify({
        "success": True,
        "summary": {
            "stcg_unlisted_gains": round(stcg_unlisted_gains, 2),
            "ltcg_unlisted_gains": round(ltcg_unlisted_gains, 2)
        },
        "transactions": foreign_gains
    })

@app.route("/api/capital-losses/foreign", methods=["GET"])
def get_foreign_capital_losses():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    results = data.get("results", {})
    cg = results.get("capital_gains", {})
    txs = cg.get("transactions", [])
    
    # Filter loss-making foreign stock transactions (gain_inr < 0 and is_us == True)
    foreign_losses = [
        t for t in txs 
        if t.get("is_us") and t.get("gain_inr", 0.0) < 0
    ]
    
    stcg_unlisted_losses = sum(abs(t.get("gain_inr", 0.0)) for t in foreign_losses if t.get("type") == "STCG")
    ltcg_unlisted_losses = sum(abs(t.get("gain_inr", 0.0)) for t in foreign_losses if t.get("type") == "LTCG")
    
    return jsonify({
        "success": True,
        "summary": {
            "stcg_unlisted_losses": round(stcg_unlisted_losses, 2),
            "ltcg_unlisted_losses": round(ltcg_unlisted_losses, 2)
        },
        "transactions": foreign_losses
    })

@app.route("/api/capital-gains/indian", methods=["GET"])
def get_indian_capital_gains():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    results = data.get("results", {})
    cg = results.get("capital_gains", {})
    txs = cg.get("transactions", [])
    net_gains = cg.get("net_gains", {})
    
    # Filter Indian stock transactions (is_us == False)
    indian_txs = [t for t in txs if not t.get("is_us")]
    
    stcg_listed_gains = sum(t.get("gain_inr", 0.0) for t in indian_txs if t.get("type") == "STCG" and t.get("gain_inr", 0.0) > 0)
    stcg_listed_losses = sum(abs(t.get("gain_inr", 0.0)) for t in indian_txs if t.get("type") == "STCG" and t.get("gain_inr", 0.0) < 0)
    ltcg_listed_gains = sum(t.get("gain_inr", 0.0) for t in indian_txs if t.get("type") == "LTCG" and t.get("gain_inr", 0.0) > 0)
    ltcg_listed_losses = sum(abs(t.get("gain_inr", 0.0)) for t in indian_txs if t.get("type") == "LTCG" and t.get("gain_inr", 0.0) < 0)
    
    total_charges = sum(t.get("transfer_expenses", 0.0) for t in indian_txs)
    
    return jsonify({
        "success": True,
        "summary": {
            "stcg_listed_gains": round(stcg_listed_gains, 2),
            "stcg_listed_losses": round(stcg_listed_losses, 2),
            "ltcg_listed_gains": round(ltcg_listed_gains, 2),
            "ltcg_listed_losses": round(ltcg_listed_losses, 2),
            "net_ltcg_listed": round(net_gains.get("ltcg_listed", 0.0), 2),
            "total_charges_deducted": round(total_charges, 2)
        },
        "transactions": indian_txs
    })

@app.route("/api/capital-gains/combined", methods=["GET"])
def get_combined_capital_gains():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    results = data.get("results", {})
    cg = results.get("capital_gains", {})
    txs = cg.get("transactions", [])
    
    indian_txs = [t for t in txs if not t.get("is_us")]
    foreign_txs = [t for t in txs if t.get("is_us")]
    
    total_gains = sum(t.get("gain_inr", 0.0) for t in txs if t.get("gain_inr", 0.0) > 0)
    total_losses = sum(abs(t.get("gain_inr", 0.0)) for t in txs if t.get("gain_inr", 0.0) < 0)
    
    return jsonify({
        "success": True,
        "summary": {
            "combined_gains": round(total_gains, 2),
            "combined_losses": round(total_losses, 2),
            "net_taxable_gains": round(total_gains - total_losses, 2)
        },
        "indian_stocks": indian_txs,
        "foreign_stocks": foreign_txs
    })

@app.route("/api/tax-summary", methods=["GET"])
def get_tax_summary():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    results = data.get("results", {})
    new_regime = results.get("regimes", {}).get("new", {})
    parsed_raw = data.get("parsed_raw", {})
    
    salary_tds = parsed_raw.get("form16", {}).get("tds_deducted", 0.0)
    deposit_tds = parsed_raw.get("ais", {}).get("tds_on_deposit_interest", 0.0)
    
    return jsonify({
        "success": True,
        "fy": results.get("fy", "2025-26"),
        "pan": data.get("pan", ""),
        "summary": {
            "gross_total_income": round(new_regime.get("gross_total_income", 0.0), 2),
            "total_deductions_80c_80d": round(new_regime.get("deductions", {}).get("total", 0.0), 2),
            "net_taxable_income": round(new_regime.get("total_taxable_income", 0.0), 2),
            "basic_slab_tax": round(new_regime.get("slab_tax", 0.0), 2),
            "capital_gains_tax": round(new_regime.get("cg_tax", {}).get("total", 0.0), 2),
            "deposit_tds_credited": round(deposit_tds, 2),
            "salary_tds_credited": round(salary_tds, 2),
            "advance_tax_paid": round(new_regime.get("advance_tax_paid", 0.0), 2),
            "interest_234c": round(new_regime.get("interest_234c", 0.0), 2),
            "final_due_or_refund": round(new_regime.get("final_due_or_refund", 0.0), 2)
        }
    })

@app.route("/api/bank-tds", methods=["GET"])
def get_bank_tds():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    parsed_raw = data.get("parsed_raw", {})
    ais = parsed_raw.get("ais", {})
    tds_details = ais.get("tds_on_deposit_interest_details", [])
    total_tds = ais.get("tds_on_deposit_interest", 0.0)
    
    return jsonify({
        "success": True,
        "total_bank_tds": round(total_tds, 2),
        "tds_records": tds_details
    })

@app.route("/api/forex-rates/applicable", methods=["GET"])
def get_applicable_forex_rates():
    data = load_cached_result()
    if not data:
        return jsonify({"success": False, "error": "No cached calculations found. Please upload documents first."}), 404
        
    parsed_raw = data.get("parsed_raw", {})
    us_divs = parsed_raw.get("us_dividends", [])
    us_stocks = parsed_raw.get("stock_sales", [])
    
    applicable = []
    seen = set()
    
    # 1. Foreign Dividends
    for d in us_divs:
        d_date = d.get("date")
        rate = d.get("rate_used")
        if d_date and rate and (d_date, rate) not in seen:
            seen.add((d_date, rate))
            applicable.append({
                "date": d_date,
                "rate": rate,
                "source_event": f"US Dividend transaction ({d.get('source', 'Schwab')})"
            })
            
    # 2. Foreign Stocks
    for s in us_stocks:
        if s.get("is_us"):
            b_date = s.get("buy_date")
            b_rate = s.get("rate_buy_used")
            if b_date and b_rate:
                if isinstance(b_date, str):
                    b_date_str = b_date[:10]
                else:
                    b_date_str = b_date.strftime("%Y-%m-%d") if hasattr(b_date, "strftime") else str(b_date)
                
                if (b_date_str, b_rate) not in seen:
                    seen.add((b_date_str, b_rate))
                    applicable.append({
                        "date": b_date_str,
                        "rate": b_rate,
                        "source_event": f"US Stock Purchase: {s.get('symbol')}"
                    })
                    
            s_date = s.get("sell_date")
            s_rate = s.get("rate_sell_used")
            if s_date and s_rate:
                if isinstance(s_date, str):
                    s_date_str = s_date[:10]
                else:
                    s_date_str = s_date.strftime("%Y-%m-%d") if hasattr(s_date, "strftime") else str(s_date)
                
                if (s_date_str, s_rate) not in seen:
                    seen.add((s_date_str, s_rate))
                    applicable.append({
                        "date": s_date_str,
                        "rate": s_rate,
                        "source_event": f"US Stock Sale: {s.get('symbol')}"
                    })
                    
    applicable.sort(key=lambda x: x["date"], reverse=True)
    
    return jsonify({
        "success": True,
        "applicable_rates": applicable
    })

@app.route("/api/forex-rates", methods=["GET"])
def get_forex_rates():
    currency = request.args.get("currency", "USD").strip().upper()
    if currency != "USD":
        return jsonify({"success": False, "error": f"Currency {currency} is not supported. Only USD rates are maintained."}), 400
        
    rates_list = rate_resolver.usd_rates
    total_rates = len(rates_list)
    
    latest_date = None
    latest_val = None
    if rates_list:
        sorted_dates = sorted(rates_list.keys(), reverse=True)
        latest_date = sorted_dates[0].isoformat() if hasattr(sorted_dates[0], "isoformat") else str(sorted_dates[0])
        latest_val = rates_list[sorted_dates[0]]
        
    return jsonify({
        "success": True,
        "currency": "USD",
        "total_rates": total_rates,
        "latest_rate": {
            "date": latest_date,
            "rate": latest_val
        } if latest_date else None
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
