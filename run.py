import time
import webbrowser
import threading
from backend import app

def open_browser():
    # Wait a moment for the Flask server to initialize
    time.sleep(1.5)
    url = "http://127.0.0.1:5000/"
    print(f"\n[Aatmanirbhar Tax] Opening browser at {url}...")
    webbrowser.open(url)

if __name__ == "__main__":
    print("\n[Aatmanirbhar Tax] Starting local e-filing calculation server...")
    print("Keep this terminal window open while using the software.")
    
    # Start browser-opening in a background thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Start Flask server
    app.run(host="127.0.0.1", port=5000, debug=False)
