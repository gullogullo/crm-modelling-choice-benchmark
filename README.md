# CIDOC CRM Modelling-Choice Benchmark

This repository contains two CIDOC CRM modelling-choice benchmark paths:

- the keyboard-instruments dataset and pipeline under `data/e11e81/`,
  `data/records/`, and the general benchmark modules in `src/remake_sensitivity/`;
- the Ligatus boundary-policy sensitivity run whose current results are
  reported under `outputs/ligatus/`.

The public repo excludes Getty-specific data/code and generated paper drafts.

## Results

The concise results text is in `outputs/ligatus/results.md`. The underlying
machine-readable files are in `outputs/ligatus/results/`.

Core result:

| Boundary policy | Episodes | History/E11 gap | Property gap | LOSO |
|---|---:|---:|---:|---:|
| `all_roots_split` | 102 / 56 / 0 | 56/158 (35.4%) | 6/158 each | 35.0%-35.7% |
| `source_semantics` | 147 / 11 / 45 | 11/158 (7.0%) | 0/158 each | 6.4%-7.0% |
| `dated_only` | 157 / 1 / 55 | 1/158 (0.6%) | 0/158 each | 0.0%-0.6% |

## Layout

```text
src/remake_sensitivity/       Ligatus adapter, fetcher, and benchmark runner
data/e11e81/                  keyboard-instruments benchmark configuration
data/records/                 keyboard-instruments source records
data/ligatus/                 source and ordering-policy manifests
outputs/ligatus/results/      reference machine-readable result files
figures/                      retained publication figure sources and data
tests/                        keyboard and Ligatus regression tests
```

Downloaded Ligatus RDF is not committed. The source archive and commit are
pinned in `data/ligatus/board_pilot.yaml`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
pytest -q
```

Runtime dependencies are `rdflib`, `PyYAML`, and `networkx`. Figure generation
requires a LaTeX installation with TikZ and `pgfplots`.

## Keyboard-Instruments Pipeline

The keyboard-instruments dataset and pipeline are retained for development and
future comparison work. No public results section is claimed from this path in
the cleaned repo.

```bash
make keyboard
```

Equivalent command:

```bash
python -m remake_sensitivity.run \
  --config data/e11e81/config.yaml \
  --allow-frozen-rerun
```

## Reproduce

```bash
make fetch-ligatus
make ligatus
```

Equivalent commands:

```bash
python -m remake_sensitivity.ligatus_fetch \
  --config data/ligatus/board_pilot.yaml \
  --destination data/external/ligatus

python -m remake_sensitivity.ligatus_benchmark \
  --config data/ligatus/board_pilot.yaml \
  --data-dir data/external/ligatus/board-pilot-data-762213835c6c6cdd20fcadb4ded90119ae3ee147 \
  --output-root outputs
```

The benchmark writes CSV/JSON result files, profile graphs, two diagnostic SVGs,
and `outputs/ligatus/results.md`.

## Figures

```bash
make figures
```

The `figures/` folder is retained for now. It uses the result files under
`outputs/ligatus/results/` to prepare figure data.
