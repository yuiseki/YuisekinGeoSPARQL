"""The graphs are what the builder said they were.

Nothing clever is asked of the endpoint here. These check that the bytes on
disk are the bytes the manifest describes. A server answering plausibly over a
graph nobody checked is the failure this repository exists to prevent.
"""
import hashlib
import os

from conftest import require

DATA = os.environ.get("DATA_DIR", "/data")

# Each source, pinned. Changing a revision changes these, deliberately.
EXPECTED = {
    "tokyo23": {
        "dataset": "yuiseki/osm-tokyo23-src-2026-08",
        "revision": "e60e017f6a77fa81014b11ca953ae0b2b177edaf",
        "licence": "ODbL-1.0",
        "features": 23,
        "positions": 22307,
        "ordered_pairs": 506,
        "ttl_sha256":
            "c6cfe6d2d68d0513e81317f40769d6df9eca2f84947c25f5e3cde1b52e289d4c",
        "relations_sha256":
            "e90147c8c642017b0df5efbe292b68449de6fc70f223588a089508a4328fd1c6",
    },
    "ne-admin0": {
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "03e247c4de1fe6f97fe3dd8e4f000f3f04210b9f",
        "licence": "public-domain",
        "features": 258,
        "positions": 548470,
        "ordered_pairs": 66306,
        "ttl_sha256":
            "d6128880a13a092a8c04a3f3c9d4877fcc47cb5ab4d321c71c887518067e9938",
        "relations_sha256":
            "738e23d7425b2b4b1f865856d641c50b32692eb252c184eb2eb3c23e165bd7f2",
    },
}


def digest(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_every_built_source_is_one_this_repository_knows(built):
    assert set(built) <= set(EXPECTED), sorted(set(built) - set(EXPECTED))
    assert built, "nothing was built"


def test_each_source_is_pinned_where_it_was_pinned(built):
    for key, s in built.items():
        e = EXPECTED[key]
        assert s["dataset"] == e["dataset"]
        assert s["revision"] == e["revision"]


def test_each_graph_is_byte_for_byte_what_it_was(built):
    for key, s in built.items():
        e = EXPECTED[key]
        assert s["ttl_sha256"] == e["ttl_sha256"], key
        assert digest(s["ttl_file"]) == e["ttl_sha256"], key


def test_each_relations_file_is_byte_for_byte_what_it_was(built):
    for key, s in built.items():
        e = EXPECTED[key]
        assert s["relations_sha256"] == e["relations_sha256"], key
        assert digest(s["relations_file"]) == e["relations_sha256"], key


def test_the_counts_are_the_counts(built):
    for key, s in built.items():
        e = EXPECTED[key]
        assert s["features"] == e["features"], key
        assert s["positions"] == e["positions"], key
        assert s["ordered_pairs"] == e["ordered_pairs"], key


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
        assert s["licence"] == EXPECTED[key]["licence"]
