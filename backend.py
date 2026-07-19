import os
import json
from datetime import datetime, date
import logging
from flask import Flask, request, jsonify, render_template_string
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
    # Renders the single-page HTML template from the local file
    try:
        template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
        return render_template_string(template_content)
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
    indian_stock_file = request.files.get("indian_stock")
    us_stock_file = request.files.get("us_stock")
    us_dividends_file = request.files.get("us_dividends_csv")
    us_1042s_files = request.files.getlist("us_1042s")

    parsed_data = {
        "form16": {},
        "ais": {},
        "stock_sales": [],
        "us_dividends": [],
        "us_dividends_1042s": [],
        "us_interest": []
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
        detail_keys = ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details"]
        
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
        for key in ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details"]:
            if key in ais_csv_data:
                for item in ais_csv_data[key]:
                    if "(" in item.get("source", ""):
                        item["source"] = item["source"].split("(")[0].strip()
        parsed_data["ais"] = ais_csv_data
    elif ais_pdf_data:
        for key in ["savings_details", "fd_details", "dividend_details", "advance_tax_details", "taxable_epf_interest_details"]:
            if key in ais_pdf_data:
                for item in ais_pdf_data[key]:
                    if "(" in item.get("source", ""):
                        item["source"] = item["source"].split("(")[0].strip()
        parsed_data["ais"] = ais_pdf_data

    # 3. Parse Stock Sales
    if indian_stock_file and indian_stock_file.filename:
        try:
            indian_stock_csv = indian_stock_file.read().decode('utf-8')
            records = doc_parser.parse_stock_sales_csv(indian_stock_csv, is_us=False)
            parsed_data["stock_sales"].extend(records)
            logger.info(f"Parsed {len(records)} Indian stock sales.")
        except Exception as e:
            logger.error(f"Error parsing Indian stock sales CSV: {e}")
            warnings.append(f"Error parsing Indian Stock Sales CSV: {e}")

    if us_stock_file and us_stock_file.filename:
        try:
            us_stock_csv = us_stock_file.read().decode('utf-8')
            records = doc_parser.parse_stock_sales_csv(us_stock_csv, is_us=True)
            parsed_data["stock_sales"].extend(records)
            logger.info(f"Parsed {len(records)} US stock sales.")
        except Exception as e:
            logger.error(f"Error parsing US stock sales CSV: {e}")
            warnings.append(f"Error parsing US Stock Sales CSV: {e}")

    # 3.5 Parse US Dividends CSV
    csv_divs = []
    if us_dividends_file and us_dividends_file.filename:
        try:
            us_div_csv = us_dividends_file.read().decode('utf-8')
            records = doc_parser.parse_us_dividends_csv(us_div_csv)
            for r in records:
                r["source"] = us_dividends_file.filename
            csv_divs.extend(records)
            logger.info(f"Parsed {len(records)} US dividends from CSV.")
        except Exception as e:
            logger.error(f"Error parsing US dividends CSV: {e}")
            warnings.append(f"Error parsing US Dividends CSV: {e}")

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
                        txn_date = date(int(parsed["tax_year"]), 11, 30)

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
    
    # Reconciliation logic: compare USD totals
    total_csv_usd = sum(r["amount_usd"] for r in csv_divs)
    total_1042s_usd = sum(r["amount_usd"] for r in us_dividends_1042s)
    
    if us_dividends_1042s:
        # Check if they match within $2.00 tolerance
        if csv_divs and abs(total_csv_usd - total_1042s_usd) < 2.0:
            parsed_data["us_dividends_match"] = True
            parsed_data["us_dividends"] = csv_divs
        else:
            parsed_data["us_dividends_match"] = False
            # Reconcile using 1042-S as default source of truth, converted at Dec 31st TT rates
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
            parsed_data["us_dividends"] = reconciled_1042s
    else:
        # No 1042-S files uploaded
        parsed_data["us_dividends_match"] = True
        parsed_data["us_dividends"] = csv_divs

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
        has_ind = indian_stock_file is not None and indian_stock_file.filename != ""
        has_us = us_stock_file is not None and us_stock_file.filename != ""
        has_1042s = len(us_1042s_files) > 0 and any(f.filename != "" for f in us_1042s_files)

        response_data = {
            "success": True,
            "results": tax_results,
            "parsed_raw": parsed_data,
            "warnings": warnings,
            "has_files": {
                "form16": has_f16,
                "ais_tis": has_ais,
                "indian_stock": has_ind,
                "us_stock": has_us,
                "us_1042s": has_1042s
            }
        }
        
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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
