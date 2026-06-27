# Path-Index Answer-Set Comparison

Index materialisation necessarily makes some fully articulated P46-path answers available to the shortcut/index query. That deterministic consequence is not treated as the empirical finding. The empirical result is the magnitude, distribution, object-level recall, and structural depth of the index-recovered URI-level answers in this corpus.

The shortcut/index profile changes object-level conservation retrieval in this Ligatus corpus: 105 of 158 records have an answer-set gap and 53 do not.

| Query family | Records with gap | Index-recovered | Object-level recall | Dark records |
|---|---:|---:|---:|---:|
| e11_modification | 105 | 756 | 13.4% | 0 |
| condition | 95 | 433 | 0.0% | 95 |
| material | 24 | 90 | 83.8% | 21 |
| technique | 105 | 458 | 0.0% | 105 |

Object-level recall is the corpus-level count of URI answers from the fully-articulated-path profile divided by the count from the shortcut/index profile. Dark records have zero fully-articulated-path answers and at least one index-profile answer for the family.

## Documented Answer Space

| Query family | Directly visible | Index-recovered | Outside implemented paths | URI universe |
|---|---:|---:|---:|---:|
| e11_modification | 117 | 756 | 104 | 977 |
| condition | 0 | 433 | 401 | 834 |
| material | 467 | 90 | 245 | 802 |
| technique | 0 | 458 | 185 | 643 |

Counts in this table are distinct URIs per record, not raw predicate-statement counts.

## Top Records

| Rank | Record | Index-recovered answers |
|---:|---|---:|
| 1 | `bod:ArchBc4` | 34 |
| 2 | `bod:23197d1` | 33 |
| 3 | `bod:MSeMus65` | 32 |
| 4 | `bod:VetAld39` | 31 |
| 5 | `bod:ArchAf134` | 30 |
| 6 | `bod:AA106Art` | 28 |
| 7 | `bod:C822Line` | 28 |
| 8 | `loc:2966` | 27 |
| 9 | `tna:T20-1220` | 26 |
| 10 | `bod:MsAuctD417` | 25 |

## Conditions Outside the Index

| Classification | Conditions | Share |
|---|---:|---:|
| component_not_in_selected_p46_closure | 81 | 20.2% |
| component_p44_without_typed_e11_p31i | 320 | 79.8% |
| condition_attached_through_another_structure | 0 | 0.0% |
| another_e22_object_context | 0 | 0.0% |

## Unchanged Records

| Classification | Records | Share of unchanged |
|---|---:|---:|
| A_already_object_visible | 1 | 1.9% |
| B_no_eligible_indexed_content | 52 | 98.1% |
| C_component_evidence_duplicates_object_visible_uris | 0 | 0.0% |

## Interpretation

This result is limited to E11 modification, P44 condition, P126 material, and P32 technique retrieval through the configured P46 paths. It does not show that index profiles are generally better.

The fully-articulated-path profile preserves the source structure. Object-level discovery requires either explicit custom access indexes or query services that traverse the fully articulated P46 paths. The generated index graph contains no synthetic CRM P31i or P44 assertions.
