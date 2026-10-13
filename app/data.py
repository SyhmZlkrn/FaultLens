"""Shared data loading and windowing for training (on AMD GPU) and the app."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.sensors import FEATURES, RAW_COLUMNS

WINDOW = 30
RUL_CAP = 125  # piecewise-linear RUL target, standard for C-MAPSS


def load_cmapss(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", header=None)
    df = df.iloc[:, : len(RAW_COLUMNS)]
    df.columns = RAW_COLUMNS
    return df


def add_rul(df: pd.DataFrame, cap: int = RUL_CAP) -> pd.DataFrame:
    max_cycle = df.groupby("unit")["cycle"].transform("max")
    df = df.copy()
    df["rul"] = (max_cycle - df["cycle"]).clip(upper=cap)
    return df


def fit_scaler(df: pd.DataFrame) -> dict:
    return {
        "mean": df[FEATURES].mean().to_dict(),
        "std": df[FEATURES].std().replace(0, 1.0).to_dict(),
    }


def scale(df: pd.DataFrame, scaler: dict) -> np.ndarray:
    mean = np.array([scaler["mean"][f] for f in FEATURES], dtype=np.float32)
    std = np.array([scaler["std"][f] for f in FEATURES], dtype=np.float32)
    return ((df[FEATURES].to_numpy(dtype=np.float32) - mean) / std).astype(np.float32)


def pad_left(x: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Repeat the first row if a unit has fewer cycles than the window."""
    if len(x) >= window:
        return x[-window:]
    pad = np.repeat(x[:1], window - len(x), axis=0)
    return np.concatenate([pad, x], axis=0)


def make_windows(df: pd.DataFrame, scaler: dict, window: int = WINDOW):
    """Sliding windows per unit. Returns X (N, window, F), rul (N,), units, cycles."""
    xs, ruls, units, cycles = [], [], [], []
    for unit, g in df.groupby("unit"):
        g = g.sort_values("cycle")
        arr = scale(g, scaler)
        rul = g["rul"].to_numpy() if "rul" in g else np.full(len(g), np.nan)
        for end in range(window, len(g) + 1):
            xs.append(arr[end - window:end])
            ruls.append(rul[end - 1])
            units.append(unit)
            cycles.append(int(g["cycle"].iloc[end - 1]))
    return (np.stack(xs).astype(np.float32), np.array(ruls, dtype=np.float32),
            np.array(units), np.array(cycles))
