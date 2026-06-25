from remake_sensitivity.query_burden import analyse_query


def test_query_burden_counts_triples_and_property_path():
    metadata = {
        "role": "strict_direct",
        "result_variables": ["current"],
        "input_variables": ["maker"],
    }
    strict = """
    PREFIX ex: <http://example.org/remake/>
    SELECT ?current WHERE {
      ?production ex:maker ?maker .
      ?production ex:produced ?current .
      ?current ex:isCurrent true .
    }
    """
    strict_result = analyse_query("strict", strict, metadata, set())
    assert strict_result["triple_pattern_count"] == 3
    assert strict_result["property_path_count"] == 0

    lineage = """
    PREFIX ex: <http://example.org/remake/>
    SELECT ?current WHERE {
      ?original ex:precedesSegment* ?current .
    }
    """
    lineage_result = analyse_query(
        "lineage",
        lineage,
        metadata,
        {"http://example.org/remake/precedesSegment"},
    )
    assert lineage_result["property_path_count"] == 1
    assert lineage_result["derived_predicate_count"] >= 1
