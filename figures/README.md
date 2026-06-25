# Publication figures

This folder now contains only the three figures needed to explain the Ligatus
benchmark method and result.

## Figure 1 — Ligatus benchmark pipeline

`tex/figure01_benchmark_pipeline.tex`

Starts from already encoded Ligatus CIDOC CRM RDF and shows the benchmark-added
stages: structural adaptation, episode-boundary policy, generated persistent
and segmented comparison profiles, paired retrieval scopes, and answer-set
measurement.

## Figure 2 — Persistent versus segmented retrieval

`tex/figure02_current_vs_lineage_query.tex`

Shows the conceptual modelling contrast. The same treatment evidence is local
to one identity in the persistent profile, but distributed across an E81
identity sequence in the segmented profile. The figure also shows why a
current-identity-local query can differ while a lineage-wide query remains
stable.

## Figure 3 — Boundary-policy sensitivity and LOSO stability

`tex/figure03_ordering_policy_sensitivity.tex`

Reads generated CSV data from the Ligatus machine outputs and plots the
current-local gap rate under the three reported boundary policies. In
this run, treatment-history and modification-retrieval gaps affect the same
records for each policy, so the figure reports the shared affected-record rate
once instead of duplicating equal bars. Error bars are computed as
leave-one-record-out standard deviations for each boundary policy.

## Data preparation

Run from the repository root:

```bash
python figures/prepare_publication_data.py
```

The script reads:

- `outputs/ligatus/results/manifest.json`
- `outputs/ligatus/results/episode_order_audit.csv`
- `outputs/ligatus/results/ordering_policy_metrics.csv`
- `outputs/ligatus/results/leave_one_record_out.csv`

and writes:

- `figures/data/ligatus_figure_macros.tex`
- `figures/data/boundary_policy_sensitivity.csv`
- `figures/data/boundary_policy_loso.csv`
- `figures/data/source_semantics_loso.csv`

## Compile

```bash
make figures
```

This regenerates the figure data and compiles the three standalone PDFs under
`figures/generated/`.
