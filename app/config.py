import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# AMD Token Factory (OpenAI-compatible). Copy the values from notebooks.amd.com/tokenfactory.
AMD_BASE_URL = os.getenv("AMD_BASE_URL", "")
AMD_API_KEY = os.getenv("AMD_API_KEY", "")
AMD_MODEL = os.getenv("AMD_MODEL", "")
# Other Token Factory models to try, in order, when the main one is busy. Comma separated.
AMD_FALLBACK_MODELS = [m.strip() for m in os.getenv("AMD_FALLBACK_MODELS", "").split(",") if m.strip()]
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "90"))

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

ARTIFACTS = ROOT / "artifacts"
DETECTOR_PATH = ARTIFACTS / "detector.pt"
INDEX_PATH = ARTIFACTS / "index.npz"
CHUNKS_PATH = ARTIFACTS / "chunks.jsonl"
METRICS_PATH = ARTIFACTS / "metrics.json"
LLM_BENCH_PATH = ARTIFACTS / "llm_benchmark.json"

DEMO_DATA = ROOT / "data" / "demo" / "demo_units.csv"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
WORKORDERS_PATH = ROOT / "data" / "workorders.jsonl"

# Agent rules (deterministic, not left to the LLM)
CONFIDENCE_ESCALATE_BELOW = 0.6
RUL_CRITICAL = 30
RUL_WARNING = 60
