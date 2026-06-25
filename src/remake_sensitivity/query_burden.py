from __future__ import annotations

import argparse
import csv
import itertools
import json
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml


COUNT_FIELDS = (
    "triple_pattern_count",
    "property_path_count",
    "intermediate_variable_count",
    "derived_predicate_count",
    "filter_count",
    "union_branch_count",
    "optional_block_count",
    "subquery_count",
)

DELTA_FIELD_NAMES = {
    "triple_pattern_count": "delta_triple_patterns",
    "property_path_count": "delta_property_paths",
    "intermediate_variable_count": "delta_intermediate_variables",
    "derived_predicate_count": "delta_derived_predicates",
    "filter_count": "delta_filters",
    "union_branch_count": "delta_union_branches",
    "optional_block_count": "delta_optional_blocks",
    "subquery_count": "delta_subqueries",
}


def _prefixes(text: str) -> dict[str, str]:
    return {
        prefix: uri
        for prefix, uri in re.findall(
            r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>", text
        )
    }


def _expand(term: str, prefixes: dict[str, str]) -> str:
    if term.startswith("<") and term.endswith(">"):
        return term[1:-1]
    if ":" in term:
        prefix, local = term.split(":", 1)
        if prefix in prefixes:
            return prefixes[prefix] + local.rstrip("*+?")
    return term.rstrip("*+?")


def analyse_query(
    query_id: str,
    text: str,
    metadata: dict[str, Any],
    derived_predicates: set[str],
) -> dict[str, Any]:
    warnings = [
        "Conservative line-oriented SPARQL parser; complex inline graph patterns may be undercounted."
    ]
    prefixes = _prefixes(text)
    body_match = re.search(r"\{(.*)\}", text, re.DOTALL)
    body = body_match.group(1) if body_match else ""
    lines = [
        re.sub(r"#.*$", "", line).strip()
        for line in body.splitlines()
        if re.sub(r"#.*$", "", line).strip()
    ]
    triple_count = 0
    path_count = 0
    derived_count = 0
    predicates = []
    for line in lines:
        if re.match(r"(?i)^(FILTER|OPTIONAL|UNION|SELECT|BIND|VALUES)\b", line):
            continue
        if line in {"{", "}"}:
            continue
        if line.endswith((";", ".")):
            triple_count += 1
            tokens = line.rstrip(";.").split()
            if not tokens:
                continue
            predicate = tokens[1] if tokens[0].startswith(("?", "<")) and len(tokens) > 1 else tokens[0]
            predicates.append(predicate)
            if re.search(r"[*+?]|[/|^]", predicate):
                path_count += 1
            expanded = _expand(predicate, prefixes)
            if expanded in derived_predicates:
                derived_count += 1
    variables = set(re.findall(r"\?([A-Za-z_][\w-]*)", body))
    excluded = set(metadata.get("result_variables", [])) | set(
        metadata.get("input_variables", [])
    )
    intermediate = len(variables - excluded)
    return {
        "query_id": query_id,
        "query_role": metadata.get("role", ""),
        "triple_pattern_count": triple_count,
        "property_path_count": path_count,
        "intermediate_variable_count": intermediate,
        "derived_predicate_count": derived_count,
        "filter_count": len(re.findall(r"(?i)\bFILTER\s*\(", body)),
        "union_branch_count": (
            len(re.findall(r"(?i)\bUNION\b", body)) + 1
            if re.search(r"(?i)\bUNION\b", body)
            else 0
        ),
        "optional_block_count": len(re.findall(r"(?i)\bOPTIONAL\s*\{", body)),
        "subquery_count": len(re.findall(r"(?i)\{\s*SELECT\b", body)),
        "parser_status": "conservative",
        "query_burden_warnings": " | ".join(warnings),
    }


def generate_query_burden(config_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = Path.cwd()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    results = config["results"]
    manifest = json.loads((root / results["manifest"]).read_text(encoding="utf-8"))
    metadata_path = root / config["queries"]["metadata"]
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    profile = metadata.get("profile", {})
    derived = set(metadata.get("derived_predicates", []))
    rows = []
    for query_id, query_meta in metadata["queries"].items():
        query_path = metadata_path.parent / query_meta["file"]
        row = analyse_query(
            query_id,
            query_path.read_text(encoding="utf-8"),
            query_meta,
            derived,
        )
        query_text = query_path.read_text(encoding="utf-8")
        rows.append(
            {
                "run_id": manifest["run_id"],
                "query_profile_id": profile.get("id", ""),
                "query_profile_version": profile.get("version", ""),
                "counting_rules_version": profile.get("counting_rules_version", ""),
                "query_sha256": hashlib.sha256(query_text.encode()).hexdigest(),
                **row,
            }
        )
    deltas = []
    for left, right in itertools.combinations(rows, 2):
        delta = {
            "run_id": manifest["run_id"],
            "from_query_id": left["query_id"],
            "to_query_id": right["query_id"],
        }
        for field in COUNT_FIELDS:
            delta[DELTA_FIELD_NAMES[field]] = right[field] - left[field]
        deltas.append(delta)
    for path_key, data in (
        ("query_burden", rows),
        ("query_burden_deltas", deltas),
    ):
        path = root / results[path_key]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    return rows, deltas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("data/e11e81/config.yaml"))
    args = parser.parse_args()
    generate_query_burden(args.config)


if __name__ == "__main__":
    main()
