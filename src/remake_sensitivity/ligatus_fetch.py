from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

import yaml


def fetch(config_path: Path, destination: Path) -> Path:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "board-pilot-data.zip"
    request = urllib.request.Request(
        config["repository_archive"],
        headers={"User-Agent": "remake-ontology-eval/ligatus-fetch"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        with archive.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(destination)
        roots = {
            name.split("/", 1)[0]
            for name in zipped.namelist()
            if "/" in name
        }
    archive.unlink()
    if len(roots) != 1:
        raise RuntimeError(f"unexpected archive roots: {sorted(roots)}")
    return destination / next(iter(roots))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data/ligatus/board_pilot.yaml"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("data/external/ligatus"),
    )
    args = parser.parse_args()
    print(fetch(args.config, args.destination))


if __name__ == "__main__":
    main()
