import sys
import os
import unittest
import json
import io

# Append parent directory to path so we can import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend import app

class TestMultiFormatUploads(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_mandatory_us_dividends_validation(self):
        # Sending request without US dividends should fail with 400 Bad Request
        payload = {
            "pan": "ABCDE1234F",
            "dob": "01011990",
            "fy": "2025-26"
        }
        response = self.app.post("/api/process", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data.decode("utf-8"))
        self.assertFalse(data["success"])
        self.assertIn("US Dividends statement file is mandatory", data["error"])

    def test_successful_parsing_with_mandatory_dividends(self):
        # Prepare sample files
        div_csv = io.BytesIO(b"Date,Action,Symbol,Description,Quantity,Price,Amount\n2025-06-15,Qualifying Dividend,AAPL,Apple Dividend,,,10.00\n")
        ind_csv_1 = io.BytesIO(b"Symbol,Quantity,Buy Date,Buy Price,Sell Date,Sell Price\nINFY,10,2023-01-01,1500,2025-01-01,2000\n")
        ind_csv_2 = io.BytesIO(b"Symbol,Quantity,Buy Date,Buy Price,Sell Date,Sell Price\nTCS,5,2023-05-01,3200,2025-01-01,3800\n")
        
        payload = {
            "pan": "ABCDE1234F",
            "dob": "01011990",
            "fy": "2025-26",
            "us_dividends_csv": (div_csv, "schwab_dividends.csv"),
            "indian_stock": [
                (ind_csv_1, "indian_stocks_1.csv"),
                (ind_csv_2, "indian_stocks_2.csv")
            ]
        }
        
        response = self.app.post("/api/process", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data.decode("utf-8"))
        self.assertTrue(data["success"])
        
        # Verify that both Indian stock files were successfully parsed and aggregated
        stock_sales = data["parsed_raw"]["stock_sales"]
        symbols = [s["symbol"] for s in stock_sales]
        self.assertIn("INFY", symbols)
        self.assertIn("TCS", symbols)
        
        # Verify US dividends were parsed
        us_divs = data["parsed_raw"]["us_dividends_csv"]
        self.assertEqual(len(us_divs), 1)
        self.assertEqual(us_divs[0]["symbol"], "AAPL")

if __name__ == "__main__":
    unittest.main()
