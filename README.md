# Aatmanirbhar Tax Calculator

Aatmanirbhar Tax is a self-contained, automated personal income tax calculator built for Indian individual taxpayers with complex income portfolios. It is especially tailored for tech professionals and investors who receive foreign stock compensation (RSUs/ESPPs), claim Foreign Tax Credits (FTC) under Section 90, and manage multiple domestic interest and dividend sources.

The tool parses official PDFs and statements locally, resolves exchange rates u/s Rule 26 using historical SBI TT Buying rates, computes tax liability under both the Old and New tax regimes, and generates a printable tax computation sheet.

---

## 🌟 Key Features

* **Regime Comparison**: Side-by-side old vs new tax regime comparison for **FY 2025-26 (AY 2026-27)**.
* **Form 16 Parser**: Extracts salary particulars (Section 17(1) basic pay, Section 17(2) perquisites/vested RSUs, and Section 17(3) profits in lieu) directly from Form 16 PDF.
* **AIS/TIS PDF Parser**: Uses a state-machine parser to scan the TIS/AIS Statement PDF, extracting and listing every savings account bank, deposit interest account, domestic company dividend, and advance tax payment.
* **EPFO Taxable Interest**: Parses taxable interest from employee EPF contributions exceeding ₹2.5 Lakhs (along with Section 194A TDS credits).
* **US Stock Realizations**: Parses Schwab/Fidelity CSV statements, converts USD to INR using the exact date-by-date SBI TT Buying rate, and computes short-term/long-term capital gains.
* **Section 234C & 234B Interest**: Extracts actual dates of advance tax payments from the AIS PDF to compute bucketed quarterly shortfalls and interest charges u/s 234C and 234B.
* **Form 67 FTC Relief**: Automatically computes Foreign Tax Credit (FTC) relief under Section 90 for double-taxed US stock dividends.
* **Capital Gains Exemptions**: Factors in reinvestment exemptions (Section 54F, 54EC) for unlisted US stock sales.
* **Interactive Modals**: Clickable schedule items on the dashboard show detailed breakdowns of individual bank transactions and assets.
* **Printable PDF Reports**: Generates a high-fidelity tax computation sheet summarizing comparative schedules and transaction registers, printable directly to PDF.

---

## 👥 Who Can Use This Tool?

Indian residents who file **ITR-1** or **ITR-2** and have:
1. **Salary Income** with RSU/Stock vesting details.
2. **Foreign Assets (Schedule FA)** and US Stock Capital Gains.
3. **Double-Taxed Foreign Dividends** requiring Section 90 relief and Form 67 preparation.
4. **Interest Income** across multiple bank accounts and Fixed Deposits.
5. **Taxable EPF Interest** from high employee provident fund contributions.

---

## 📋 Necessary Input Files

To run calculations, upload the following files via the dashboard:

| File Type | Format | Source | Purpose |
| :--- | :--- | :--- | :--- |
| **AIS/TIS Statement** | `.pdf` | Income Tax e-filing portal | Extraction of savings, FDs, domestic dividends, EPF interest, advance tax dates, and refund interest |
| **Form 16 Part B** | `.pdf` | Employer | Salary Section 17 breakdown and TDS credited |
| **US Realization Report** | `.csv` | Schwab / Fidelity / Broker | Realized gain/loss details for US Stock capital gains |
| **US Dividends Report** | `.csv` | Schwab / Fidelity / Broker | Foreign dividends received and tax withheld u/s 1042-S |
| **US Schedule FA** *(Optional)* | `.json` | Pre-configured | Cost basis and peak value overrides for Schedule FA filing |
| **CG Exemptions** *(Optional)* | `.json` | Pre-configured | Custom exemption amounts claimed under Section 54F/54EC |

---

## 🛠️ Technical Requirements

* **Python**: Version `3.9` or higher.
* **Dependencies**: Minimal dependencies (only standard library + Flask web framework, PyPDF2 parser, and dateutil):
  - `Flask==3.0.3`
  - `PyPDF2==2.12.1`
  - `python-dateutil==2.8.2`

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
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser, enter your PAN & Date of Birth, upload your statements, and click **Process Tax Data**.
