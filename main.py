"""Entry point: runs the FastAPI dashboard (which also launches the Telegram bot).

Local:   python main.py
Railway: uvicorn web.app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, reload=False)
