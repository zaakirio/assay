#!/usr/bin/env python3
"""Download the SROIE 2019 test split and convert it into assay's document
and truth format under data/sroie/golden/.

The dataset is the ICDAR 2019 Robust Reading Challenge on Scanned Receipts
OCR and Information Extraction (SROIE), task 3: 361 real scanned receipts
with provided OCR text and four ground-truth key fields (company, date,
address, total).
Source: the jsdnrs/ICDAR2019-SROIE mirror on Hugging Face (CC-BY-4.0),
pinned to a specific revision so the bytes cannot change under us.
The data is downloaded on demand and is not redistributed in this repo.

Usage:
    uv run --extra sroie python scripts/fetch_sroie.py [--limit N] [--force]
"""

import argparse
import sys
import urllib.request
from pathlib import Path

REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"
URL = ("https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE/resolve/"
       f"{REVISION}/data/test-00000-of-00001.parquet")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "sroie" / "raw" / "sroie-test.parquet"
OUT = PROJECT_ROOT / "data" / "sroie" / "golden"


def download(force: bool):
    if RAW.exists() and not force:
        print(f"Using cached {RAW} ({RAW.stat().st_size / 1e6:.0f} MB); --force redownloads")
        return
    RAW.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading SROIE test parquet (~216 MB, revision {REVISION[:12]})...")
    tmp = RAW.with_suffix(".part")
    urllib.request.urlretrieve(URL, tmp)
    tmp.rename(RAW)
    print(f"Saved {RAW}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None,
                    help="convert only the first N receipts (sorted by key)")
    ap.add_argument("--force", action="store_true", help="redownload the parquet")
    args = ap.parse_args()

    try:
        from assay.sroie import convert_parquet
    except ModuleNotFoundError as e:
        sys.exit(f"Missing dependency ({e.name}). Run via: "
                 "uv run --extra sroie python scripts/fetch_sroie.py")

    download(args.force)
    n = convert_parquet(RAW, OUT, limit=args.limit)
    print(f"Converted {n} receipts into {OUT}")
    print("Run the eval arm with: uv run assay eval --dataset sroie --limit 50")


if __name__ == "__main__":
    main()
