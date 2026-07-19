# Aatmanirbhar Tax Portal - Issues & Enhancements Tracking

This document tracks unresolved issues, resolved features, and planned roadmap enhancements for the tax filing calculator.

---

## ✅ Resolved in Previous Sessions

### 1. Layout & Tab Horizontal Scrolling
- Fixed constraints that caused dashboard regime comparison cards and individual schedule tabs to be clipped on smaller viewports. Added horizontal scroll support and customized scrollbars for the tabs.

### 2. Form 16 Decimals & Zero-Value Fallback Matching
- Resolved regex matching errors in `parser.py` that occurred when decimals were omitted in Form 16. Added support to correctly distinguish zero-valued fields (e.g. Profits in lieu of salary u/s 17(3) is 0) from unmatched fields.

### 3. Schwab / Fidelity Stock Sales CSV Ingestion
- Upgraded the cost basis CSV parser to dynamically scan for header rows and resolve custom column names. Added support to automatically scale down total cost/proceeds to unit prices based on transaction quantity.

### 4. US Dividends Date-by-Date CSV Ingestion & SBI TTBR Lookup
- Implemented transaction-level ingestion of USD dividends, lookup of monthly TT Buying Rates, and deduplication/reconciliation with annual Form 1042-S statements.

### 5. Interactive Breakdown Modal Popups
- Added detailed popup modals for Gross Salary 17(1), Perquisites 17(2), and Foreign Dividends to show contributors, dates, and currency exchange rates.

### 6. Multiple AIS CSV Ingestion & PDF Merge
- Upgraded the file upload UI and backend to support uploading multiple AIS CSV files downloaded from the AIS utility.
- Added parsing logic to scan and extract savings interest, term deposit interest, dividends, and gross salary from individual CSV files.
- Implemented extraction of last year's tax refund amount and outstanding tax due demand from the AIS/TIS PDF.
- Added automated estimation of Section 244A refund interest (0.5% per month or part of a month from April 1 of the assessment year to the payment date) and included it in the taxable Income from Other Sources.
- Added logic to append last year's tax due demand directly to the current year's final tax bill.

### 8. Regime Column Ordering in Overview Comparison
- **Resolution**: Swapped the columns in the Detailed Side-by-Side Regime Comparison table and Final Tax Status row to display the "New Regime" first and "Old Regime" second, matching user preference.

### 9. Schedule Value Alignment & Copy Buttons
- **Resolution**: Added a fixed min-width (140px) and right-alignment to `.row-val` in CSS. Shifted the pseudo-element `::after` (which renders the `ⓘ` icon) from `.clickable-row` to `.clickable-row .label-main`. This keeps the table row container limited to exactly two flex children, ensuring that all values and copy buttons align perfectly in a vertical column without being pushed by the informational icons.

### 10. Laptop-Friendly Maximum Layout Width
- **Resolution**: Constrained `.container` to `1280px` max-width and `.main-content` to `900px` max-width to prevent table stretch and bring numbers closer to row labels, fitting perfectly on standard MacBook monitors.

### 11. HRA base_dir NameError & Sidebar Form Relocation
- **Resolution**: Defined a global `BASE_DIR` module-level constant at the top of `backend.py` and pointed both route file operations to it, eliminating the NameError when saving HRA inputs. Moved the HRA input fields inside the manual overrides card so they sit right next to the other inputs (above the submit/load buttons).

### 12. Schedule FA (Foreign Assets) Manual Entries & Depository Accounts
- **Resolution**: Converted the static Schedule FA table to an interactive editor with editable cells and an "+ Add Asset" button. Users can now declare foreign bank accounts, zero-dividend shares, or other custodial holdings manually. Automatically merges dynamically generated Schwab holdings with manually entered rows, and auto-saves your FA state to `Karthik_Schedule_FA.json` inside your local directory.

---

## 🛠️ Outstanding Issues (Current Session Actions)

### 1. Surcharges Not Calculated
- **Resolution**: Implemented dynamic surcharge calculation in `calculator.py`. It correctly applies the capped 15% rate on special capital gains and dividend income, and 25% or 37% on regular income (capped at 25% under the New Regime). Unified calculation logic across both regimes so that the tiered 25% surcharge is properly computed under the New Regime when income exceeds 2 Crores. Displays surcharge in the comparison table.

### 2. Interest u/s 234B & 234C
- **Resolution**: Integrated interest calculations u/s 234B (for defaults in paying advance tax) and Section 234C (for deferment of installments). It respects the special exemption u/s 234C where capital gains and dividend income are excluded from early installment shortfalls.

### 3. Net Tax Due / Refund Display
- **Resolution**: Updated the side-by-side comparison table to display:
  - Total Surcharges
  - Health & Education Cess
  - FTC Relief (DTAA u/s 90)
  - TDS Credited & Advance Tax Paid
  - Final Tax Status (Net Tax Due or Refund)

### 4. US Dividends Reconciliation & December 31st Forex Fallback
- **Resolution**: Automatically compares USD totals between the CSV statement and Form 1042-S PDFs. If they do not match, it displays a prominent alert on the page, uses the Form 1042-S forms as the default source of truth, and converts the USD amounts to INR using the SBI TT buying rate as of December 31st of the tax year. Shows both tables side-by-side inside the interactive popup modal.

### 5. Schedule AL (Assets and Liabilities) Disclosures & Portal Export (Enhancement 3)
- **Resolution**: Added a new tab panel 'Schedule AL' that allows capturing domestic immovable properties (address, pin code, cost) dynamically, movable assets (bank deposits, shares, insurance, gold, vehicles), and liabilities. Supports exporting these inputs in portal-ready upload-ready JSON or CSV formats.

### 6. Cryptocurrencies & VDA Trades u/s 115BBH (Enhancement 4)
- **Resolution**: Integrated VDA / Crypto transaction CSV parsing and manual entry into the new 'Schedule VDA' tab. The tax calculator applies a flat 30% tax rate on positive gains per trade with zero deduction for expenses or set-off/carry-forward of losses, and lists VDA tax in the comparison table.

### 7. House Rent Allowance (HRA) Calculator (Old Regime)
- **Resolution**: Added a dedicated 'HRA Exemption Calculator' sidebar panel to capture Annual Basic Salary, Actual HRA Received, Annual Rent Paid, and city of residence (Metro vs Non-Metro). The calculator automatically computes the tax-exempt amount u/s 10(13A) as the minimum of the three statutory limits and applies it under the Old Regime. The UI shows the breakdown details under the Schedule S tab.

### 8. Capital Gains Exemptions (Sections 54 / 54B / 54EC / 54F)
- **Resolution**: Added a dynamic input editor for capital gains exemptions u/s Schedule CG tab. Tax calculator computes tax deductions dynamically based on reinvestments and net considerations (with a ₹10 Cr limit for Sec 54/54F, and ₹50L limit for Sec 54EC). Renders calculated exemptions directly inside copy summaries and persists inputs locally in `Karthik_CG_Exemptions.json`.

### 9. Schedule VI-A Deductions Show Zero in New Regime
- **Resolution**: Changed the frontend data binding for Schedule VI-A values in `templates/index.html` to always pull from `results.old.deductions` instead of `optimalData.deductions`. This ensures that even when the New Regime is recommended (resulting in ₹0 optimal deductions), your actual computed/entered Old Regime deductions are still shown in the tab for audit/viewing purposes.

### 10. Dual Browser Tabs Opening on Server Start
- **Resolution**: Flask's debug mode restarts the script in a Werkzeug reloader subprocess, executing the main block twice. Added an environment check `os.environ.get("WERKZEUG_RUN_MAIN") == "true"` inside `run.py` to ensure the browser-opening thread only starts in the child process.

### 11. AIS CSV + PDF Dual Intake Support
- **Resolution**: Updated templates/index.html to sort and append selected file uploads by extension (.pdf goes to "ais_tis" and .csv goes to "ais_files"). Rewrote process_tax in backend.py to parse both sources in parallel and merge their output summaries by taking the maximum value for each key. This allows the tool to swallow all detailed CSV lines and the PDF simultaneously, merging unexportable items (like last year's refund amount) automatically.

### 12. Generalize 80C Home Loan Label
- **Resolution**: Generalised the sidebar form labels in templates/index.html to "Home Loan Principal (Sec 80C)" and "Other Section 80C Deductions (PPF/ELSS/etc.)", clarifying that Section 80C accommodates arbitrary investments.

### 13. EPFO Taxable Interest & TDS Credits
- **Resolution**: Updated `parser.py` (both PDF and CSV paths) to parse Regional Office Bommasanora 2 EPFO interest (₹32,103) and EPFO TDS (₹3,567). Updated `calculator.py` to add `taxable_epf_interest` to other sources income and add `taxable_epf_interest_tds` to total `tds_credited` claimed, reducing final tax due/increasing refund.

### 14. PDF-Only Savings Bank Interest Parsing Fix
- **Resolution**: Replaced simple keyword parsing in `parser.py` with a state-machine parser. It accurately extracts the detail rows from the TIS/AIS PDF under Section 194A / SFT-016(SB), resolving the 0.0 savings interest bug.

### 15. Detailed Modal Popups for Schedule OS
- **Resolution**: Updated `/api/process` to return lists of individual transactions (`savings_details`, `fd_details`, `dividend_details`, etc.). Re-engineered `templates/index.html` to render detailed tables inside the popups listing sources, account numbers, and amounts.

### 16. Corrected Section 234C Interest Calculation
- **Resolution**: Replaced the full assessed-tax default shortfall u/s 234C with date-bucketed advance tax subtraction logic. The code now buckets advance tax payments by their actual dates (extracted from the AIS PDF) and subtracts them from installment requirements to compute shortfalls.

### 17. Single-Page PDF Tax Report Download
- **Resolution**: Added a "Download PDF Report" action in the Side-by-Side Comparison section of the Overview tab. It generates a clean, printable tax computation sheet summarizing all calculations and schedule details and invokes the browser print dialogue.

### 18. Premature Script Block Closing (Browser Tag Token Collision)
- **Resolution**: Fixed a bug where including the `</script>` tag as a string literal within a JavaScript template literal u/s `downloadPDFReport` caused the browser's HTML parser to close the main `<script>` tag prematurely, breaking the subsequent click event listeners. Handled it by interpolating it as `<\/s\${""}cript>`.

### 19. UnboundLocalError: Local Variable 'json' Referenced Before Assignment
- **Resolution**: Fixed a scoping bug in `backend.py` where declaring `import json` locally inside branches of `api_process` caused Python to treat `json` as a local name across the entire scope of the endpoint function, resulting in reference failures when using the global `json` object in prior blocks. Removed all local `import json` statements in favor of the global `import json` defined at the top of the file.

### 20. JS Escaped Backticks Syntax Error (Template Literal Broken)
- **Resolution**: Fixed a syntax bug in `templates/index.html` where backslashes were escaping the start/end backticks of the template literal (`pWindow.document.write(\` ... \`)`). This prevented JS from recognizing the template literal and broke the JavaScript execution context entirely. Removed the backslashes to correctly wrap the print document payload.

### 21. Modal Popups TypeErrors (Unresolved Nested Keys)
- **Resolution**: Fixed a bug where clicking the savings, deposit, or dividend interest rows threw a TypeError. Because the frontend global caching object was shifted to cache the entire backend response instead of just `.parsed_raw`, lookups like `globalProcessedData.ais` were returning `undefined`. Corrected them to reference nested keys under `.parsed_raw` and `.results` correctly.

---

## 🐛 Open Bugs
*(All active bugs resolved!)*

---

## 🚀 Planned Enhancements (Roadmap)

### 1. Remove External SBI TT Repo Dependency
- Eliminate the external git repository dependency for SBI TT buying rates, replacing it with a self-contained/local rate loading method.
