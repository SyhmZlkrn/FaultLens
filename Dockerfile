FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# CPU torch keeps the image small. The trained models ship in artifacts/.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download the embedding model so the first request is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY . .

EXPOSE 8501
CMD ["sh", "-c", "streamlit run app/ui.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
