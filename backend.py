import os
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
    us_1042s_files = request.files.getlist("us_1042s")

    parsed_data = {
        "form16": {},
        "ais": {},
        "stock_sales": [],
        "us_dividends": [],
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

    # 2. Parse AIS or TIS
    if ais_tis_file and ais_tis_file.filename:
        try:
            ais_tis_pdf = ais_tis_file.read()
            pw_list = []
            if pan and dob:
                pw_list.append(f"{pan.lower()}{dob}")
                pw_list.append(f"{pan.upper()}{dob}")
            pw = pw_list[0] if pw_list else None
            
            parsed_data["ais"] = doc_parser.parse_ais_tis(ais_tis_pdf, pw)
            logger.info("Successfully parsed AIS/TIS.")
        except Exception as e:
            logger.error(f"Error parsing AIS/TIS: {e}")
            warnings.append(f"Failed to decrypt/parse AIS/TIS PDF. Ensure PAN and Date of Birth (DDMMYYYY) are correct. Details: {e}")

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

    # 4. Parse multiple Form 1042-S PDFs
    if us_1042s_files:
        for f in us_1042s_files:
            if not f or not f.filename:
                continue
            try:
                f_bytes = f.read()
                parsed = doc_parser.parse_1042s(f_bytes)
                
                # Resolve date for Rule 115 TT Buying rate lookup
                if parsed.get("payment_date"):
                    try:
                        txn_date = datetime.strptime(parsed["payment_date"], "%Y-%m-%d").date()
                    except Exception:
                        txn_date = date(int(parsed["tax_year"]), 12, 31)
                else:
                    # Consolidated default: Nov 30 of tax year
                    txn_date = date(int(parsed["tax_year"]), 11, 30)

                rate = rate_resolver.resolve_rule_115_rate(txn_date)
                
                gross_usd = float(parsed["gross_income_usd"])
                withholding_usd = float(parsed["withholding_tax_usd"])
                
                record = {
                    "date": txn_date,
                    "amount_usd": gross_usd,
                    "amount_inr": gross_usd * rate,
                    "withholding_usd": withholding_usd,
                    "withholding_inr": withholding_usd * rate,
                    "rate_used": rate
                }
                
                code = str(parsed["income_code"]).strip().zfill(2)
                if code == "06":
                    parsed_data["us_dividends"].append(record)
                    logger.info(f"Parsed US Dividend from 1042-S: ${gross_usd}")
                elif code in ["01", "29", "30"]:
                    parsed_data["us_interest"].append(record)
                    logger.info(f"Parsed US Bank Interest from 1042-S: ${gross_usd}")
                else:
                    logger.warning(f"Unknown 1042-S income code {code}. Defaulting to dividends.")
                    parsed_data["us_dividends"].append(record)
                    
            except Exception as e:
                logger.error(f"Error parsing 1042-S PDF: {e}")
                warnings.append(f"Failed to parse 1042-S PDF '{f.filename}': {e}")

    # Assemble calculator inputs
    calculator_inputs = {
        "form16": parsed_data["form16"],
        "ais": parsed_data["ais"],
        "stock_sales": parsed_data["stock_sales"],
        "us_dividends": parsed_data["us_dividends"],
        "us_interest": parsed_data["us_interest"],
        "home_loan_interest": home_loan_interest_override if home_loan_interest_override is not None else parsed_data["form16"].get("home_loan_interest_24b", 0.0),
        "home_loan_principal": home_loan_principal_override,
        "custom_80c": custom_80c,
        "custom_80d": custom_80d,
        "advance_tax_paid": advance_tax_override if advance_tax_override is not None else parsed_data["ais"].get("advance_tax_paid", 0.0),
        "dob": dob
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
        import json
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
