"""Measure latency and throughput of the AMD Token Factory model on a real diagnosis-sized prompt.
Results go to artifacts/llm_benchmark.json and show up in the app's AMD panel.

    python -m amd.benchmark_llm --runs 5
"""
import argparse
import json
import statistics
import time

from app import config
from app.llm import complete

PROMPT = ("A gas turbine shows T30 (HPC outlet temperature) rising 1.4 degR, P30 falling 0.6 psia and "
          "W31 coolant bleed falling over 30 cycles. In about 150 words, list the two most likely causes "
          "and the first inspection step for each.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    lat, tps, used = [], [], []
    for i in range(args.runs):
        meta = {"calls": 0, "latency_s": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
        t0 = time.perf_counter()
        complete([{"role": "user", "content": PROMPT}], meta, temperature=0.2, max_tokens=400)
        dt = time.perf_counter() - t0
        out = meta["completion_tokens"]
        lat.append(dt)
        tps.append(out / dt if dt else 0)
        used.append(meta["model"])
        print(f"run {i + 1}: {meta['model']}  {dt:.2f}s  {out} tokens  {out / dt:.1f} tok/s")
    result = {"model": statistics.mode(used), "requested_model": config.AMD_MODEL, "runs": args.runs,
              "median_latency_s": round(statistics.median(lat), 2),
              "median_tokens_per_s": round(statistics.median(tps), 1)}
    config.ARTIFACTS.mkdir(exist_ok=True)
    config.LLM_BENCH_PATH.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
