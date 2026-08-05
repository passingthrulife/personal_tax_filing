# Aatmanirbhar Tax Engine

Aatmanirbhar Tax is a self-contained, automated personal income tax calculator built for Indian individual taxpayers with complex income portfolios. It is especially tailored for tech professionals and investors who receive foreign stock compensation (RSUs/ESPPs), claim Foreign Tax Credits (FTC) under Section 90, and manage multiple domestic interest and dividend sources.

The tool parses official PDFs and statements locally, resolves exchange rates u/s Rule 26 using historical SBI TT Buying rates, computes tax liability under both the Old and New tax regimes, and generates a printable tax computation sheet.

---

## 🌟 Key Features

* **Regime Comparison**: Side-by-side old vs new tax regime comparison for **FY 2025-26 (AY 2026-27)**.
* **Form 16 Parser**: Extracts salary particulars (Section 17(1) basic pay, Section 17(2) perquisites/vested RSUs, and Section 17(3) profits in lieu) directly from Form 16 PDF.
* **AIS/TIS PDF Parser**: Uses a state-machine parser to scan the TIS/AIS Statement PDF, extracting and listing every savings account bank, deposit interest account, domestic company dividend, and advance tax payment.
* **EPFO Taxable Interest**: Parses taxable interest from employee EPF contributions exceeding ₹2.5 Lakhs (along with Section 194A TDS credits).
* **US Stock Realizations**: Parses Schwab/Fidelity CSV statements, converts USD to INR using the exact date-by-date SBI TT Buying rate, and computes short-term/long-term capital gains.
* **Manual Stock Realizations**: Manual entry grids for both Indian and US stock sales to log custom transaction records.
* **House Property Calculator**: Supports self-occupied, let-out, and deemed let-out properties, computing net annual value, 30% statutory deduction u/s 24(a), municipal taxes, and home loan interest u/s 24(b) (with regime-specific capping).
* **HRA Exemption & Chapter VI-A Deductions**: Includes a dedicated calculator for Section 10(13A) HRA exemption (rules on actual rent, received HRA, and basic salary) under the Old regime, alongside inputs for Section 80C, 80D, 80CCD(1B) (NPS), and 80TTA/TTB interest deductions.
* **Carried-Forward Capital Losses (Sec 74)**: Supports setting off brought-forward short-term (BF STCL) and long-term (BF LTCL) capital losses from previous years against current eligible gains (BF LTCL u/s 74 is restricted to LTCG, while BF STCL can set off against both STCG and LTCG).
* **Section 234C & 234B Interest & Ledger**: Extracts actual dates of advance tax payments to compute bucked quarterly shortfalls and interest charges. Includes a **transparency ledger modal** displaying installment target percentages, assessed cumulative tax liability, actual paid cumulative tax, and interest accrued per installment.
* **Surcharge Capping (15%) & Surcharge Marginal Relief**: Caps surcharge on dividends and special capital gains (Section 111A, 112A, 112) at 15%. Implements proportional scaling surcharge marginal relief under both regimes at all thresholds (₹50L, ₹1Cr, ₹2Cr, ₹5Cr).
* **Form 67 FTC Relief**: Automatically computes Foreign Tax Credit (FTC) relief under Section 90 for double-taxed US stock dividends.
* **Capital Gains Exemptions**: Factors in reinvestment exemptions (Section 54F, 54EC) for unlisted US stock sales.
* **Interactive Modals**: Clickable schedule items on the dashboard show detailed breakdowns of individual bank transactions, assets, and the advance tax ledger.
* **Printable PDF Reports**: Generates a high-fidelity tax computation sheet summarizing comparative schedules and transaction registers, printable directly to PDF.

---

## 👥 Who Can Use This Tool?

Indian residents who file **ITR-1** or **ITR-2** and have:
1. **Salary Income** with RSU/Stock vesting details.
2. **Foreign Assets (Schedule FA)** and US Stock Capital Gains.
3. **Double-Taxed Foreign Dividends** requiring Section 90 relief and Form 67 preparation.
4. **Interest Income** across multiple bank accounts and Fixed Deposits.
5. **Taxable EPF Interest** from high employee provident fund contributions.
6. **Carried-Forward Losses** from previous tax years.

---

## 📋 Necessary Input Files

To run calculations, upload the following files via the dashboard:

| File Type | Format | Source | Purpose |
| :--- | :--- | :--- | :--- |
| **AIS/TIS Statement** | `.pdf` | Income Tax e-filing portal | Extraction of savings, FDs, domestic dividends, EPF interest, advance tax dates, and refund interest |
| **Form 16 Part B** | `.pdf` | Employer | Salary Section 17 breakdown and TDS credited |
| **US Realization Report** | `.csv` | Schwab / Fidelity / Broker | Realized gain/loss details for US Stock capital gains |
| **US Dividends Report** | `.csv` | Schwab / Fidelity / Broker | Foreign dividends received and tax withheld u/s 1042-S |
| **Indian Stocks / MF Realization** | `.csv` / `.pdf` | Broker (Groww, Zerodha, HDFC Sec, etc.) | Realized gain/loss, grandfathered prices, and transaction dates for domestic stocks and mutual funds |
| **CG Exemptions** *(Optional)* | `.json` | Pre-configured | Custom exemption amounts claimed under Section 54F/54EC |

---

## 🛠️ Technical Requirements

* **Python**: Version `3.9` or higher.
* **Dependencies**: Minimal dependencies (only Flask web framework, pypdf parser, and dateutil):
  - `Flask==3.1.3`
  - `pypdf==6.14.2`
  - `python-dateutil==2.9.0.post0`

---

## 🚀 Getting Started

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the Server**:
   ```bash
   python run.py
   ```

3. **Use the Application**:
   Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your web browser, enter your PAN & Date of Birth, upload your statements, and click **Process Tax Data**. (Note: runs on port `5001` to avoid conflicts with macOS AirPlay Receiver).
