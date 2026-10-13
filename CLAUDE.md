# FaultLens: notes for Claude Code

## What this is
Hackathon project for the AMD Developer Hackathon ACT III (lablab.ai), Track 1 "Intelligent Industry". Online build ends 18 Oct 2026. Solo or small team, so favour working and demoable over clever.

FaultLens is a maintenance copilot for gas turbine units at a power station. It watches sensor data, flags degradation, explains it in plain language with citations to the manual and past incidents, and drafts a work order that a person approves.

## Hard rules (do not break these)
1. **AMD must power the product.** The runtime LLM is the AMD Token Factory (OpenAI-compatible, configured in `.env`). Do not switch the product's reasoning to Anthropic, OpenAI or any other provider. Token Factory is the only AMD component (owner's decision, 14 Oct; the event requires only Token Factory). The detector and index are built on CPU. Never claim ROCm, Instinct or AMD GPU training anywhere.
2. **Never commit secrets.** Keys live in `.env` only. `.env.example` has empty values.
3. **No real company data.** Sensor data is NASA C-MAPSS. Manual and incidents in `data/knowledge/` are synthetic and labelled as such. Never add anything from a real employer.
4. **The LLM proposes, code enforces, a person approves.** Safety rules live in `app/agent.py::apply_guardrails`, not only in prompts. Do not remove the human approval step.
5. Keep it MIT licensed and the README runnable from a clean clone.

## Layout
```
app/            runtime (CPU): detector, retriever, LLM client, agent, Streamlit UI
  prompts/      system.md (diagnosis agent), verifier.md (second-pass checker)
scripts/        download_data, train, build_index (CPU is fine), benchmark_llm (Token Factory)
data/knowledge  synthetic manual (MAN-xx sections) and incidents (INC-xxxx-xxx)
data/demo       held-out units exported by scripts/train.py for the live demo
artifacts/      detector.pt, index.npz, chunks.jsonl, metrics.json, llm_benchmark.json
tests/          pure-Python tests, no network or GPU
docs/           demo script
```

## Commands
- Tests: `pytest -q`
- App: `streamlit run app/ui.py`
- Retrain, from repo root: `python -m scripts.download_data`, `python -m scripts.train --epochs 30`, `python -m scripts.build_index`, `python -m scripts.benchmark_llm`
- Docker: `docker build -t faultlens . && docker run -p 8501:8501 --env-file .env faultlens`

## Conventions
- Python 3.11, type hints, small functions. No LangChain or other heavy frameworks; plain OpenAI client is enough.
- Any new LLM output field must be added to the pydantic `Report` schema AND to `prompts/system.md`.
- New manual sections need a `## [MAN-xx] Title` heading. Re-run `scripts.build_index` after editing knowledge.
- The UI must never crash during a demo: catch errors at the UI boundary and show a clear message.
- Writing in the UI and docs: plain, natural English. Avoid em dashes.

## Milestones
1. [x] Token Factory call works (`python -m scripts.benchmark_llm --runs 1`)
2. [x] Detector trained and index built (CPU), artifacts committed
3. [ ] End-to-end diagnosis in the UI for GT-97 (normal, warning at 149, critical at 176)
4. [ ] Tests pass, Docker image runs, deployed with public URL
5. [ ] Demo video, slides, submission

## Nice to have (only after milestone 4)
- Before/after metric panel: time to diagnosis, cycles of early warning vs INC-2026-003
- Evolus partner track: route report PDFs through an Evolus document extractor, serve the agent model with vLLM on AMD Developer Cloud
