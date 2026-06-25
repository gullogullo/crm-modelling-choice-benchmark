# Data Sources

## Keyboard Instruments

The YAML records under `data/records/` and the configuration/query files under
`data/e11e81/` are retained as the keyboard-instruments benchmark dataset and
pipeline inputs.

This cleaned repo does not present a results section from the keyboard path.
The files are kept so the developed pipeline remains available.

## Ligatus Linked Conservation Data

The benchmark uses the public Linked Conservation Data board-pilot repository:

- Project: <https://www.ligatus.org.uk/lcd/node/255>
- Repository: <https://github.com/linked-conservation-data/board-pilot-data>
- Commit: `762213835c6c6cdd20fcadb4ded90119ae3ee147`

The archive is downloaded by `remake_sensitivity.ligatus_fetch`. Downloaded RDF
is excluded from the repository. The retained result files are derived from the
158 RDF records in the board reattachment corpus.

The benchmark preserves the structured CIDOC CRM E11 hierarchy, E3 conditions,
date boundaries, P32 techniques, P126 materials, and modified targets used by
the reported retrieval tasks.

## Generated Outputs

The committed outputs under `outputs/ligatus/results/` are small reference
files for inspection and figure generation. Profile graphs and plots can be
regenerated from the pinned input archive.
