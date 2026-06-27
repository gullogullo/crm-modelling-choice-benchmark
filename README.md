# Ligatus Path-Index Answer-Set Comparison

This dependency-free experiment compares one object-level conservation query
over two application profiles of the same Ligatus RDF/XML records:

- `fully_articulated_path_profile` preserves the source graph unchanged;
- `shortcut_index_profile`, called the shortcut/index profile in the report,
  preserves the source graph and adds custom access-index triples in a separate
  named graph.

The index graph uses only:

- `benchmark:indexModification` for E11 activities reached through
  `P46+ / P31i`;
- `benchmark:indexCondition` for conditions reached through the constrained
  `P46+ / P31i-to-typed-E11 / P44` rule.

It does **not** generate CRM P31i or P44 statements. Index-recovered answers are
the URI-level set difference between the shortcut/index profile and the
fully-articulated-path profile for the same record and query family.

The code requires Python 3.10 or later and only the Python standard library.
PDF export is optional and uses `rsvg-convert` from librsvg.

## Reproduce

Fetch the pinned Ligatus source corpus:

```bash
make fetch
```

Run the experiment, analysis, and figure generation:

```bash
make run
```

Run tests and optionally export PDFs:

```bash
make test
make pdf
```

To use an existing source checkout:

```bash
make run SOURCE_DIR=/path/to/board-pilot-data
```

## Rules and Semantics

The complete machine-readable specification is in `config/index_rules.json`.
The described object is selected structurally as the E22 node with the largest
transitive P46 component closure, with production evidence and lexical URI used
only as deterministic tie-breakers. Record identifiers and labels never choose
an index rule.

The condition index intentionally includes only P44 conditions on components
that also have a P31i link to a typed E11 Modification. This Ligatus-specific
task constraint is explicit and audited; it is not a CIDOC CRM entailment.

Answer comparison uses URI-level sets within each record and family. Labels are
reported for readability but never used to merge answers. Every recovered URI
retains its supporting component, E11, P46 depth, index triple, and rule ID.

## Principal Outputs

- `outputs/path_profile_answer_set_comparison.csv`: profile answer sets and
  answer-set gaps by record.
- `outputs/index_recovered_answer_trace.csv`: one row per index-recovered URI.
- `outputs/index_recovery_summary_stats.csv`: corpus totals and top records.
- `outputs/index_recovery_family_stats.csv`: family-level distributions.
- `outputs/corpus_level_recall.csv` and `outputs/record_level_recall.csv`:
  object-level recall and dark-record diagnostics.
- `outputs/documented_answer_space.csv`: directly visible, index-recovered, and
  documented-but-outside-path answers.
- `outputs/condition_outside_path_diagnostic.csv`: one row for each condition
  outside the implemented index paths.
- `outputs/condition_outside_path_summary.csv`: the requested four-category
  breakdown of those conditions.
- `outputs/unaffected_record_diagnostic.csv`: classification of all unchanged
  records as already visible, without eligible content, or duplicate-only.
- `outputs/unaffected_record_summary.csv`: counts for those classifications.
- `outputs/p46_path_depth_distribution.csv`: index-recovered answers by minimum
  P46 depth.
- `outputs/predicate_inventory.csv`: source CRM predicates inside and outside
  the task scope.
- `outputs/fully_articulated_path_profile.nq`: unchanged source triples in
  per-record named graphs.
- `outputs/index_profile.nq`: source graphs plus custom index triples in
  separate index named graphs.
- `outputs/index_rules.json`: exact rules copied into the result package.
- `outputs/scope_note.md` and `outputs/report.md`: scope and restrained results.

## Figures

- `outputs/analysis/per_record_answer_composition.svg` and `.pdf`;
- `outputs/analysis/documented_answer_space.svg` and `.pdf`;
- `figures/single_record_shortcut_comparison.svg` and `.pdf`.

The empirical conclusion is limited to this corpus and these paths: the
shortcut/index profile changes object-level conservation retrieval in the
Ligatus board-reattachment corpus. It does not establish that access indexes are
generally preferable to fully articulated querying.
