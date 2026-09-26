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
    # Attribution, and nothing more. Japan's government registries land here:
    # they ask to be credited and they do not reach into what is built from
    # them, which is the whole difference from the entry below.
    "CC-BY-4.0": {
        "rank": 1,
        "name": "Creative Commons Attribution 4.0 International",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "share_alike": False,
        "attribution_required": True,
    },
    "ODbL-1.0": {
        "rank": 2,
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
    "tokyo23-poi": {
        "title": "Named places in the Tokyo wards that carry a Wikidata id",
        "dataset": "yuiseki/osm-tokyo23-src-2026-08",
        "revision": "e60e017f6a77fa81014b11ca953ae0b2b177edaf",
        # Two tables, because a place is mapped as a node or as a way
        # depending on who mapped it and when, and which one it is says
        # nothing about the place.
        "files": ["parquet/planet_osm_point.parquet",
                  "parquet/planet_osm_polygon.parquet"],
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "tokyo23-poi/",
        "collection": "tokyo23-poi",
        "collection_label": [("東京都区部の地物", "ja"),
                             ("Named places in the Tokyo wards", "en")],
        "feature_class": "Place",
        "expected": 7265,
        "source_crs": "EPSG:3857",
        "loader": "load_tokyo23_poi",
        # Only against the wards. 7,288 places against each other is a
        # different dataset with a different cost, and the question this layer
        # was added for is which ward a place is in.
        "pairs_with": ["tokyo23"],
        "note": (
            "One feature per Wikidata id rather than per OSM object. 63 of "
            "them are mapped both as a node and as a way; the way is kept, "
            "because an area relates to a ward as a region and a point does "
            "not. Administrative boundaries are excluded: the wards are "
            "already a layer."),
    },
    # The country-sized sibling of tokyo23, from the same planet file. Four
    # layers rather than one, because the question this source exists for is a
    # hierarchy: a place is in a municipality, which is in a prefecture, which
    # is in the country.
    #
    # Every layer is read from the same two Parquet tables with a filter
    # pushed into the scan. planet_osm_polygon is 3.3 GB and 33 million rows;
    # reading it whole to keep two thousand of them is how a builder ends up
    # needing more memory than the machine has.
    "jp-country": {
        "title": "Japan",
        "dataset": "yuiseki/osm-japan-src-2026-08",
        "revision": "b51be030416ef0b2a011a2d51d3cfbf066a71bfe",
        "files": ["parquet/planet_osm_polygon.parquet"],
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "jp-country/",
        "collection": "jp-country",
        "collection_label": [("日本", "ja"), ("Japan", "en")],
        "feature_class": "Country",
        "admin_level": "2",
        "expected": 1,
        "source_crs": "EPSG:3857",
        "loader": "load_jp_admin",
        "note": "The admin_level=2 relation, as OpenStreetMap draws it.",
    },
    "jp-pref": {
        "title": "Prefectures of Japan",
        "dataset": "yuiseki/osm-japan-src-2026-08",
        "revision": "b51be030416ef0b2a011a2d51d3cfbf066a71bfe",
        "files": ["parquet/planet_osm_polygon.parquet"],
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "jp-pref/",
        "collection": "jp-pref",
        "collection_label": [("都道府県", "ja"),
                             ("Prefectures of Japan", "en")],
        "feature_class": "Prefecture",
        "admin_level": "4",
        "expected": 47,
        "source_crs": "EPSG:3857",
        "loader": "load_jp_admin",
        "note": "All 47, and nothing else: no admin_level=4 division of a "
                "neighbouring country survives the clip.",
    },
    "jp-muni": {
        "title": "Municipalities of Japan",
        "dataset": "yuiseki/osm-japan-src-2026-08",
        "revision": "b51be030416ef0b2a011a2d51d3cfbf066a71bfe",
        "files": ["parquet/planet_osm_polygon.parquet"],
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "jp-muni/",
        "collection": "jp-muni",
        "collection_label": [("市区町村", "ja"),
                             ("Municipalities of Japan", "en")],
        "feature_class": "Municipality",
        "admin_level": "7",
        "expected": 1740,
        "source_crs": "EPSG:3857",
        "loader": "load_jp_admin",
        "note": "市町村 and the special wards of Tokyo, which OpenStreetMap "
                "puts at the same level. The wards of a designated city are "
                "admin_level=8 and are not here.",
    },
    "jp-poi": {
        "title": "Named places in Japan that carry a Wikidata id",
        "dataset": "yuiseki/osm-japan-src-2026-08",
        "revision": "b51be030416ef0b2a011a2d51d3cfbf066a71bfe",
        "files": ["parquet/planet_osm_point.parquet",
                  "parquet/planet_osm_polygon.parquet"],
        "licence": "ODbL-1.0",
        "rights_holder": "OpenStreetMap contributors",
        "iri_base": BASE + "jp-poi/",
        "collection": "jp-poi",
        "collection_label": [("日本の地物", "ja"),
                             ("Named places in Japan", "en")],
        "feature_class": "Place",
        "expected": 80748,
        "source_crs": "EPSG:3857",
        "loader": "load_jp_poi",
        # Only against the municipalities. 85,000 places against each other is
        # a different dataset with a different cost, and the question this
        # layer was added for is which municipality a place is in.
        "pairs_with": ["jp-muni"],
        "note": "One feature per Wikidata id, from the point and polygon "
                "tables. Administrative boundaries are excluded: they are "
                "their own layers.",
    },
    # Japan's administrative geography without OpenStreetMap in it. The names
    # and codes are the Digital Agency's registry and the boundaries are the
    # 2020 census, both CC BY, fused at the municipality in jp-admin-2026-09.
    #
    # Beside the tokyo23 and jp-* layers rather than instead of them. The two
    # disagree in ways worth being able to see: OpenStreetMap has 1,740
    # municipalities at admin_level 7 and the registry has 1,918, because the
    # 171 wards of the designated cities sit at a different level in one and
    # not in the other.
    "abr-pref": {
        "title": "Prefectures of Japan, registry names on census boundaries",
        "dataset": "yuiseki/jp-admin-2026-09",
        "revision": "c86cbe9f2200dadb441f5bde7a1e4b068aeaa7f0",
        "file": "prefectures.parquet",
        "licence": "CC-BY-4.0",
        "rights_holder": "デジタル庁 and 総務省統計局",
        "iri_base": BASE + "abr-pref/",
        "collection": "abr-pref",
        "collection_label": [("都道府県", "ja"),
                             ("Prefectures of Japan", "en")],
        "feature_class": "Prefecture",
        "expected": 47,
        # JGD2000. A datum shift from WGS84 of a few centimetres, which is
        # below the seven decimals everything here is rounded to, but stated
        # rather than assumed.
        "source_crs": "EPSG:4612",
        "loader": "load_abr_admin",
        "note": (
            "Names, readings and romanisation from the Address Base Registry; "
            "boundary and population from the 2020 census small areas, "
            "dissolved."),
    },
    "abr-muni": {
        "title": "Municipalities of Japan, registry names on census boundaries",
        "dataset": "yuiseki/jp-admin-2026-09",
        "revision": "c86cbe9f2200dadb441f5bde7a1e4b068aeaa7f0",
        "file": "municipalities.parquet",
        "licence": "CC-BY-4.0",
        "rights_holder": "デジタル庁 and 総務省統計局",
        "iri_base": BASE + "abr-muni/",
        "collection": "abr-muni",
        "collection_label": [("市区町村", "ja"),
                             ("Municipalities of Japan", "en")],
        "feature_class": "Municipality",
        # 1,918 rows, of which nine have no boundary: six villages of the
        # Northern Territories the census does not survey, and three wards
        # Hamamatsu created in 2024. A feature with no geometry cannot be in
        # a graph of geometries, so they are dropped here and the count says
        # so rather than the loader failing.
        "expected": 1909,
        "source_crs": "EPSG:4612",
        "loader": "load_abr_admin",
        "note": (
            "Includes the 171 wards of the 20 designated cities, which sit "
            "beside their parent city rather than inside it: both carry the "
            "same ground, so a count over this layer double-counts 30 "
            "million people unless the wards are excluded."),
    },
    # Pinned at the revision that first carries admin-2. The admin-0 and
    # admin-1 entries below stay at the older one on purpose: their Parquet
    # bytes are identical at both, and moving the pin would change the
    # provenance string on every row of every dataset already built from
    # them for no change in the data.
    "ne-admin2": {
        "title": "Natural Earth admin-2 counties, 10m",
        "dataset": "yuiseki/ne-admin0-10m",
        "revision": "a891044f7e524b93c60a7686834bd6b8e788d1e1",
        "file": "v5.1.1/parquet/ne_10m_admin_2_counties.parquet",
        "licence": "public-domain",
        "rights_holder": "Natural Earth",
        "iri_base": BASE + "ne-admin2/",
        "collection": "ne-admin2",
        "collection_label": [("Natural Earth admin-2 counties", "en")],
        "feature_class": "County",
        "expected": 3224,
        "source_crs": "EPSG:4326",
        "loader": "load_ne_admin2",
        "note": (
            "The United States and nothing else: Natural Earth publishes no "
            "admin-2 for the other 257 countries at this scale. REGION joins "
            "a county to its state, not iso_3166_2, which holds US-53 here "
            "and US-WA there."),
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
