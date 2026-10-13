# Data

## Sensor data: NASA C-MAPSS (FD001)

Turbofan engine degradation simulation from NASA's Prognostics Center of Excellence. Used here as a stand-in for gas turbine telemetry.

Only needed to retrain. Run `python -m scripts.download_data`, which fetches the NASA Prognostics Data Repository archive and saves these three files into `data/raw/`:
   - `train_FD001.txt`
   - `test_FD001.txt`
   - `RUL_FD001.txt`

`data/raw/` is gitignored. `scripts/train.py` exports the held-out demo units to `data/demo/demo_units.csv`, which IS committed so the deployed app works without the raw data.

## Knowledge base: SYNTHETIC

`knowledge/gt_troubleshooting_guide.md` and `knowledge/incidents.jsonl` were written for this demo. They are not from any manufacturer or utility. Edit or extend them freely; re-run `python -m scripts.build_index` after changes.

Manual sections must use headings like `## [MAN-11] Title` so the indexer can split and cite them.
