"""Download NASA C-MAPSS FD001 into data/raw (needed only to retrain).

    python -m scripts.download_data
"""
import io
import urllib.request
import zipfile

from app import config

URL = "https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip"
FILES = ("train_FD001.txt", "test_FD001.txt", "RUL_FD001.txt")


def main():
    raw = config.ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    print("Downloading", URL)
    outer = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL, timeout=300).read()))
    inner_name = next(n for n in outer.namelist() if n.endswith("CMAPSSData.zip"))
    inner = zipfile.ZipFile(io.BytesIO(outer.read(inner_name)))
    for name in FILES:
        (raw / name).write_bytes(inner.read(name))
        print("saved", raw / name)


if __name__ == "__main__":
    main()
