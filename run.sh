#!/bin/bash
# Start the expense report server with Homebrew library paths for WeasyPrint/Pango
cd "$(dirname "$0")"
source venv/bin/activate
DYLD_LIBRARY_PATH=/opt/homebrew/lib uvicorn main:app --reload --port 8000
