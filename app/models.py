"""PyTorch models. Trained by scripts/train.py, run on CPU in the app."""
import torch
import torch.nn as nn


class LSTMAutoencoder(nn.Module):
    """Learns what a healthy window looks like. High reconstruction error = anomaly.
    Per-sensor error tells us WHICH sensors look abnormal, which is what the agent explains."""

    def __init__(self, n_features: int, hidden: int = 64, latent: int = 32):
        super().__init__()
        self.encoder = nn.LSTM(n_features, hidden, batch_first=True)
        self.to_latent = nn.Linear(hidden, latent)
        self.from_latent = nn.Linear(latent, hidden)
        self.decoder = nn.LSTM(hidden, hidden, batch_first=True)
        self.out = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h, _) = self.encoder(x)
        z = self.to_latent(h[-1])
        seq = self.from_latent(z).unsqueeze(1).repeat(1, x.size(1), 1)
        dec, _ = self.decoder(seq)
        return self.out(dec)


class RULRegressor(nn.Module):
    """Predicts remaining useful life (in cycles) from a sensor window."""

    def __init__(self, n_features: int, hidden: int = 64):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, num_layers=2, batch_first=True, dropout=0.2)
        self.head = nn.Sequential(nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1]).squeeze(-1)
