"""Runs the trained models against a window of live sensor data."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch

from app import config
from app.data import WINDOW, pad_left, scale, trend
from app.models import LSTMAutoencoder, RULRegressor
from app.sensors import FEATURES, SENSOR_META, label


class Detector:
    def __init__(self, path: str | Path = config.DETECTOR_PATH):
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        n = len(FEATURES)
        self.ae = LSTMAutoencoder(n)
        self.ae.load_state_dict(ckpt["autoencoder"])
        self.rul = RULRegressor(n)
        self.rul.load_state_dict(ckpt["rul"])
        self.ae.eval()
        self.rul.eval()
        self.scaler = ckpt["scaler"]
        self.threshold = float(ckpt["threshold"])            # 99th pct healthy recon error
        self.sensor_err_mean = np.array(ckpt["sensor_err_mean"])
        self.sensor_err_std = np.array(ckpt["sensor_err_std"])
        self.trained_on = ckpt.get("device_name", "unknown")
        self.rul_scale = float(ckpt.get("rul_scale", 1.0))

    @torch.no_grad()
    def assess(self, history: pd.DataFrame) -> dict:
        """history: rows for ONE unit up to the current cycle (raw C-MAPSS columns)."""
        history = history.sort_values("cycle")
        x = pad_left(scale(history, self.scaler), WINDOW)
        xt = torch.from_numpy(x).unsqueeze(0)
        recon = self.ae(xt)[0].numpy()
        per_sensor = ((recon - x) ** 2).mean(axis=0)
        overall = float(per_sensor.mean())
        ratio = overall / self.threshold
        rul = max(0.0, float(self.rul(xt)[0]) * self.rul_scale)

        z = (per_sensor - self.sensor_err_mean) / np.maximum(self.sensor_err_std, 1e-6)
        window = history.tail(WINDOW)
        top = []
        for i in np.argsort(-z)[:3]:
            s = FEATURES[i]
            change, direction = trend(window[s].to_numpy(dtype=float))
            top.append({
                "sensor": s, "code": SENSOR_META[s][0], "label": label(s),
                "unit": SENSOR_META[s][2], "anomaly_z": round(float(z[i]), 2),
                "value_now": round(float(window[s].iloc[-1]), 3), "change_over_window": change,
                "direction": direction,
            })

        if rul < config.RUL_CRITICAL or ratio > 2.0:
            severity = "critical"
        elif rul < config.RUL_WARNING or ratio > 1.0:
            severity = "warning"
        else:
            severity = "normal"

        return {
            "unit": int(history["unit"].iloc[0]),
            "cycle": int(history["cycle"].iloc[-1]),
            "anomaly_ratio": round(ratio, 2),
            "predicted_rul_cycles": round(rul, 1),
            "severity": severity,
            "top_sensors": top,
        }
