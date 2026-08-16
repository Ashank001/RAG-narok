#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}