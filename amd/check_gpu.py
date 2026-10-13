"""Run first in the AMD notebook. Confirms PyTorch sees the AMD GPU through ROCm.
Screenshot the output for your demo video and README."""
import platform
import subprocess

import torch

print("Python:", platform.python_version())
print("PyTorch:", torch.__version__)
print("ROCm/HIP version:", getattr(torch.version, "hip", None))
print("GPU available:", torch.cuda.is_available())  # ROCm exposes AMD GPUs through the torch.cuda API
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"  [{i}] {p.name}  {p.total_memory / 1e9:.0f} GB")
    a = torch.randn(4096, 4096, device="cuda")
    print("Matmul OK:", (a @ a).shape)
try:
    print(subprocess.run(["rocm-smi"], capture_output=True, text=True).stdout)
except FileNotFoundError:
    print("rocm-smi not on PATH (fine inside some containers)")
