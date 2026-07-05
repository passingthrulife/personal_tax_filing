# Outstanding Issues & Planned Enhancements

This document tracks the bugs, layout limitations, and enhancements identified during the tax filing software run. We will resolve these in the next session.

---

## Outstanding Issues

### 1. Form-16 PDF Parsing & Perquisites Accuracy
- **Symptom**: Perquisites data (Quarterly RSU vests u/s 17(2)) is incorrect or missing.
- **Root Cause**: The raw PDF layout or text extraction u/s Form 16 may not align with current regex/prompt models, resulting in incorrect magnitude extraction or omission of perquisite blocks.
- **Goal**: Refine the PDF text extraction and fallback regexes to ensure perquisites u/s 17(2) match the document exactly.

### 2. Form 1042-S PDF Parsing & Dividend Accuracy
- **Symptom**: Extracted US dividend information is incorrect.
- **Goal**: Audit the Form 1042-S parser logic (`parse_1042s` in `parser.py`) to verify how federal tax withheld (Box 7) and gross dividends (Box 2) are mapped, ensuring they align precisely with your U.S. statements.

### 3. US Stock Sales CSV Parsing Failure
- **Symptom**: The parser crashed with the error:  
  `Error parsing US Stock Sales CSV: Required columns (Quantity, Buy Date, Buy Price, Sell Date, Sell Price) not resolved in CSV headers: [...]`
- **Missing Mappings**: The brokerage CSV statement lists the following headers:
  - **Symbol**: `'symbol'`
  - **Quantity**: `'quantity'`
  - **Buy Date**: `'opened date'` (date purchased)
  - **Buy Price / Cost**: `'cost per share'` (unit price) or `'cost basis (cb)'` (total cost)
  - **Sell Date**: `'closed date'` or `'transaction closed date'`
  - **Sell Price / Proceeds**: `'proceeds per share'` (unit price) or `'proceeds'` (total proceeds)
- **Goal**: Expand the CSV header resolution keyword mapping lists in `parser.py` to identify these columns.

### 4. Tab Layout Styling (Viewport Constraints)
- **Symptom**: Sidebar/Page layout forces horizontal scrolling.
- **Goal**: Restructure the layout within individual tabs (Overview & Slabs, Schedule S, Schedule HP, etc.) so that all tab content fits cleanly within the horizontal viewport boundaries without horizontal scrollbars, keeping scrolling isolated to long vertical sections.

---

## Planned Enhancements

### 1. Foreign Dividends Breakdown Modal
- **Description**: Clicking the "Foreign Dividends (US stocks)" row on the dashboard should open an interactive modal/pop-up showing how the total INR was calculated.
- **Example Details**:
  - `1042-S Schwab 1.pdf`: `$xxxx.xx USD`
  - `1042-S Fidelity.pdf`: `$yyyy.yy USD`
  - Total: `₹zz,zzz INR`

### 2. Transaction-Level US Dividend CSV/Excel Ingestion
- **Description**: Since Form 1042-S is an annual calendar-year summary, it uses a generic preceding month-end conversion date. 
- **Goal**: Add support to upload a transaction-level CSV/Excel spreadsheet listing individual dividend payments (Company name, transaction date, and USD amount). The parser will automatically lookup the specific SBI TT buying rate (TTBR) for the month preceding each exact transaction date for precise conversions.
