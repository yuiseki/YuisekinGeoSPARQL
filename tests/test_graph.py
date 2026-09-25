"""The graphs and the relations file are what the builder said they were.

Nothing clever is asked of the endpoint here. These check that the bytes on
disk are the bytes the manifest describes. A server answering plausibly over a
graph nobody checked is the failure this repository exists to prevent.
"""
import csv
import hashlib
import os

from conftest import require

DATA = os.environ.get("DATA_DIR", "/data")

# Each source, pinned. Changing a revision changes these, deliberately.
SOURCES = {
    "tokyo23": {
        "dataset": "yuiseki/osm-tokyo23-src-2026-08",
        "revision": "e60e017f6a77fa81014b11ca953ae0b2b177edaf",
        "licence": "ODbL-1.0", "features": 23, "positions": 22307,
        "ttl_sha256":
            "c6cfe6d2d68d0513e81317f40769d6df9eca2f84947c25f5e3cde1b52e289d4c",
    },
    "ne-admin0": {
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "d1d37a11992230933819fdb3f363dc919bb547a5",
        "licence": "public-domain", "features": 258, "positions": 548470,
        "ttl_sha256":
            "597fdd90c230c03f918f019cea0e8938872c387be5decdd536c396d6ef9ceb12",
    },
    "ne-admin1": {
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "d1d37a11992230933819fdb3f363dc919bb547a5",
        "licence": "public-domain", "features": 4596, "positions": 1295268,
        "ttl_sha256":
            "ba4ed3a41539664e2824976b21dddf0118908db7625961d8fecd817757231f4d",
    },
}

# With every source loaded.
ALL = {
    "features": 4877,
    "ordered_pairs": 23780252,
    "rows_written": 36694,
    "relations_sha256":
        "05a49721005af782c13a9e913a4f0b701703c0e25718feb0adeaedde655d4a4a",
    "by_rcc8": {"EC": 26900, "EQ": 58, "NTPP": 1466, "NTPPi": 1466, "PO": 2644, "TPP": 2080, "TPPi": 2080},
}


def digest(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_every_built_source_is_one_this_repository_knows(built):
    assert set(built) <= set(SOURCES), sorted(set(built) - set(SOURCES))
    assert built, "nothing was built"


def test_each_source_is_pinned_where_it_was_pinned(built):
    for key, s in built.items():
        assert s["dataset"] == SOURCES[key]["dataset"], key
        assert s["revision"] == SOURCES[key]["revision"], key


def test_each_graph_is_byte_for_byte_what_it_was(built):
    for key, s in built.items():
        assert s["ttl_sha256"] == SOURCES[key]["ttl_sha256"], key
        assert digest(s["ttl_file"]) == SOURCES[key]["ttl_sha256"], key


def test_the_counts_are_the_counts(built):
    for key, s in built.items():
        assert s["features"] == SOURCES[key]["features"], key
        assert s["positions"] == SOURCES[key]["positions"], key


def test_nerima_is_assembled_from_two_rows(built):
    """osm2pgsql splits a relation's parts, and one of 練馬区's is 2,696
    square metres: the exclave at 西大泉町, surrounded by Saitama. Merging is
    what keeps 23 wards from becoming 24 features while keeping the piece.
    """
    require(built, "tokyo23")
    assert built["tokyo23"]["features_with_more_than_one_source_row"] == {"練馬区": 2}


def test_the_licence_is_the_strictest_one_loaded(manifest, built):
    """Share-alike is contagious. One ODbL source makes the whole derived
    database ODbL, whatever else is in it, and a reader of the output should
    not have to work that out.
    """
    licence = manifest["licence"]
    if "tokyo23" in built:
        assert licence["id"] == "ODbL-1.0"
        assert licence["share_alike"] is True
    else:
        assert licence["id"] == "public-domain"
        assert licence["share_alike"] is False
    for key, s in built.items():
        assert s["licence"] == SOURCES[key]["licence"], key


def test_the_relations_file_is_byte_for_byte_what_it_was(manifest, built):
    """Only when every source is loaded: the file is computed over all of them
    at once, so a subset gives different and equally correct bytes.
    """
    if set(built) != set(SOURCES):
        import pytest
        pytest.skip(f"only {sorted(built)} built")
    rel = manifest["relations"]
    assert rel["features"] == ALL["features"]
    assert rel["ordered_pairs"] == ALL["ordered_pairs"]
    assert rel["rows_written"] == ALL["rows_written"]
    assert rel["by_rcc8"] == ALL["by_rcc8"]
    assert rel["sha256"] == ALL["relations_sha256"]
    assert digest(rel["file"]) == ALL["relations_sha256"]


def test_only_non_disjoint_pairs_are_written(manifest, relations):
    """4,877 features make 23.8 million ordered pairs and all but 36,694 are
    DC. A pair absent from the file is DC with the matrix the manifest names,
    and a reader that does not know this will think the data is missing.
    """
    rel = manifest["relations"]
    assert rel["omitted_as_disjoint"] == rel["ordered_pairs"] - rel["rows_written"]
    assert rel["omitted_matrix"] == "FF2FF1212"
    assert not any(r["rcc8_raw"] == "DC" for r in relations.values())


def test_the_raw_and_normalized_readings_are_in_different_columns(manifest):
    """The raw columns are observations of the geometry as published. The
    normalized ones are a judgement, and carry the method and tolerance that
    produced them so a reader can disagree without losing the observation.
    """
    columns = manifest["relations"]["columns"]
    for name in ("de9im_raw", "sf_raw", "rcc8_raw",
                 "outside_area_deg2", "outside_ratio",
                 "norm_method", "norm_tolerance", "rcc8_norm"):
        assert name in columns, name
    for name in ("subject_source", "subject_layer", "subject_id",
                 "object_source", "object_layer", "object_id"):
        assert name in columns, name


def test_every_row_states_where_both_features_came_from(relations):
    known = set(SOURCES)
    for r in relations.values():
        assert r["subject_source"] in known
        assert r["object_source"] in known
        assert r["subject_id"] and r["object_id"]


def test_the_rcc8_reading_is_one_of_the_eight(relations):
    eight = {"DC", "EC", "PO", "EQ", "TPP", "NTPP", "TPPi", "NTPPi"}
    seen = {r["rcc8_raw"] for r in relations.values()}
    assert seen <= eight, seen - eight
    assert "" not in seen, "a matrix RCC8 could not classify"


def test_the_converse_relations_balance(manifest, built):
    """TPP and TPPi are read from the same matrix, one transposed. If the
    counts ever differ, the transpose is wrong.
    """
    if set(built) != set(SOURCES):
        import pytest
        pytest.skip(f"only {sorted(built)} built")
    by = manifest["relations"]["by_rcc8"]
    assert by["TPP"] == by["TPPi"]
    assert by["NTPP"] == by["NTPPi"]


def test_crossing_is_never_claimed_between_two_areas(relations):
    """SFA defines sfCrosses for point/line, point/area, line/area and
    line/line, and not for area/area. Claiming it here made nine matrices
    disagree with LeanGeospatial's prover, which was right to refuse them.
    """
    for r in relations.values():
        assert "sfCrosses" not in r["sf_raw"].split(","), r


def test_a_ward_is_inside_the_country_the_other_sources_draw(relations, built):
    """The join the sources exist together for: an OpenStreetMap ward, a
    Natural Earth state, a Natural Earth country, one containment chain.
    """
    require(built, "tokyo23")
    require(built, "ne-admin0")
    require(built, "ne-admin1")
    taito = "ward-1758888"
    japan = [r for (a, b), r in relations.items()
             if a == taito and b == "country-JPN"]
    assert japan and japan[0]["rcc8_raw"] == "NTPP"
    tokyo = [r for (a, b), r in relations.items()
             if a == taito and b.startswith("state-JPN")]
    assert tokyo and all(r["rcc8_raw"] == "NTPP" for r in tokyo)
