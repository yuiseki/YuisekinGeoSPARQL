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
    "tokyo23-poi": {
        "dataset": "yuiseki/osm-tokyo23-src-2026-08",
        "revision": "e60e017f6a77fa81014b11ca953ae0b2b177edaf",
        "licence": "ODbL-1.0", "features": 7265, "positions": 73973,
        "ttl_sha256":
            "3ea1dc9e8506ff19fb93e79beea8f5c806e699663846384b101fad245103fe5a",
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
    "features": 12142,
    "ordered_pairs": 147416022,
    # Not every pair is formed. tokyo23-poi is compared against the wards and
    # against nothing else, so the pairs that were never looked at are counted
    # apart from the pairs that were looked at and found disjoint.
    "pairs_compared": 24114442,
    "rows_written": 51436,
    "relations_sha256":
        "6a3354d9928e6eab36e787520aed5946e7b8842d3bf81df861f339b2adb05640",
    "by_rcc8": {"(not two regions)": 6898, "EC": 26906, "EQ": 58,
                "NTPP": 5134, "NTPPi": 5134, "PO": 3140,
                "TPP": 2083, "TPPi": 2083},
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
    assert rel["pairs_compared"] == ALL["pairs_compared"]
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
    assert rel["omitted_as_disjoint"] == rel["pairs_compared"] - rel["rows_written"]
    assert rel["omitted_matrix"] == "FF2FF1212"
    # A point has no boundary, so a point that misses an area does not spell
    # its disjointness the way two areas do. A reader filling in absent pairs
    # with the area/area matrix would give every place a boundary.
    assert rel["omitted_matrix_by_kinds"]["point/area"] == "FF0FFF212"
    assert rel["omitted_matrix_by_kinds"]["area/point"] == "FF2FF10F2"
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
                 "subject_kind", "object_kind",
                 "object_source", "object_layer", "object_id"):
        assert name in columns, name


def test_every_row_states_where_both_features_came_from(relations):
    known = set(SOURCES)
    for r in relations.values():
        assert r["subject_source"] in known
        assert r["object_source"] in known
        assert r["subject_id"] and r["object_id"]


def test_the_rcc8_reading_is_one_of_the_eight(relations):
    """And empty exactly when the pair is not two regions.

    RCC8 is a calculus of regions. A point is not a region, so a pair with a
    point in it has no RCC8 relation, and the column is empty rather than
    holding the nearest relation that fits. Filling it would put every place
    mapped as a node into the composition table, where nothing has been proved
    about it.
    """
    eight = {"DC", "EC", "PO", "EQ", "TPP", "NTPP", "TPPi", "NTPPi"}
    for r in relations.values():
        regions = r["subject_kind"] == "area" and r["object_kind"] == "area"
        if regions:
            assert r["rcc8_raw"] in eight, r
        else:
            assert r["rcc8_raw"] == "", r


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


def test_crossing_is_never_claimed(relations):
    """SFA gives sfCrosses to point/line, point/area and line/area, in that
    argument order, plus line/line. Two areas are not a case, and neither is
    an area against a point.

    Both readings have been wrong here. Applying the point/line pattern to two
    areas made nine matrices claim to cross, and LeanGeospatial's prover
    refused them. Applying it without the argument order made every ward claim
    to cross every place inside it, which the matrix matches perfectly well
    and the standard does not allow.
    """
    for r in relations.values():
        assert "sfCrosses" not in r["sf_raw"].split(","), r


def test_a_place_is_within_the_ward_it_is_in(relations, built):
    """The question this layer was added for.

    Sensoji, mapped as an area, against Taito. The ward contains it and it is
    within the ward, and neither of them overlaps or crosses the other.
    """
    require(built, "tokyo23")
    require(built, "tokyo23-poi")
    taito, sensoji = "ward-1758888", "poi-Q615183"
    down = relations[(sensoji, taito)]
    up = relations[(taito, sensoji)]
    assert "sfWithin" in down["sf_raw"].split(",")
    assert "sfContains" in up["sf_raw"].split(",")
    assert down["subject_layer"] == "tokyo23-poi"
    for r in (down, up):
        held = r["sf_raw"].split(",")
        assert "sfOverlaps" not in held and "sfCrosses" not in held, r


def test_places_are_compared_against_wards_and_nothing_else(manifest, relations,
                                                            built):
    """The restriction that keeps this layer affordable, as a fact about the
    output rather than as an intention in the source.

    7,288 places against each other is a different dataset with a different
    cost. Without the restriction the file would also carry every place
    against every country, which is 1.9 million pairs of nothing.
    """
    require(built, "tokyo23-poi")
    assert manifest["relations"]["layers_compared"]["tokyo23-poi"] == ["tokyo23"]
    for r in relations.values():
        layers = {r["subject_layer"], r["object_layer"]}
        if "tokyo23-poi" in layers:
            assert layers == {"tokyo23-poi", "tokyo23"}, r


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


def test_no_field_can_be_read_as_a_separator(relations):
    """A name with a tab in it, which shifts every value after it.

    One place in Japan is named 私立鵬学園高等学校 with a tab before
    第二キャンパス. csv.DictReader does not fail on the extra column: it
    shifts the row and hands back a layer name where an id should be, and the
    first thing downstream that looks up that id raises somewhere else
    entirely.
    """
    for r in relations.values():
        for name, value in r.items():
            assert "\t" not in (value or ""), (name, r)
            assert "\n" not in (value or ""), (name, r)


def test_the_normalised_reading_is_in_its_own_columns(relations):
    """A judgement must never overwrite an observation.

    rcc8_raw is what the geometry says and rcc8_norm is what a rule made of
    it, and the method and the tolerance that produced the second are beside
    it so a reader can disagree with the rule without losing the measurement.
    """
    for r in relations.values():
        if not r["norm_method"]:
            continue
        assert r["rcc8_raw"], r
        assert r["norm_tolerance"], r
        assert r["norm_method"] in ("snap", "area_ratio"), r


def test_area_ratio_only_ever_turns_an_overlap_into_a_touch(relations):
    """The one rewrite the rule is allowed to make.

    Japan's census boundaries are digitised per municipality and neighbours
    across a border do not share their nodes, so administrative units that
    cannot overlap do. The rule reads a small overlap as adjacency and must
    leave everything else exactly as measured: a containment rewritten by a
    tolerance would be the rule asserting the hierarchy rather than the data
    showing it.
    """
    for r in relations.values():
        if r["norm_method"] != "area_ratio":
            continue
        if r["rcc8_raw"] == r["rcc8_norm"]:
            continue
        assert r["rcc8_raw"] == "PO", r
        assert r["rcc8_norm"] == "EC", r
        # And only where the overlap really is small.
        inside = 1.0 - float(r["outside_ratio"])
        assert inside <= float(r["norm_tolerance"]), r
