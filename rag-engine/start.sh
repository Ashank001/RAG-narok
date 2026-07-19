#!/bin/sh
# RAG Engine startup script

# 1. Install/update Python dependencies
# Using --upgrade ensures pymongo and cryptography stay current for Atlas TLS compatibility
pip install --upgrade pip --quiet
pip install -r requirements.txt

# 2. Start FastAPI server in the background
uvicorn main:app --host 0.0.0.0 --port 8000 &

# 3. Start Celery worker in the foreground (keeps the container alive)
python -m celery -A worker worker --loglevel=info
