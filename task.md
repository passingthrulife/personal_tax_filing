# Tasks

- [x] Run E2E dashboard validations and update issues.md tracking status
- [x] Convert Active Regime Slab Breakdown to Lakhs formatting (e.g. 4L, 8L) in calculator.py
- [x] Implement Section 10(13A) HRA Exemption Calculator and sync local inputs to Karthik_HRA_Inputs.json
- [x] Add HRA inputs card to templates/index.html sidebar and map inputs to payload serialization
- [x] Render calculated HRA exemption in Schedule S tab as a detailed sub-row
 in `templates/index.html`
- [x] Correct Form 16 regex parsing u/s 17(2) perquisites, 24(b) housing loss, and TDS
- [x] Upgrade brokerage CSV parsing to handle dynamic header row locations, custom column naming, and automatic total-to-unit value conversions
- [x] Update and run verification tests (`test_verify.py` in scratch)
- [x] Update walkthrough details in `walkthrough.md`
- [x] Implement Individual Surcharge logic with 15% capping on Capital Gains & Dividends
- [x] Implement Sections 234B and 234C interest calculations on assessed tax shortfalls
- [x] Display Surcharge, Cess, and Sections 234B/C interest rows in side-by-side comparison table
- [x] Show final Net Tax Due or Refund status after deducting TDS and Advance Tax
- [x] Resolve Form 16 parsing NameError bug and correct regex newline matching constraints for TDS/Perquisites
- [x] Add planned enhancements (Section 54, HRA, Schedule AL, Crypto) to `issues.md` roadmap
