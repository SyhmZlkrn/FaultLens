# FaultLens

**A maintenance copilot that tells a power station technician what is going wrong with a gas turbine, why, and what to do first, before it becomes a forced outage.**

Built for the AMD Developer Hackathon ACT III, Track 1: Intelligent Industry.

## The problem

Gas turbines degrade slowly. The warning signs are usually in the sensor data dozens of cycles before an alarm, but nobody has time to read 14 trends per unit per shift and cross-check them against a manual and years of incident reports. When the pattern is finally noticed, it is often too late for a planned fix, and a planned 9 hour wash turns into a 31 hour forced outage.

## What FaultLens does

1. **Detects** degradation early with an LSTM autoencoder and a remaining-useful-life model trained on AMD Instinct GPUs.
2. **Explains** which sensors are abnormal and how, in plain language.
3. **Finds the evidence**: the relevant manual sections and similar past incidents.
4. **Recommends** actions, least invasive first, every one cited.
5. **Checks itself**: code-level guardrails plus a second verifier pass that flags unsupported claims.
6. **Drafts a work order** that a person edits and approves. Nothing is raised automatically.

## Where AMD is used

| Part | AMD technology |
|---|---|
| Anomaly + RUL model training | PyTorch on ROCm, AMD Instinct GPU (AMD Developer Cloud notebook) |
| Embedding the manual and incident history | sentence-transformers on ROCm |
| Diagnosis and verification reasoning, live in the app | Open model served by AMD Token Factory |

See `artifacts/metrics.json` and `artifacts/llm_benchmark.json` for the GPU used, training time and inference latency.

## Architecture

```
sensor stream --> [LSTM autoencoder + RUL model]  (trained on AMD GPU)
                          |
                    anomaly, RUL, top sensors
                          |
             [retriever: manual + incidents]       (index built on AMD GPU)
                          |
              [diagnosis agent on AMD Token Factory]
                          |
          [guardrails in code] --> [verifier on AMD Token Factory]
                          |
         report + draft work order --> technician approves
```

## Quickstart

```bash
git clone https://github.com/SyhmZlkrn/faultlens && cd faultlens
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

## Reproducing the AMD steps

In an AMD AI Notebook (JupyterLab with ROCm), from the repo root:

```bash
pip install -r amd/requirements-rocm.txt
python amd/check_gpu.py
python -m amd.train --data-dir data/raw --epochs 30
python -m amd.build_index
python -m amd.benchmark_llm --runs 5
```

Download the data first, see `data/README.md`.

## Data and safety notes

- Sensor data: NASA C-MAPSS FD001, used as a stand-in for gas turbine telemetry.
- The troubleshooting guide and incident history are **synthetic**, written for this demo.
- FaultLens is advisory. It never acts on equipment, never suggests bypassing protections, and escalates to an engineer when severity is critical or confidence is low.

## License

MIT
