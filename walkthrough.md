# Walkthrough - Form 1042-S Coordinate Parsing & Tax Verification

We have successfully replaced the regex-based fallback for Form 1042-S in `parser.py` with a highly robust, coordinate-based cell value extraction engine using the `pdfplumber` module. The application calculations have been fully verified against the user's real tax documents.

---

## 📈 Updated Side-by-Side Regime Comparison (FY 2025-26)

Opting for the **New Tax Regime** remains highly recommended. It results in a tax refund of **₹9,21,945** instead of a tax payment due of **₹9,06,833**, yielding a net financial advantage of **₹18,28,778**.

| Income Component / Tax Particulars | Old Regime | New Regime | Difference (Old - New) |
| :--- | :--- | :--- | :--- |
| **Gross Salary** | ₹4,73,44,802 | ₹4,73,44,802 | ₹0 |
| **Standard Deduction (Sec 16(ia))** | ₹50,000 | ₹75,000 | -₹25,000 |
| **Professional Tax (Sec 16(ii))** | ₹16 | ₹0 | +₹16 |
| **Net Salary Income** | ₹4,72,94,786 | ₹4,72,69,802 | +₹24,984 |
| **US Dividend Income (Sec 56(1))** | ₹10,48,228 | ₹10,48,228 | ₹0 |
| **US Bank Interest (Sec 56(1))** | ₹7,786 | ₹7,786 | ₹0 |
| **US Stock STCG (taxed at slab)** | ₹5,87,301 | ₹5,87,301 | ₹0 |
| **Taxable Slab Income** | **₹4,89,38,101** | **₹4,89,13,118** | **+₹24,983** |
| **Special Capital Gains (LTCG 112)** | ₹8,70,000 | ₹8,70,000 | ₹0 |
| **Total Taxable Income** | **₹4,98,08,101** | **₹4,97,93,118** | **+₹24,983** |
| **Basic Slab + Special Gains Tax** | ₹1,46,02,361 | ₹1,43,65,366 | +₹2,36,995 |
| **Add: Surcharge** | **₹36,16,540** | **₹21,54,805** | **+₹14,61,735** |
| **Add: Cess (4% on Tax + Surcharge)** | **₹7,28,756** | **₹6,60,807** | **+₹67,949** |
| **Total Tax Before Relief** | **₹1,89,47,657** | **₹17,180,978** | **+₹17,66,679** |
| **Less: Double Tax Relief (Sec 90)** | ₹2,13,705 | ₹2,13,705 | ₹0 |
| **Net Tax Payable** | **₹1,87,33,953** | **₹1,69,67,273** | **+₹17,66,679** |
| **Add: Interest u/s 234B** | **₹33,788** | **₹0** | **+₹33,788** |
| **Add: Interest u/s 234C** | **₹28,310** | **₹0** | **+₹28,310** |
| **Total Tax, Surcharge & Interest** | **₹1,87,96,051** | **₹1,69,67,273** | **+₹18,28,778** |
| **Less: TDS Credited (Form 16)** | ₹1,78,89,218 | ₹1,78,89,218 | ₹0 |
| **Less: Advance Tax Paid** | ₹0 | ₹0 | ₹0 |
| **Final Tax Status** | **₹9,06,833 (Due)** | **-₹9,21,945 (Refund)** | **+₹18,28,778** |

---

## 🛠️ Implementation Details

### 1. `pdfplumber` Coordinate-Based Form 1042-S Parser
- **Proximity-Based Search**: Implemented a spatial layout parsing algorithm in `parser.py` that utilizes word-level coordinates instead of fragile text regex patterns.
- **Directional Rules**:
  - **Gross income** and **Income code**: Value cell is located strictly **below** the bounding coordinates of the label block (`direction="below"`). This prevents matching irrelevant numbers on the same row, such as box indices.
  - **Federal tax withheld**: Value cell is located to the **right** in the same row (`direction="right"`).
- **Correct Income Code Classification**: Captures standard code `06` and code `52` as foreign dividends, and codes `01`/`29`/`30` as bank interest.

### 2. Verified Parsing of Schwab & Fidelity PDFs
- **Schwab 1**: Interest (Code `01`, Gross `$40.0`, Tax `$6.0`), Dividend (Code `06`, Gross `$9023.0`, Tax `$2256.0`).
- **Schwab 2**: Dividend (Code `52`, Gross `$293.0`, Tax `$73.0`).
- **Fidelity**: Interest (Code `01`, Gross `$5.0`, Tax `$0.0`), Dividend (Code `06`, Gross `$3333.0`, Tax `$833.0`).
