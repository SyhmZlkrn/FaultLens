FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# CPU torch keeps the image small. The trained models ship in artifacts/.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download the embedding model so the first request is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY . .
# Some hosts run the container as a non-root user; let it write work orders and read the model cache
RUN chmod -R a+rwX /app/data /app/.cache

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8501\")}/_stcore/health')"
CMD ["sh", "-c", "streamlit run app/ui.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
