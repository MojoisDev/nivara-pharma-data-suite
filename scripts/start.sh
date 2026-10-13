#!/bin/sh
set -eu
# Preserve existing Phase 1 data; initialize a deterministic demo only on an empty database.
pharma init
pharma seed
exec streamlit run dashboard/app.py --server.address=0.0.0.0 --server.port=8501
