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
    from huggingface_hub import hf_hub_download
    return hf_hub_download(spec["dataset"], spec["file"], repo_type="dataset",
                           revision=spec["revision"],
                           cache_dir=os.path.join(out_dir, "hf"))


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


LOADERS = {"load_tokyo23": load_tokyo23, "load_ne_admin0": load_ne_admin0,
           "load_ne_admin1": load_ne_admin1}


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
    "object_source", "object_layer", "object_id", "object_name",
    "de9im_raw", "sf_raw", "rcc8_raw",
    "outside_area_deg2", "outside_ratio",
    "norm_method", "norm_tolerance", "rcc8_norm",
)

# Two areas whose bounding boxes miss cannot meet, and this is the matrix
# every such pair has. Pairs are omitted from the file rather than written
# with it: 4,877 features make 23.8 million ordered pairs and all but a few
# tens of thousands are this. The reader fills them in.
DISJOINT = "FF2FF1212"


def relations(features, normalize=None, tolerance=None):
    """Every ordered pair that is not disjoint, with what the matrix says.

    Computed over every feature from every source at once, not per source.
    Cross-layer pairs are the point: a ward inside a country, a state inside
    the country it names. Those are the triples a composition table is checked
    against, and a per-source file cannot hold them.

    raw and normalized are kept apart. The raw columns are observations of the
    geometry as published; the normalized ones are a judgement, and carry the
    method and tolerance that produced them so a reader can disagree.
    """
    from shapely import relate, snap, STRtree

    import rcc8 as R

    geoms = [f["crs84"] for f in features]
    tree = STRtree(geoms)
    out = []
    for i, a in enumerate(features):
        for j in (int(x) for x in tree.query(geoms[i])):
            if j == i:
                continue
            b = features[j]
            ga, gb = geoms[i], geoms[j]
            matrix = relate(ga, gb)
            if matrix == DISJOINT:
                continue
            sf = R.simple_features(matrix)
            outside = ga.difference(gb).area
            row = {
                "subject_source": a["source"], "subject_layer": a["layer"],
                "subject_id": a["key"], "subject_name": a["name"],
                "object_source": b["source"], "object_layer": b["layer"],
                "object_id": b["key"], "object_name": b["name"],
                "de9im_raw": matrix,
                "sf_raw": ",".join(k for k in sorted(sf) if sf[k]),
                "rcc8_raw": R.of_matrix(matrix) or "",
                "outside_area_deg2": "%.12g" % outside,
                "outside_ratio": "%.12g" % (outside / ga.area if ga.area else 0.0),
                "norm_method": "", "norm_tolerance": "", "rcc8_norm": "",
            }
            if normalize == "snap":
                # Move the subject's vertices onto the object's where they are
                # within the tolerance, then read the matrix again. Mechanical
                # and reversible: the raw columns are untouched.
                sa = snap(ga, gb, tolerance)
                row["norm_method"] = "snap"
                row["norm_tolerance"] = "%.12g" % tolerance
                row["rcc8_norm"] = R.of_matrix(relate(sa, gb)) or ""
            out.append(row)
    out.sort(key=lambda r: (r["subject_id"], r["object_id"]))
    return out


def write_relations(rels, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(RELATION_COLUMNS) + "\n")
        for r in rels:
            f.write("\t".join(str(r[c]) for c in RELATION_COLUMNS) + "\n")


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
        "positions": sum(len(p.exterior.coords)
                         + sum(len(i.coords) for i in p.interiors)
                         for r in rows for p in r["crs84"].geoms),
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
    ap.add_argument("--normalize", choices=["snap"], default=None,
                    help="also write a normalized RCC8 column, in fields of "
                         "its own. The raw columns are never touched")
    ap.add_argument("--tolerance", type=float, default=1e-6,
                    help="with --normalize snap, in degrees. 1e-6 is about "
                         "10 cm at this latitude")
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
    rels = relations(features, a.normalize, a.tolerance)
    rel_path = os.path.join(a.out, "relations.tsv")
    write_relations(rels, rel_path)
    rel_text = open(rel_path, encoding="utf-8").read()

    total = len(features)
    ordered_pairs = total * (total - 1)
    by_rcc8 = collections.Counter(r["rcc8_raw"] or "(unclassified)" for r in rels)
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
            "rows_written": len(rels),
            "omitted_as_disjoint": ordered_pairs - len(rels),
            "omitted_matrix": DISJOINT,
            "by_rcc8": dict(sorted(by_rcc8.items())),
            "by_layer_pair": {f"{a_}->{b_}": n
                              for (a_, b_), n in sorted(cross.items())},
            "normalize": a.normalize,
            "tolerance": a.tolerance if a.normalize else None,
            "sha256": hashlib.sha256(rel_text.encode("utf-8")).hexdigest(),
            "note": (
                "Only pairs that are not disjoint are written. A pair absent "
                "from this file is DC, matrix " + DISJOINT + ". Areas are in "
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

    print(f"\n{total:,} features, {ordered_pairs:,} ordered pairs")
    print(f"  {len(rels):,} written, "
          f"{ordered_pairs - len(rels):,} omitted as DC")
    for name, n in sorted(by_rcc8.items()):
        print(f"    {name:14} {n:7,}")
    print("  by layer:")
    for (a_, b_), n in sorted(cross.items()):
        print(f"    {a_} -> {b_:12} {n:7,}")
    print(f"\ngraph licence: {info['name']} ({licence})")
    if info["share_alike"]:
        print("  share-alike applies. Anything built from this graph carries it.")
    else:
        print("  no share-alike and no attribution required.")

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
