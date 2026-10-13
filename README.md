# FaultLens

**A maintenance copilot that tells a power station technician what is going wrong with a gas turbine, why, and what to do first, before it becomes a forced outage.**

Built for the AMD Developer Hackathon ACT III, Track 1: Intelligent Industry.

## The problem

Gas turbines degrade slowly. The warning signs are usually in the sensor data dozens of cycles before an alarm, but nobody has time to read 14 trends per unit per shift and cross-check them against a manual and years of incident reports. When the pattern is finally noticed, it is often too late for a planned fix, and a planned 9 hour wash turns into a 31 hour forced outage.

## What FaultLens does

1. **Detects** degradation early with an LSTM autoencoder and a remaining-useful-life model.
2. **Explains** which sensors are abnormal and how, in plain language.
3. **Finds the evidence**: the relevant manual sections and similar past incidents.
4. **Recommends** actions, least invasive first, every one cited.
5. **Checks itself**: code-level guardrails plus a second verifier pass that flags unsupported claims.
6. **Drafts a work order** that a person edits and approves. Nothing is raised automatically.

## Where AMD is used

All reasoning in the live app runs on **AMD Token Factory**, AMD's hosted service for open models (OpenAI-compatible API).

| Step | Runs on |
|---|---|
| Diagnosis: reads the detector output and the evidence, writes causes, actions and a draft work order as strict JSON | AMD Token Factory (default `DeepSeek-V4-Flash`) |
| Verifier: a second pass that checks every claim against its cited evidence | AMD Token Factory |
| Fallback when a model is busy | Other AMD Token Factory models, set in `AMD_FALLBACK_MODELS` |

The small detector models and the search index are built on CPU and committed in `artifacts/`, so the app starts without a GPU. `artifacts/llm_benchmark.json` holds the measured Token Factory latency.

## Architecture

```
sensor stream --> [LSTM autoencoder + RUL model]
                          |
                    anomaly, RUL, top sensors
                          |
             [retriever: manual + incidents]
                          |
              [diagnosis agent on AMD Token Factory]
                          |
          [guardrails in code] --> [verifier on AMD Token Factory]
                          |
         report + draft work order --> technician approves
```

## Quickstart

```bash
git clone https://github.com/SyhmZlkrn/FaultLens && cd FaultLens
cp .env.example .env              # fill in AMD Token Factory values
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
streamlit run app/ui.py
```

Or with Docker:

```bash
docker build -t faultlens .
docker run -p 8501:8501 --env-file .env faultlens
```

Get the Token Factory values by signing in at [notebooks.amd.com/tokenfactory](https://notebooks.amd.com/tokenfactory). No card is needed.

## Retraining and benchmarking

The trained files are already in the repo. To rebuild them (about two minutes on a laptop CPU):

```bash
python -m scripts.download_data                      # NASA C-MAPSS FD001 into data/raw
python -m scripts.train --data-dir data/raw --epochs 30
python -m scripts.build_index                        # after editing data/knowledge
python -m scripts.benchmark_llm --runs 5             # Token Factory latency
```

Training uses a GPU automatically if PyTorch sees one.

## How FaultLens keeps the model honest

The model proposes; code checks; a person approves.

1. **Ground it.** The model gets every monitored sensor (direction, change, current value, how unusual), the window length, and the retrieved manual sections and incidents. It does not have to guess what it was not told.
2. **Check it in code** (`app/agent.py::apply_guardrails`, `app/checks.py`):
   - citations must be ids from the evidence it was given, and uncited causes lower confidence;
   - every sensor the report describes must match the detector's code, direction and numbers;
   - severity can only go up, critical always escalates with a P1 work order, low confidence escalates.
3. **Check it again with a second model call.** The verifier judges each cause and action against its cited text and the detector output; the verdict is computed in code from the failed checks.
4. **A person approves** the work order. Nothing is raised automatically.

Both calls run at temperature 0. `python -m scripts.eval_diagnosis` runs 10 fixed cases and counts uncited items, sensor mismatches, verifier failures and time; results are in `artifacts/eval.json`.

## Data and safety notes

- Sensor data: NASA C-MAPSS FD001, used as a stand-in for gas turbine telemetry.
- The troubleshooting guide and incident history are **synthetic**, written for this demo.
- FaultLens is advisory. It never acts on equipment, never suggests bypassing protections, and escalates to an engineer when severity is critical or confidence is low.

## License

MIT
