#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def fetch(config_path: Path, destination: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected_root = config["expected_archive_root"]
    target = destination / expected_root
    if target.exists():
        return target

    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{expected_root}.zip"
    request = urllib.request.Request(
        config["repository_archive"],
        headers={"User-Agent": "ligatus-path-index-benchmark/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        with archive.open("wb") as handle:
            shutil.copyfileobj(response, handle)

    with zipfile.ZipFile(archive) as zipped:
        names = [PurePosixPath(name) for name in zipped.namelist()]
        if any(path.is_absolute() or ".." in path.parts for path in names):
            raise RuntimeError("archive contains an unsafe path")
        roots = {path.parts[0] for path in names if path.parts}
        if roots != {expected_root}:
            raise RuntimeError(
                f"unexpected archive roots: {sorted(roots)}; "
                f"expected {expected_root}"
            )
        zipped.extractall(destination)
    archive.unlink()
    return target


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Fetch the pinned Ligatus corpus.")
    parser.add_argument(
        "--config", type=Path, default=root / "config" / "source.json"
    )
    parser.add_argument(
        "--destination", type=Path, default=root / "data" / "external"
    )
    args = parser.parse_args()
    print(fetch(args.config, args.destination))


if __name__ == "__main__":
    main()
