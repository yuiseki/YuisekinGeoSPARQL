#!/usr/bin/env python3
"""Turn pinned Hugging Face revisions into deterministic Turtle.

One graph per source, plus the DE-9IM matrix of every ordered pair within it,
plus a manifest that records the revisions, the counts, the digests, and the
licence the result carries.

Everything that could vary is nailed down. Datasets are fetched at a commit
sha rather than a branch. Rows are sorted by their own identifier, so the file
does not depend on the order Parquet returns. Coordinates are rounded to a
fixed number of decimals, so a different GEOS or PROJ build cannot move a
digit. Nothing carries a timestamp: the file is its own checksum.

    python build_rdf.py --out /data --source tokyo23
    python build_rdf.py --out /data --source ne-admin0
    python build_rdf.py --out /data --source all
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys

import sources as S

# Seven decimals is about a centimetre. Finer than any of these sources
# surveys to, and coarse enough that no floating-point difference between two
# library builds shows through.
PRECISION = 7
TARGET_CRS = "OGC:CRS84"

# The eight Simple Features predicates GeoSPARQL names.
SF = ("sfEquals", "sfDisjoint", "sfIntersects", "sfTouches",
      "sfWithin", "sfContains", "sfOverlaps", "sfCrosses")

PREFIXES = """@prefix geo:   <http://www.opengis.net/ont/geosparql#> .
@prefix geof:  <http://www.opengis.net/def/function/geosparql/> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix wd:    <http://www.wikidata.org/entity/> .
@prefix gs:    <https://yuiseki.net/geosparql/schema#> .
"""


def fetch(spec, out_dir):
    """The local path of this source's file, or of each of them.

    A source names one file or several. A place mapped as a node lands in one
    osm2pgsql table and the same place mapped as a way lands in another, so a
    layer that is about places rather than about tables reads both.
    """
    from huggingface_hub import hf_hub_download

    def one(name):
        return hf_hub_download(spec["dataset"], name, repo_type="dataset",
                               revision=spec["revision"],
                               cache_dir=os.path.join(out_dir, "hf"))

    if spec.get("files"):
        return [one(n) for n in spec["files"]]
    return one(spec["file"])


# --------------------------------------------------------------------------
# Loaders. Each returns a list of features, sorted, each a dict with:
#   key      a stable identifier, unique within the source
#   label    [(text, language), ...]
#   geometry a shapely geometry in the source CRS
#   props    extra triples, as (predicate, object) strings already in Turtle
#   parts    how many source rows were merged into it

def load_tokyo23(path, spec):
    """The 23 special wards, each as one geometry.

    A ward may arrive as several rows: osm2pgsql splits a relation's parts,
    and one of 練馬区's is 2,696 square metres, the exclave at 西大泉町 that
    sits inside Saitama. Dropping the small row would make the ward a Polygon
    and lose a piece of Tokyo; keeping the rows apart would make 23 wards into
    24 features. They are merged.
    """
    import json as _json
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    from shapely import wkb
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union

    t = pq.read_table(path, columns=["osm_id", "admin_level", "boundary",
                                     "name", "way", "tags"])
    sel = t.filter(pc.and_(pc.equal(t.column("boundary"), "administrative"),
                           pc.equal(t.column("admin_level"), "7")))
    parts = {}
    for row in sel.to_pylist():
        name = row["name"] or ""
        if not name.endswith("区"):
            continue
        try:
            tags = _json.loads(row["tags"] or "{}")
        except (ValueError, TypeError):
            tags = {}
        p = parts.setdefault(row["osm_id"], {"name": name, "tags": tags,
                                             "geoms": [], "rows": 0})
        p["geoms"].append(wkb.loads(bytes(row["way"])))
        p["rows"] += 1

    out = []
    for osm_id in sorted(parts):
        p = parts[osm_id]
        geom = unary_union(sorted(p["geoms"], key=lambda g: (g.bounds, g.area)))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        labels = [(p["name"], "ja")]
        if p["tags"].get("name:en"):
            labels.append((p["tags"]["name:en"], "en"))
        props = ['gs:osmId "%d"^^xsd:long' % osm_id,
                 "gs:osmRelation <https://www.openstreetmap.org/relation/%d>"
                 % abs(osm_id)]
        if p["tags"].get("wikidata"):
            props.append("owl:sameAs wd:%s" % p["tags"]["wikidata"])
        out.append({"key": safe_key("ward-%d" % abs(osm_id)), "sort": osm_id,
                    "label": labels, "geometry": geom, "props": props,
                    "parts": p["rows"], "name": p["name"]})
    return out


def load_tokyo23_poi(paths, spec):
    """Named places carrying a Wikidata id, one feature per id.

    The identity is the Wikidata id, not the OSM object. 63 places are mapped
    both as a node and as a way, and two features with one label and one name
    would be two answers to every question about that place. Where both exist
    the way is kept: an area stands in an RCC8 relation to a ward and a point
    does not, so keeping the point would throw away the part a composition
    table can reason about.

    Administrative boundaries are dropped, and so are the 23 wards' own
    Wikidata ids. Dropping the boundary rows alone is not enough, because
    台東区 is also a place node at the centre of the ward carrying the ward's
    id. It would arrive here as a point named 台東区 sitting inside a ward
    named 台東区, and a question about which ward a place is in would have two
    answers, one of them the place itself.

    Only the wards, not every administrative unit. Excluding the id of every
    boundary in the extract took 390 features, most of them 町丁 mapped as
    both a boundary and a place node. Those are places this layer is for; the
    wards are the layer it would collide with.
    """
    import json as _json
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union

    KIND_RANK = {"area": 1, "point": 0}
    tables = [pq.read_table(p, columns=["osm_id", "name", "way", "tags",
                                        "boundary", "admin_level"]).to_pylist()
              for p in paths]

    def qid_of(row):
        try:
            tags = _json.loads(row["tags"] or "{}")
        except (ValueError, TypeError):
            return "", {}
        qid = tags.get("wikidata") or ""
        return (qid if QID.match(qid) else ""), tags

    # The same rule load_tokyo23 selects the wards by, so the two layers
    # cannot disagree about what a ward is.
    wards = {qid_of(r)[0] for t in tables for r in t
             if r["boundary"] == "administrative"
             and r["admin_level"] == "7"
             and (r["name"] or "").endswith("区")} - {""}

    by_qid = {}
    for rows_in in tables:
        for row in rows_in:
            if not row["name"] or row["boundary"] == "administrative":
                continue
            qid, tags = qid_of(row)
            if not qid or qid in wards:
                continue
            geom = wkb.loads(bytes(row["way"]))
            kind = "area" if geom.geom_type in ("Polygon", "MultiPolygon") \
                else "point" if geom.geom_type == "Point" else None
            if kind is None:
                continue
            have = by_qid.get(qid)
            if have is None or KIND_RANK[kind] > KIND_RANK[have["kind"]]:
                by_qid[qid] = {"kind": kind, "name": row["name"], "tags": tags,
                               "geoms": [geom], "ids": [row["osm_id"]]}
            elif KIND_RANK[kind] == KIND_RANK[have["kind"]]:
                # osm2pgsql splits a multipolygon's parts across rows, the
                # same reason the wards are merged. Two separate places
                # sharing one Wikidata id are merged here too, which is a
                # statement about the tagging and not about the geometry.
                have["geoms"].append(geom)
                have["ids"].append(row["osm_id"])

    out = []
    for qid in sorted(by_qid):
        p = by_qid[qid]
        if p["kind"] == "area":
            geom = unary_union(sorted(p["geoms"],
                                      key=lambda g: (g.bounds, g.area)))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
        else:
            geom = sorted(p["geoms"], key=lambda g: g.coords[0])[0]
        labels = [(p["name"], "ja")]
        if p["tags"].get("name:en"):
            labels.append((p["tags"]["name:en"], "en"))
        props = ["owl:sameAs wd:%s" % qid]
        for osm_id in sorted(set(p["ids"])):
            props.append('gs:osmId "%d"^^xsd:long' % osm_id)
        for tag in ("amenity", "shop", "tourism", "railway", "place",
                    "historic", "leisure", "natural", "building"):
            if p["tags"].get(tag):
                props.append('gs:%s "%s"' % (tag, escape(p["tags"][tag])))
        out.append({"key": safe_key("poi-" + qid), "sort": qid,
                    "label": labels, "geometry": geom, "props": props,
                    "parts": len(p["ids"]), "name": p["name"]})
    return out


def _jp_table(path, columns, filter_):
    """One filtered scan of an osm2pgsql Parquet table.

    The filter is pushed into the scan rather than applied afterwards.
    planet_osm_polygon is 3.3 GB and 33 million rows, of which these layers
    keep two thousand or sixty thousand; reading it whole to throw away the
    rest is how a builder comes to need more memory than the machine has.
    """
    import pyarrow.dataset as ds

    return ds.dataset(path, format="parquet").to_table(
        columns=columns, filter=filter_)


def load_jp_admin(paths, spec):
    """One administrative level of Japan, each unit as one geometry.

    A unit may arrive as several rows: osm2pgsql splits a relation's parts,
    the same reason the Tokyo wards are merged. Merging by osm_id is what
    makes 1,982 rows into 1,740 municipalities.
    """
    import json as _json
    import pyarrow.compute as pc
    from shapely import wkb
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union

    level = spec["admin_level"]
    t = _jp_table(
        paths[0], ["osm_id", "admin_level", "boundary", "name", "tags", "way"],
        (pc.field("boundary") == "administrative")
        & (pc.field("admin_level") == level))

    parts = {}
    for row in t.to_pylist():
        if not row["name"]:
            continue
        try:
            tags = _json.loads(row["tags"] or "{}")
        except (ValueError, TypeError):
            tags = {}
        p = parts.setdefault(row["osm_id"], {"name": row["name"], "tags": tags,
                                             "geoms": [], "rows": 0})
        p["geoms"].append(wkb.loads(bytes(row["way"])))
        p["rows"] += 1

    out = []
    for osm_id in sorted(parts):
        p = parts[osm_id]
        geom = unary_union(sorted(p["geoms"], key=lambda g: (g.bounds, g.area)))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        labels = [(p["name"], "ja")]
        if p["tags"].get("name:en"):
            labels.append((p["tags"]["name:en"], "en"))
        props = ['gs:osmId "%d"^^xsd:long' % osm_id,
                 'gs:adminLevel "%s"' % level,
                 "gs:osmRelation <https://www.openstreetmap.org/relation/%d>"
                 % abs(osm_id)]
        qid = p["tags"].get("wikidata") or ""
        if QID.match(qid):
            props.append("owl:sameAs wd:%s" % qid)
        for tag in ("ISO3166-1", "ISO3166-2", "ref"):
            if p["tags"].get(tag):
                props.append('gs:%s "%s"' % (tag.replace("-", ""),
                                             escape(p["tags"][tag])))
        out.append({"key": safe_key("%s-%d" % (spec["collection"].split("-")[-1],
                                               abs(osm_id))),
                    "sort": osm_id, "label": labels, "geometry": geom,
                    "props": props, "parts": p["rows"], "name": p["name"]})
    return out


def load_jp_poi(paths, spec):
    """Named places in Japan carrying a Wikidata id, one feature per id.

    The same rule as the Tokyo layer, at a hundred times the size. The
    identity is the Wikidata id rather than the OSM object, an area is kept
    where a place is mapped both ways, and any id that an administrative
    boundary in this extract carries is dropped, because those are their own
    layers and would otherwise arrive twice under different IRIs.
    """
    import json as _json
    import pyarrow.compute as pc
    from shapely import wkb
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union

    KIND_RANK = {"area": 1, "point": 0}
    has_wikidata = (pc.field("name").is_valid()
                    & pc.match_substring(pc.field("tags"), '"wikidata"'))

    tables = []
    for path in paths:
        cols = ["osm_id", "name", "tags", "way"]
        # Only the polygon table has these two, and only it needs them.
        if "polygon" in os.path.basename(path):
            cols += ["boundary", "admin_level"]
        tables.append(_jp_table(path, cols, has_wikidata).to_pylist())

    def qid_of(row):
        try:
            tags = _json.loads(row["tags"] or "{}")
        except (ValueError, TypeError):
            return "", {}
        qid = tags.get("wikidata") or ""
        return (qid if QID.match(qid) else ""), tags

    administrative = {qid_of(r)[0] for t in tables for r in t
                      if r.get("boundary") == "administrative"} - {""}

    by_qid = {}
    for rows_in in tables:
        for row in rows_in:
            if row.get("boundary") == "administrative":
                continue
            qid, tags = qid_of(row)
            if not qid or qid in administrative:
                continue
            geom = wkb.loads(bytes(row["way"]))
            kind = ("area" if geom.geom_type in ("Polygon", "MultiPolygon")
                    else "point" if geom.geom_type == "Point" else None)
            if kind is None:
                continue
            have = by_qid.get(qid)
            if have is None or KIND_RANK[kind] > KIND_RANK[have["kind"]]:
                by_qid[qid] = {"kind": kind, "name": row["name"], "tags": tags,
                               "geoms": [geom], "ids": [row["osm_id"]]}
            elif KIND_RANK[kind] == KIND_RANK[have["kind"]]:
                have["geoms"].append(geom)
                have["ids"].append(row["osm_id"])

    out = []
    for qid in sorted(by_qid):
        p = by_qid[qid]
        if p["kind"] == "area":
            geom = unary_union(sorted(p["geoms"],
                                      key=lambda g: (g.bounds, g.area)))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
        else:
            geom = sorted(p["geoms"], key=lambda g: g.coords[0])[0]
        labels = [(p["name"], "ja")]
        if p["tags"].get("name:en"):
            labels.append((p["tags"]["name:en"], "en"))
        props = ["owl:sameAs wd:%s" % qid]
        for osm_id in sorted(set(p["ids"])):
            props.append('gs:osmId "%d"^^xsd:long' % osm_id)
        for tag in ("amenity", "shop", "tourism", "railway", "place",
                    "historic", "leisure", "natural", "building"):
            if p["tags"].get(tag):
                props.append('gs:%s "%s"' % (tag, escape(p["tags"][tag])))
        out.append({"key": safe_key("poi-" + qid), "sort": qid,
                    "label": labels, "geometry": geom, "props": props,
                    "parts": len(p["ids"]), "name": p["name"]})
    return out


def load_abr_admin(path, spec):
    """One rung of Japan's administrative hierarchy, registry names and all.

    The rows arrive already fused: the Address Base Registry supplies the
    codes and the names in kanji, kana and Latin script, and the 2020 census
    supplies the boundary and the counts. Nothing here has to join anything.

    Nine of the 1,918 municipalities have no boundary: six villages of the
    Northern Territories the census does not survey, and three wards Hamamatsu
    created in 2024, after the census. A feature without geometry cannot take
    part in a graph of geometries, so they are dropped, counted, and named in
    the summary rather than silently skipped.
    """
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import MultiPolygon

    t = pq.read_table(path)
    have = set(t.column_names)
    cols = [c for c in ("lg_code", "code5", "pref_code", "pref", "pref_kana",
                        "pref_roma", "county", "city", "ward", "name",
                        "name_roma", "population", "households",
                        "geometry_source", "municipalities", "geometry")
            if c in have]
    rows = t.select(cols).to_pylist()

    out, without = [], []
    for row in rows:
        if not row.get("geometry"):
            without.append(row.get("name") or row.get("pref"))
            continue
        geom = wkb.loads(bytes(row["geometry"]))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        ja = row.get("name") or row.get("pref")
        roma = row.get("name_roma") or row.get("pref_roma")
        labels = [(ja, "ja")]
        if roma:
            labels.append((roma, "en"))
        key = row.get("lg_code") or row.get("pref_code")
        props = []
        for col, pred in (("lg_code", "lgCode"), ("code5", "code5"),
                          ("pref_code", "prefCode"), ("pref", "prefName"),
                          ("county", "county"), ("ward", "ward"),
                          ("geometry_source", "geometrySource")):
            if row.get(col):
                props.append('gs:%s "%s"' % (pred, escape(str(row[col]))))
        for col, pred in (("population", "population"),
                          ("households", "households")):
            if row.get(col) is not None:
                props.append('gs:%s "%d"^^xsd:integer' % (pred, row[col]))
        out.append({"key": safe_key("%s-%s" % (spec["collection"], key)),
                    "sort": key, "label": labels, "geometry": geom,
                    "props": props, "parts": 1, "name": ja})
    if without:
        print(f"  {len(without)} without a boundary, dropped: "
              f"{', '.join(without[:6])}"
              + (" ..." if len(without) > 6 else ""))
    out.sort(key=lambda r: r["sort"])
    return out


def load_ne_admin2(path, spec):
    """3,224 counties of the United States, and of nowhere else.

    REGION carries the postal abbreviation of the state, WA, which is the
    second half of the admin-1 layer's iso_3166_2, US-WA. The column called
    iso_3166_2 here carries US-53, the FIPS number, so a join on the shared
    column name matches nothing and does so quietly. Both are written out.
    """
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import MultiPolygon

    t = pq.read_table(path, columns=["NAME", "NAME_EN", "NAME_JA", "TYPE_EN",
                                     "REGION", "ISO_3166_2", "ADM0_A3",
                                     "ADM2_CODE", "CODE_LOCAL", "WIKIDATAID",
                                     "geometry"])
    out = []
    for row in t.to_pylist():
        geom = wkb.loads(bytes(row["geometry"]))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        labels = []
        if row.get("NAME_EN") or row.get("NAME"):
            labels.append((row.get("NAME_EN") or row["NAME"], "en"))
        # 3,212 of 3,224 carry one, so a Japanese sentence about an American
        # county has a name to use.
        if row.get("NAME_JA"):
            labels.append((row["NAME_JA"], "ja"))
        props = ['gs:adm2Code "%s"' % escape(row["ADM2_CODE"] or ""),
                 'gs:parentRegion "%s"' % escape(row["REGION"] or ""),
                 'gs:iso3166_2 "%s"' % escape(row["ISO_3166_2"] or ""),
                 'gs:parentAdm0A3 "%s"' % escape(row["ADM0_A3"] or ""),
                 'gs:codeLocal "%s"' % escape(row["CODE_LOCAL"] or ""),
                 'gs:typeEn "%s"' % escape(row["TYPE_EN"] or "")]
        qid = row.get("WIKIDATAID") or ""
        if QID.match(qid):
            props.append("owl:sameAs wd:%s" % qid)
        out.append({"key": safe_key("county-" + (row["ADM2_CODE"] or "")),
                    "sort": row["ADM2_CODE"] or "", "label": labels,
                    "geometry": geom, "props": props, "parts": 1,
                    "name": row.get("NAME_EN") or row.get("NAME")})
    out.sort(key=lambda r: r["sort"])
    return out


def load_ne_admin0(path, spec):
    """258 countries as Natural Earth draws them, de facto, at 1:10m."""
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import MultiPolygon

    t = pq.read_table(path, columns=["NAME", "NAME_EN", "NAME_JA", "ISO_A3",
                                     "ADM0_A3", "SOVEREIGNT", "CONTINENT",
                                     "WIKIDATAID", "geometry",
                                     "geometrySource", "datasetVersion",
                                     "boundaryView"])
    out = []
    for row in t.to_pylist():
        geom = wkb.loads(bytes(row["geometry"]))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        labels = []
        for field, lang in (("NAME_EN", "en"), ("NAME_JA", "ja")):
            if row.get(field):
                labels.append((row[field], lang))
        if not labels and row.get("NAME"):
            labels.append((row["NAME"], "en"))
        props = ['gs:iso3 "%s"' % escape(row["ISO_A3"] or ""),
                 'gs:sovereignty "%s"' % escape(row["SOVEREIGNT"] or ""),
                 'gs:continent "%s"' % escape(row["CONTINENT"] or ""),
                 # The three provenance fields the source carries per row,
                 # kept per feature so a mixed graph can still be taken apart.
                 'gs:geometrySource "%s"' % escape(row["geometrySource"] or ""),
                 'gs:datasetVersion "%s"' % escape(row["datasetVersion"] or ""),
                 'gs:boundaryView "%s"' % escape(row["boundaryView"] or "")]
        if (row.get("WIKIDATAID") or "").startswith("Q"):
            props.append("owl:sameAs wd:%s" % row["WIKIDATAID"])
        # ADM0_A3 is unique in this layer and stable across versions, which
        # the row order is not.
        key = safe_key("country-%s" % (row["ADM0_A3"] or row["NAME"]))
        out.append({"key": key, "sort": key, "label": labels, "geometry": geom,
                    "props": props, "parts": 1, "name": row["NAME"]})
    out.sort(key=lambda r: r["sort"])
    return out


def load_ne_admin1(path, spec):
    """4,596 states and provinces, each naming its country in adm0_a3."""
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import MultiPolygon

    t = pq.read_table(path, columns=["name", "name_en", "name_ja", "adm0_a3",
                                     "adm1_code", "iso_3166_2", "wikidataid",
                                     "type_en", "admin", "geometry",
                                     "geometrySource", "datasetVersion",
                                     "boundaryView", "adminLevel"])
    out = []
    for row in t.to_pylist():
        geom = wkb.loads(bytes(row["geometry"]))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        labels = []
        if row.get("name_en"):
            labels.append((row["name_en"], "en"))
        elif row.get("name"):
            labels.append((row["name"], "en"))
        # 4,589 of 4,596 carry one. Without it a Japanese sentence about a
        # Japanese prefecture has no name to use, and the corpus comes out
        # 99.4% English from data that is not.
        if row.get("name_ja"):
            labels.append((row["name_ja"], "ja"))
        props = ['gs:iso3166_2 "%s"' % escape(row["iso_3166_2"] or ""),
                 'gs:adm1Code "%s"' % escape(row["adm1_code"] or ""),
                 'gs:parentAdm0A3 "%s"' % escape(row["adm0_a3"] or ""),
                 'gs:geometrySource "%s"' % escape(row["geometrySource"] or ""),
                 'gs:datasetVersion "%s"' % escape(row["datasetVersion"] or ""),
                 'gs:boundaryView "%s"' % escape(row["boundaryView"] or ""),
                 'gs:adminLevel "%s"' % escape(row["adminLevel"] or "")]
        if (row.get("wikidataid") or "").startswith("Q"):
            props.append("owl:sameAs wd:%s" % row["wikidataid"])
        key = safe_key("state-%s" % (row["adm1_code"] or row["iso_3166_2"]))
        out.append({"key": key, "sort": key, "label": labels, "geometry": geom,
                    "props": props, "parts": 1,
                    "name": row["name_en"] or row["name"] or key})
    out.sort(key=lambda r: r["sort"])
    return out


LOADERS = {"load_tokyo23": load_tokyo23,
           "load_abr_admin": load_abr_admin,
           "load_ne_admin2": load_ne_admin2,
           "load_tokyo23_poi": load_tokyo23_poi,
           "load_jp_admin": load_jp_admin,
           "load_jp_poi": load_jp_poi,
           "load_ne_admin0": load_ne_admin0,
           "load_ne_admin1": load_ne_admin1}

# A Wikidata item id and nothing else. The tag holds whatever an editor typed:
# a property id, a bare number, two ids separated by a semicolon.
QID = re.compile(r"^Q[1-9][0-9]*$")


# --------------------------------------------------------------------------

def to_crs84(geom, source_crs):
    """Reproject if needed, then round.

    Two features on a shared border go through the same function from the same
    coordinates, so the border stays shared and Touches stays exact. Rounding
    each of them separately with different code is how an adjacency becomes a
    hairline gap that nothing in the totals reveals.
    """
    from shapely import set_precision

    if source_crs not in ("EPSG:4326", "OGC:CRS84"):
        from pyproj import Transformer
        from shapely.ops import transform
        tr = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
        geom = transform(lambda x, y, z=None: tr.transform(x, y), geom)
    return set_precision(geom, 10 ** -PRECISION)


# A Turtle prefixed name's local part takes letters, digits, underscore and
# hyphen safely. Natural Earth's adm1_code holds things like "AIA+99?" for a
# feature it has no code for, and Jena reads the "+99" as an integer and
# refuses the whole file. Everything else becomes an underscore.
UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def safe_key(text):
    """A feature id that a Turtle parser will accept."""
    return UNSAFE.sub("_", text)


def escape(s):
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", "\\r"))


def turtle(rows, spec, key):
    """The graph for one source, in a fixed order."""
    base = spec["iri_base"]
    lines = [PREFIXES, "@prefix src:   <%s> ." % base, ""]
    coll = "src:" + spec["collection"]
    lines.append("%s a geo:FeatureCollection ;" % coll)
    for text, lang in spec["collection_label"]:
        lines.append('    rdfs:label "%s"@%s ;' % (escape(text), lang))
    lines.append('    dcterms:source <https://huggingface.co/datasets/%s> ;'
                 % spec["dataset"])
    lines.append('    dcterms:identifier "%s" ;' % spec["revision"])
    lines.append('    dcterms:license <%s> ;' % S.LICENCES[spec["licence"]]["url"])
    lines.append('    dcterms:rightsHolder "%s" .' % escape(spec["rights_holder"]))
    lines.append("")

    for r in rows:
        iri = "src:" + r["key"]
        g = "src:geom-" + r["key"]
        lines.append("%s a geo:Feature , gs:%s ;" % (iri, spec["feature_class"]))
        for text, lang in r["label"]:
            lines.append('    rdfs:label "%s"@%s ;' % (escape(text), lang))
        lines.append("    dcterms:isPartOf %s ;" % coll)
        for p in r["props"]:
            lines.append("    %s ;" % p)
        lines.append('    gs:sourceRows "%d"^^xsd:integer ;' % r["parts"])
        lines.append("    geo:hasGeometry %s ;" % g)
        lines.append("    geo:hasDefaultGeometry %s ." % g)
        lines.append("%s a geo:Geometry ;" % g)
        lines.append('    geo:asWKT "%s"^^geo:wktLiteral .' % r["crs84"].wkt)
        lines.append("")
    return "\n".join(lines)


RELATION_COLUMNS = (
    "subject_source", "subject_layer", "subject_id", "subject_name",
    "subject_kind",
    "object_source", "object_layer", "object_id", "object_name",
    "object_kind",
    "de9im_raw", "sf_raw", "rcc8_raw",
    "outside_area_deg2", "outside_ratio",
    "norm_method", "norm_tolerance", "rcc8_norm",
)

# Two features that do not meet have a matrix decided entirely by their
# kinds, and this is the table of them. Pairs are omitted from the file rather
# than written with it: 4,877 features make 23.8 million ordered pairs and all
# but a few tens of thousands are disjoint. The reader fills them in, which is
# why the manifest carries this table rather than a single string: a point has
# no boundary, so a point that misses an area does not spell it the way two
# areas do.
DISJOINT_BY_KINDS = {
    ("area", "area"): "FF2FF1212",
    ("point", "area"): "FF0FFF212",
    ("area", "point"): "FF2FF10F2",
    ("point", "point"): "FF0FFF0F2",
    ("line", "line"): "FF1FF0102",
    ("point", "line"): "FF0FFF102",
    ("line", "point"): "FF1FF00F2",
    ("area", "line"): "FF2FF1102",
    ("line", "area"): "FF1FF0212",
}

DISJOINT = DISJOINT_BY_KINDS[("area", "area")]


def allowed_pairs(specs):
    """Which layers each layer is compared against, by name.

    A layer with no restriction is compared against everything, which is what
    makes a ward inside a country appear at all. A layer that names its
    partners is compared against those and nothing else, including not against
    itself: 7,288 places against each other is a different dataset with a
    different cost, and it is not the question that layer was added for.

    A pair is computed only if both ends allow it, so one restricted layer is
    enough to exclude a pair and the file cannot depend on which way round the
    two were seen.
    """
    return {spec["collection"]: (set(spec["pairs_with"])
                                 if spec.get("pairs_with") else None)
            for spec in specs}


def pair_allowed(allowed, a_layer, b_layer):
    for first, second in ((a_layer, b_layer), (b_layer, a_layer)):
        limit = allowed.get(first)
        if limit is not None and second not in limit:
            return False
    return True


def relations(features, normalize=None, tolerance=None, allowed=None):
    """Every ordered pair that is not disjoint, with what the matrix says.

    Computed over every feature from every source at once, not per source.
    Cross-layer pairs are the point: a ward inside a country, a state inside
    the country it names. Those are the triples a composition table is checked
    against, and a per-source file cannot hold them.

    The kinds are in the output because two of the eight Simple Features
    predicates are defined by cases on them, and because RCC8 is a calculus of
    regions: a pair involving a point has no RCC8 relation and its column is
    empty rather than filled with the nearest relation that fits.

    raw and normalized are kept apart. The raw columns are observations of the
    geometry as published; the normalized ones are a judgement, and carry the
    method and tolerance that produced them so a reader can disagree.
    """
    from shapely import relate, snap, STRtree

    import rcc8 as R

    allowed = allowed or {}
    geoms = [f["crs84"] for f in features]
    kinds = [R.kind_of(g) for g in geoms]
    tree = STRtree(geoms)
    out = []
    for i, a in enumerate(features):
        for j in (int(x) for x in tree.query(geoms[i])):
            if j == i:
                continue
            b = features[j]
            if not pair_allowed(allowed, a["layer"], b["layer"]):
                continue
            ga, gb = geoms[i], geoms[j]
            matrix = relate(ga, gb)
            if matrix.startswith("FF") and matrix[3:5] == "FF":
                # Disjoint, whatever the kinds. The constant below is the
                # area/area spelling of it; a pair involving a point spells
                # the same fact differently, because a point has no boundary,
                # so the test is the pattern rather than the string.
                continue
            ka, kb = kinds[i], kinds[j]
            sf = R.simple_features(matrix, ka, kb)
            outside = ga.difference(gb).area
            row = {
                "subject_source": a["source"], "subject_layer": a["layer"],
                "subject_id": a["key"], "subject_name": a["name"],
                "subject_kind": ka,
                "object_source": b["source"], "object_layer": b["layer"],
                "object_id": b["key"], "object_name": b["name"],
                "object_kind": kb,
                "de9im_raw": matrix,
                "sf_raw": ",".join(k for k in sorted(sf) if sf[k]),
                "rcc8_raw": (R.of_matrix(matrix) or ""
                             if ka == "area" and kb == "area" else ""),
                "outside_area_deg2": "%.12g" % outside,
                "outside_ratio": "%.12g" % (outside / ga.area if ga.area else 0.0),
                "norm_method": "", "norm_tolerance": "", "rcc8_norm": "",
            }
            if normalize == "snap" and ka == "area" and kb == "area":
                # Move the subject's vertices onto the object's where they are
                # within the tolerance, then read the matrix again. Mechanical
                # and reversible: the raw columns are untouched.
                sa = snap(ga, gb, tolerance)
                row["norm_method"] = "snap"
                row["norm_tolerance"] = "%.12g" % tolerance
                row["rcc8_norm"] = R.of_matrix(relate(sa, gb)) or ""
            elif normalize == "area-ratio" and ka == "area" and kb == "area":
                # Read a small overlap as a touch.
                #
                # Snapping is the wrong instrument for the disagreement this
                # was added for. Japan's census boundaries are digitised per
                # municipality and neighbours across a border do not share
                # their nodes, so 川崎市幸区 and 大田区 overlap across the
                # Tama river by 1.2% of a ward. Snapping at a hundred metres
                # does not close it, because it is not a hairline: it is two
                # readings of where the river is.
                #
                # Administrative units of one country do not overlap, so an
                # overlap below the threshold is read as adjacency. Above it,
                # the raw reading stands: a rule that rewrote everything would
                # be asserting the conclusion rather than measuring it.
                row["norm_method"] = "area_ratio"
                row["norm_tolerance"] = "%.12g" % tolerance
                inside = 1.0 - (outside / ga.area if ga.area else 0.0)
                raw = row["rcc8_raw"]
                if raw == "PO" and inside <= tolerance:
                    row["rcc8_norm"] = "EC"
                else:
                    row["rcc8_norm"] = raw
            out.append(row)
    out.sort(key=lambda r: (r["subject_id"], r["object_id"]))
    return out


# Anything that would end a field or a row inside a field. One place in Japan
# is named "私立鵬学園高等学校\t第二キャンパス", with a tab in the middle of
# the name tag, and it turned two rows of the file into rows with nineteen
# columns. A reader using DictReader does not fail on that: it shifts every
# value after the name by one and hands back a layer where an id should be.
TSV_WHITESPACE = re.compile(r"[\t\r\n]+")


def tsv_field(value):
    """One field, with nothing in it that could be read as a separator.

    The name columns are a convenience for a person reading the file; the id
    columns are the identity. Collapsing whitespace in a name loses nothing
    that matters here, and the label in the graph keeps the original.
    """
    return TSV_WHITESPACE.sub(" ", str(value))


def write_relations(rels, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(RELATION_COLUMNS) + "\n")
        for r in rels:
            f.write("\t".join(tsv_field(r[c]) for c in RELATION_COLUMNS)
                    + "\n")


def positions(geom):
    """How many coordinates a geometry holds, whatever kind it is."""
    if geom.geom_type == "Point":
        return 1
    if hasattr(geom, "geoms"):
        return sum(positions(g) for g in geom.geoms)
    return (len(geom.exterior.coords)
            + sum(len(i.coords) for i in geom.interiors))


def build_graph(key, out_dir):
    """Load one source, write its graph, and return its features."""
    spec = S.SOURCES[key]
    path = fetch(spec, out_dir)
    rows = LOADERS[spec["loader"]](path, spec)
    if len(rows) != spec["expected"]:
        raise SystemExit(
            f"{key}: found {len(rows)} features, expected {spec['expected']}. "
            "If the pinned revision changed, every expected figure in tests "
            "has to be rebuilt with it.")
    for r in rows:
        r["crs84"] = to_crs84(r["geometry"], spec["source_crs"])
        r["source"] = key
        r["layer"] = spec["collection"]

    ttl = turtle(rows, spec, key)
    ttl_path = os.path.join(out_dir, f"{key}.ttl")
    with open(ttl_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(ttl)

    summary = {
        "source": key,
        "title": spec["title"],
        "dataset": spec["dataset"],
        "revision": spec["revision"],
        "licence": spec["licence"],
        "rights_holder": spec["rights_holder"],
        "layer": spec["collection"],
        "features": len(rows),
        "features_with_more_than_one_source_row":
            {r["name"]: r["parts"] for r in rows if r["parts"] > 1},
        "positions": sum(positions(r["crs84"]) for r in rows),
        "ttl_file": f"{key}.ttl",
        "ttl_bytes": len(ttl.encode("utf-8")),
        "ttl_sha256": hashlib.sha256(ttl.encode("utf-8")).hexdigest(),
    }
    return summary, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/data")
    ap.add_argument("--source", action="append", default=None,
                    help="repeatable; 'all' for every source")
    ap.add_argument("--normalize", choices=["snap", "area-ratio"],
                    default=None,
                    help="also write a normalized RCC8 column, in fields of "
                         "its own. The raw columns are never touched. snap "
                         "moves vertices within a distance; area-ratio reads "
                         "an overlap smaller than a fraction of the subject "
                         "as a touch")
    ap.add_argument("--tolerance", type=float, default=None,
                    help="with snap, a distance in degrees, default 1e-6, "
                         "about 10 cm at this latitude. With area-ratio, a "
                         "fraction of the subject's area, default 0.05. "
                         "Every overlap between two Japanese municipalities "
                         "measured so far is under 0.032")
    a = ap.parse_args()

    keys = a.source or ["all"]
    if "all" in keys:
        keys = list(S.SOURCES)
    unknown = [k for k in keys if k not in S.SOURCES]
    if unknown:
        raise SystemExit(f"unknown source(s) {unknown}; "
                         f"known: {sorted(S.SOURCES)}")
    keys = [k for k in S.SOURCES if k in keys]      # a fixed order

    os.makedirs(a.out, exist_ok=True)
    built, features = [], []
    for k in keys:
        summary, rows = build_graph(k, a.out)
        built.append(summary)
        features.extend(rows)
        print(f"{summary['source']}: {summary['features']} features, "
              f"{summary['positions']:,} positions -> {summary['ttl_file']}")
        for name, n in summary["features_with_more_than_one_source_row"].items():
            print(f"  {name} was assembled from {n} rows")

    features.sort(key=lambda r: (r["source"], r["key"]))
    tolerance = a.tolerance
    if tolerance is None:
        tolerance = 0.05 if a.normalize == "area-ratio" else 1e-6
    rels = relations(features, a.normalize, tolerance,
                     allowed_pairs([S.SOURCES[k] for k in keys]))
    rel_path = os.path.join(a.out, "relations.tsv")
    write_relations(rels, rel_path)
    rel_text = open(rel_path, encoding="utf-8").read()

    total = len(features)
    ordered_pairs = total * (total - 1)
    # How many of those pairs were actually looked at. With a layer that names
    # its partners the two numbers differ by millions, and reporting the
    # difference as disjoint would say the builder had measured pairs it never
    # formed.
    allowed = allowed_pairs([S.SOURCES[k] for k in keys])
    per_layer = collections.Counter(f["layer"] for f in features)
    compared = sum(
        n * (per_layer[m] - (1 if l == m else 0))
        for l, n in sorted(per_layer.items())
        for m in sorted(per_layer)
        if pair_allowed(allowed, l, m))
    # An empty RCC8 column is not a failure to classify: it is a pair that has
    # no RCC8 relation because one of its operands is not a region.
    by_rcc8 = collections.Counter(
        r["rcc8_raw"] or "(not two regions)" for r in rels)
    cross = collections.Counter(
        (r["subject_layer"], r["object_layer"]) for r in rels)

    licence = S.combined_licence(keys)
    info = S.LICENCES[licence]
    manifest = {
        "sources": built,
        "crs": {"target": TARGET_CRS, "rounded_to_decimals": PRECISION},
        "relations": {
            "file": "relations.tsv",
            "columns": list(RELATION_COLUMNS),
            "features": total,
            "ordered_pairs": ordered_pairs,
            "pairs_compared": compared,
            "pairs_not_compared": ordered_pairs - compared,
            "layers_compared": {l: sorted(v) if v else "every layer"
                                for l, v in sorted(allowed.items())},
            "rows_written": len(rels),
            "omitted_as_disjoint": compared - len(rels),
            "omitted_matrix": DISJOINT,
            "omitted_matrix_by_kinds": {f"{a_}/{b_}": m for (a_, b_), m
                                        in sorted(DISJOINT_BY_KINDS.items())},
            "by_rcc8": dict(sorted(by_rcc8.items())),
            "by_layer_pair": {f"{a_}->{b_}": n
                              for (a_, b_), n in sorted(cross.items())},
            "normalize": a.normalize,
            "tolerance": tolerance if a.normalize else None,
            "sha256": hashlib.sha256(rel_text.encode("utf-8")).hexdigest(),
            "note": (
                "Only pairs that are not disjoint are written, and only "
                "between layers that are compared at all; layers_compared "
                "says which. A compared pair that is absent is disjoint, and "
                "its matrix is the one for its two kinds in "
                "omitted_matrix_by_kinds. RCC8 is a calculus of regions, so "
                "rcc8_raw is empty unless both kinds are area. Areas are in "
                "square degrees, which is only meaningful as the ratio beside "
                "it."),
        },
        "licence": {
            "id": licence, "name": info["name"], "url": info["url"],
            "share_alike": info["share_alike"],
            "attribution_required": info["attribution_required"],
            "derivation": (
                "the strictest licence among the sources loaded; share-alike "
                "is contagious, so one ODbL source makes the whole derived "
                "database ODbL"),
            "rights_holders": sorted({b["rights_holder"] for b in built}),
        },
    }
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(f"\n{total:,} features, {ordered_pairs:,} ordered pairs, "
          f"{compared:,} compared")
    print(f"  {len(rels):,} written, "
          f"{compared - len(rels):,} omitted as DC, "
          f"{ordered_pairs - compared:,} never compared")
    for name, n in sorted(by_rcc8.items()):
        print(f"    {name:14} {n:7,}")
    print("  by layer:")
    for (a_, b_), n in sorted(cross.items()):
        print(f"    {a_} -> {b_:12} {n:7,}")
    print(f"\ngraph licence: {info['name']} ({licence})")
    # Two flags, not one. A licence can require attribution without being
    # share-alike, which is exactly where CC BY sits, and saying "no
    # share-alike and no attribution required" of it is wrong on the half
    # that matters to anyone redistributing the result.
    if info["share_alike"]:
        print("  share-alike applies. Anything built from this graph "
              "carries it.")
    else:
        print("  no share-alike. What is built from this graph may carry "
              "any licence.")
    if info["attribution_required"]:
        print(f"  attribution is required: {', '.join(sorted({b['rights_holder'] for b in built}))}")
    else:
        print("  no attribution required.")

    uid, gid = os.environ.get("HOST_UID"), os.environ.get("HOST_GID")
    if uid and gid and os.geteuid() == 0:
        for dirpath, dirnames, filenames in os.walk(a.out):
            for n in dirnames + filenames:
                try:
                    os.chown(os.path.join(dirpath, n), int(uid), int(gid))
                except OSError:
                    pass
        os.chown(a.out, int(uid), int(gid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
