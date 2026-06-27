# Scope Note

This experiment evaluates one task-defined object-level conservation query. It
does not test all CIDOC CRM paths or all information present in Ligatus.

## Included Paths

- `P46_is_composed_of+ / P31i_was_modified_by`: fully articulated path from
  the described object through one or more P46 components to E11 Modification.
- `P46_is_composed_of+ / P44_has_condition`: fully articulated path from the
  described object through one or more P46 components to condition state.
- `benchmark:indexModification`: custom E11 access index generated from the
  P46/P31i source path.
- `benchmark:indexCondition`: custom condition access index generated from the
  constrained P46/P31i/P44 source path.
- `P126_employed`: material reached from a directly visible or indexed E11.
- `P32_used_general_technique`: technique reached from a directly visible or
  indexed E11.

The configured predicate URIs are:

```json
{
  "composition": "http://www.cidoc-crm.org/cidoc-crm/P46_is_composed_of",
  "condition": "http://www.cidoc-crm.org/cidoc-crm/P44_has_condition",
  "index_condition": "https://w3id.org/ligatus-object-scope-benchmark/indexCondition",
  "index_modification": "https://w3id.org/ligatus-object-scope-benchmark/indexModification",
  "material": "http://www.cidoc-crm.org/cidoc-crm/P126_employed",
  "modified_by": "http://www.cidoc-crm.org/cidoc-crm/P31i_was_modified_by",
  "technique": "http://www.cidoc-crm.org/cidoc-crm/P32_used_general_technique"
}
```

## Excluded Paths

All other CIDOC CRM predicates are outside the competency query, including
production, feature, temporal, type, measurement, attribution,
and activity-hierarchy paths. Their presence is inventoried rather than
interpreted. This keeps the comparison tied to the stated conservation task.

The source contains 43 other CRM predicates not evaluated here. See
`predicate_inventory.csv` for their URIs and corpus counts.

## Index Semantics

The index graph uses only the custom predicates `benchmark:indexModification`
and `benchmark:indexCondition`. It never generates CRM P31i or P44 assertions.
The index triples are retrieval metadata justified by fully articulated source
paths; they do not state that an E11 directly modified the described object or
that a component condition is literally a condition of the whole object.

The condition index rule is intentionally narrower than simple P46/P44
reachability. A component condition is indexed only when that same component
has a P31i link to a typed E11 Modification. This is a Ligatus task constraint
that limits the index to treatment-relevant component contexts. Conditions
excluded by this constraint are enumerated in
`condition_outside_path_diagnostic.csv` and summarized in
`condition_outside_path_summary.csv`.

## Deduplication

Answer comparison uses URI-level sets within each record and query family.
Labels are reported but never used to merge answers. When several source paths
support the same answer URI, the trace retains all supporting components, P46
depths, and E11 activities in JSON arrays. An index-recovered answer is the
URI-level set difference between the shortcut/index profile and the
fully-articulated-path profile for one record and query family.
