#!/usr/bin/env python3
"""Launch the product-jobs web UI on http://localhost:5000"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(override=False)  # load .env but don't override vars already in the environment

from web.app import app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Starting product-jobs web UI → http://localhost:{port}")
    app.run(debug=True, port=port)
