"""Train the anomaly autoencoder and the RUL model on an AMD GPU (ROCm).

Run from the repo root inside the AMD notebook:
    python -m amd.train --data-dir data/raw --epochs 30

Writes:
    artifacts/detector.pt        both models + scaler + thresholds
    artifacts/metrics.json       accuracy, training time, which GPU
    data/demo/demo_units.csv     held-out units for the live demo
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from app import config
from app.data import RUL_CAP, WINDOW, add_rul, fit_scaler, load_cmapss, make_windows, pad_left, scale
from app.models import LSTMAutoencoder, RULRegressor
from app.sensors import FEATURES

HOLDOUT_UNITS = 5
HEALTHY_RUL = 100  # windows with RUL >= this count as healthy for the autoencoder


def fit(model, loader, loss_fn, epochs, device, name):
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    model.to(device).train()
    for ep in range(epochs):
        total = 0.0
        for xb, yb in loader:
            xb, yb = xb.to(device, non_blocking=True), yb.to(device, non_blocking=True)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            total += loss.item() * len(xb)
        if ep % 5 == 0 or ep == epochs - 1:
            print(f"[{name}] epoch {ep + 1}/{epochs} loss {total / len(loader.dataset):.4f}")
    return model.eval()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=512)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    device_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    print(f"Training on: {device_name}")

    d = Path(args.data_dir)
    train = add_rul(load_cmapss(d / "train_FD001.txt"))
    holdout_ids = sorted(train["unit"].unique())[-HOLDOUT_UNITS:]
    demo = train[train["unit"].isin(holdout_ids)]
    train = train[~train["unit"].isin(holdout_ids)]

    scaler = fit_scaler(train)
    X, rul, _, _ = make_windows(train, scaler)
    healthy = X[rul >= HEALTHY_RUL]
    print(f"windows: {len(X)}  healthy: {len(healthy)}")

    # validation split of healthy windows for thresholds
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(healthy))
    cut = int(0.85 * len(idx))
    h_train, h_val = healthy[idx[:cut]], healthy[idx[cut:]]

    t0 = time.perf_counter()
    ae_loader = DataLoader(TensorDataset(torch.from_numpy(h_train), torch.from_numpy(h_train)),
                           batch_size=args.batch, shuffle=True)
    ae = fit(LSTMAutoencoder(len(FEATURES)), ae_loader, nn.MSELoss(), args.epochs, device, "autoencoder")

    rul_loader = DataLoader(TensorDataset(torch.from_numpy(X), torch.from_numpy(rul / RUL_CAP)),
                            batch_size=args.batch, shuffle=True)
    rul_model = fit(RULRegressor(len(FEATURES)), rul_loader, nn.MSELoss(), args.epochs, device, "rul")
    if device == "cuda":
        torch.cuda.synchronize()
    train_seconds = time.perf_counter() - t0

    # thresholds from held-out healthy windows
    with torch.no_grad():
        hv = torch.from_numpy(h_val).to(device)
        err = ((ae(hv) - hv) ** 2).mean(dim=1).cpu().numpy()  # (N, F)
    overall = err.mean(axis=1)
    threshold = float(np.percentile(overall, 99))

    # RUL accuracy on the official test set
    test = load_cmapss(d / "test_FD001.txt")
    true_rul = np.loadtxt(d / "RUL_FD001.txt")
    last = np.stack([pad_left(scale(g.sort_values("cycle"), scaler), WINDOW)
                     for _, g in test.groupby("unit")])
    with torch.no_grad():
        pred = rul_model(torch.from_numpy(last).to(device)).cpu().numpy() * RUL_CAP
    rmse = float(np.sqrt(np.mean((pred - np.minimum(true_rul, 125)) ** 2)))
    print(f"Test RUL RMSE: {rmse:.2f} cycles   anomaly threshold: {threshold:.4f}")

    config.ARTIFACTS.mkdir(exist_ok=True)
    torch.save({
        "autoencoder": {k: v.cpu() for k, v in ae.state_dict().items()},
        "rul": {k: v.cpu() for k, v in rul_model.state_dict().items()},
        "scaler": scaler, "threshold": threshold,
        "sensor_err_mean": err.mean(axis=0).tolist(), "sensor_err_std": err.std(axis=0).tolist(),
        "device_name": device_name, "rul_scale": RUL_CAP,
    }, config.DETECTOR_PATH)
    metrics = {"device": device_name, "rocm_hip": getattr(torch.version, "hip", None),
               "train_seconds": round(train_seconds, 1), "epochs": args.epochs,
               "train_windows": int(len(X)), "test_rul_rmse": round(rmse, 2),
               "anomaly_threshold": threshold, "holdout_units": [int(u) for u in holdout_ids]}
    config.METRICS_PATH.write_text(json.dumps(metrics, indent=2))

    config.DEMO_DATA.parent.mkdir(parents=True, exist_ok=True)
    demo.drop(columns=["rul"]).to_csv(config.DEMO_DATA, index=False)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
