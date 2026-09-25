#!/usr/bin/env python3
"""The datasets this endpoint can serve, and what each one costs in licence.

One entry per published Hugging Face dataset, pinned to a revision. Adding a
source means adding an entry here; nothing else in the builder knows the names.

The licence field is not decoration. Natural Earth is public domain and a
graph built from it alone can be redistributed by anyone. OpenStreetMap is
ODbL and its share-alike reaches a derived database, so a graph that contains
any OSM geometry is ODbL whatever else is in it. The builder computes the
resulting licence from whichever sources were asked for and writes it into the
manifest, because a reader of the output should not have to work it out.
"""

BASE = "https://yuiseki.net/geosparql/"

# Ordered from least to most demanding. The strictest one present wins.
LICENCES = {
    "public-domain": {
        "rank": 0,
        "name": "Public Domain",
        "url": "https://www.naturalearthdata.com/about/terms-of-use/",
        "share_alike": False,
        "attribution_required": False,
    },
    "ODbL-1.0": {
        "rank": 1,
        "name": "Open Database License v1.0",
        "url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "share_alike": True,
        "attribution_required": True,
    },
}


def combined_licence(keys):
    """The licence a graph made of these sources carries.

    Share-alike is contagious: one ODbL source makes the whole derived
    database ODbL. There is no averaging and no per-graph exemption, so the
    answer is simply the strictest.
    """
    if not keys:
        raise ValueError("no sources")
    worst = max(keys, key=lambda k: LICENCES[SOURCES[k]["licence"]]["rank"])
    return SOURCES[worst]["licence"]


SOURCES = {
    "tokyo23": {
        "title": "Tokyo special wards",
        "dataset": "yuiseki/osm-tokyo23-src-2026-08",
        "revision": "e60e017f6a77fa81014b11ca953ae0b2b177edaf",
        "file": "parquet/planet_osm_polygon.parquet",
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "tokyo23/",
        "collection": "tokyo23",
        "collection_label": [("東京都区部", "ja"), ("Tokyo Special Wards", "en")],
        "feature_class": "Ward",
        "expected": 23,
        # osm2pgsql writes Web Mercator; GeoSPARQL's default is CRS84.
        "source_crs": "EPSG:3857",
        "loader": "load_tokyo23",
        "note": (
            "Administrative relations at admin_level 7 whose name ends in 区. "
            "The extract also holds 和光市, which is admin_level 7 and not a "
            "ward, because whole ways were kept at the boundary."),
    },
    "ne-admin0": {
        "title": "Natural Earth admin-0 countries, 10m",
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "d1d37a11992230933819fdb3f363dc919bb547a5",
        "file": "v5.1.1/parquet/ne_10m_admin_0_countries.parquet",
        "licence": "public-domain",
        "rights_holder": "Natural Earth",
        "iri_base": BASE + "ne-admin0/",
        "collection": "ne-admin0",
        "collection_label": [("Natural Earth admin-0 countries", "en")],
        "feature_class": "Country",
        "expected": 258,
        # Natural Earth ships WGS84 already, so nothing is reprojected.
        "source_crs": "EPSG:4326",
        "loader": "load_ne_admin0",
        "note": (
            "Version 5.1.1, default de facto boundary view. The 33 national "
            "points of view Natural Earth also publishes are not here; the "
            "boundaryView column is what would tell them apart."),
    },
    "ne-admin1": {
        "title": "Natural Earth admin-1 states and provinces, 10m",
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "d1d37a11992230933819fdb3f363dc919bb547a5",
        "file": "v5.1.1/parquet/ne_10m_admin_1_states_provinces.parquet",
        "licence": "public-domain",
        "rights_holder": "Natural Earth",
        "iri_base": BASE + "ne-admin1/",
        "collection": "ne-admin1",
        "collection_label": [("Natural Earth admin-1 states and provinces", "en")],
        "feature_class": "State",
        "expected": 4596,
        "source_crs": "EPSG:4326",
        "loader": "load_ne_admin1",
        "note": (
            "Version 5.1.1. Every feature names its country in adm0_a3 and "
            "every one of those is in the admin-0 layer, so a containment "
            "chain has both of its steps. Natural Earth spells the Wikidata "
            "column wikidataid here and WIKIDATAID on admin-0, which is left "
            "as it is."),
    },
}
