# Python application image — shared by mcp-server, app-server, and db-init.
#
# The CMD is intentionally omitted; each service in docker-compose.yml
# supplies its own command:
#
#   mcp-server:  python -m mcp_server
#   app-server:  python -m api
#   db-init:     sh -c "python -m db.migrate && python -m db.seed"

FROM python:3.11-slim

WORKDIR /app

# System build tools required by some native extensions (e.g. asyncpg, tokenizers).
# curl is included so the mcp-server healthcheck can use it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependency installation (cached layer) ────────────────────────────────────
# requirements.txt is copied first so this layer is only invalidated when
# dependencies change, not every time source code changes.
COPY requirements.txt ./

# Install everything from requirements.txt, then add packages that are in
# pyproject.toml but not in requirements.txt.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        "langchain>=0.2.0" \
        "langchain-huggingface>=1.2.2" \
        "sentence-transformers>=5.5.1" \
        "textual>=8.2.7" \
        "uvicorn[standard]>=0.29.0"

# ── Pre-download HuggingFace embedding model ─────────────────────────────────
# Baking the model into the image avoids a slow download at container startup,
# which would otherwise cause the healthcheck to time out.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5'); print('Model cached.')"

# ── Application source ────────────────────────────────────────────────────────
COPY . .
