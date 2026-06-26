# Results

The external Ligatus evaluation used 158 RDF records from the Linked Conservation Data board reattachment corpus. The adapter extracted 977 E11 Modification events. Of the 158 records, 102 had one source root E11 activity. The remaining 56 records had two source roots. Under `source_semantics`, 10 two-root records were split by the previous repair/main conservation event label rule, 1 was split by dates, and 45 were collapsed because no supported order was found. This produced 147 one-episode records, 11 two-episode records, and 169 treatment episode identifiers.

Under `source_semantics`, current-identity-local treatment history and E11 retrieval differed between the persistent and segmented profiles in the same 11 of 158 records, or 7.0%. In those records, the segmented current-identity-local treatment query lacked one earlier episode identifier, and the E11 query lacked one earlier E11 URI. The lineage-wide treatment-history and E11 answer sets were identical across the two profiles, with Jaccard similarity 1.000. In the persistent profile, current-identity-local and lineage-wide answers did not diverge.

For treatment history and E11 retrieval, the same records diverged under each boundary policy. Table 1 therefore reports these two query families in a single gap column. The three property-retrieval tasks are grouped because condition, treatment material, and technique retrieval had the same divergent-record count within each policy.

| Boundary policy | Episodes | History/E11 gap | Property gap | LOSO |
|---|---:|---:|---:|---:|
| `all_roots_split` | 102 / 56 / 0 | 56/158 (35.4%) | 6/158 each | 35.0%-35.7% |
| `source_semantics` | 147 / 11 / 45 | 11/158 (7.0%) | 0/158 each | 6.4%-7.0% |
| `dated_only` | 157 / 1 / 55 | 1/158 (0.6%) | 0/158 each | 0.0%-0.6% |

The leave-one-record-out diagnostic was computed from record level gap indicators. The profiles and ordering decisions were not rebuilt for each omission. Under `source_semantics`, omitting one of the 11 divergent records gave 10/157 divergent records, or 6.4%. Omitting any non-divergent record gave 11/157 divergent records, or 7.0%.

The property result is path-limited and diagnostic. A zero property gap under `source_semantics` means that no additional answers were found on predecessor identities along the implemented P44, P126, and P32 paths; it does not show that condition, material, or technique information is generally unaffected by segmentation. The predicate-path inventory counted the source statements used by the three property-retrieval tasks. The condition task used 433 P44 statements attached to modified targets, while 411 P44 statements occurred elsewhere. The material task used 623 P126 statements attached directly to E11 events, while 445 P126 statements occurred elsewhere. The technique task used 702 P32 statements attached directly to E11 events, while 258 P32 statements occurred elsewhere.

The evidence ledger for `source_semantics` contains 11 divergent records. 10 were split by the previous repair/main conservation event label rule, and one, `bod:C822Line`, was split by dates. The file `source_semantics_split_property_trace.csv` reports the predecessor/current E11 labels and implemented-path P44, P126, and P32 counts for these 11 split records. The file `all_roots_split_property_gap_summary.csv` reports the 18 record-family gaps in the max-split diagnostic; `all_roots_split_property_gap_trace.csv` expands these to 156 missing property answers and resolves each answer to the source root that carried it.
