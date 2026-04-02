#!/usr/bin/env python3
"""Launch the product-jobs web UI on http://localhost:5000"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
_REPO_ROOT = Path(__file__).parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=False)

from web.app import app
from src.agent.claude import is_available

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    env_file = _REPO_ROOT / ".env"
    print(f"  .env file:  {'found' if env_file.exists() else 'NOT FOUND — create it from .env.example'}")
    import os
    key = os.getenv("ANTHROPIC_API_KEY", "")
    print(f"  API key:    {'set (' + key[:12] + '...)' if key else 'NOT SET'}")
    print(f"  AI features: {'enabled' if is_available() else 'disabled'}")
    print(f"Starting product-jobs web UI → http://localhost:{port}")
    app.run(debug=True, port=port)
