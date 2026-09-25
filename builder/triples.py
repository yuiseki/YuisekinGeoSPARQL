#!/usr/bin/env python3
"""Turn relations.tsv into requests LeanGeospatial's prover can answer.

Two kinds, both in the JSON Lines shape ProverJSON.lean documents.

An RCC8 request states A r B and B s C and asks what holds between A and C.
The prover answers from the composition table it has proved; the observed
A-C relation goes in `observed` so a checker can compare without the prover
being told the answer.

    {"id":"...","facts":[{"a":"A","relation":"NTPP","b":"B"},
                         {"a":"B","relation":"NTPP","b":"C"}],
     "query":{"a":"A","b":"C"},"observed":"NTPP", ...}

A DE-9IM claim states a matrix and a Simple Features predicate:

    {"id":"...","matrix":"FF2F11212","claim":"touches"}

A pair absent from relations.tsv is DC. That is how triples through a
disjoint pair are built without writing 23.7 million rows: the reader fills
them in, and --include-dc says whether to.

    python3 triples.py --relations /data/relations.tsv --out /data/triples.jsonl
"""
import argparse
import csv
import json
import os
import random
import sys

RELS = ("DC", "EC", "PO", "EQ", "TPP", "NTPP", "TPPi", "NTPPi")

# The Simple Features predicates the prover's Claim.ofString? accepts, and the
# column in relations.tsv that says whether each holds.
CLAIMS = {"equals": "sfEquals", "disjoint": "sfDisjoint",
          "intersects": "sfIntersects", "touches": "sfTouches",
          "within": "sfWithin", "contains": "sfContains",
          "overlaps": "sfOverlaps", "crosses": "sfCrosses"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def index(rows, column="rcc8_raw"):
    """(a, b) -> relation, and a -> the b it relates to."""
    rel, out = {}, {}
    for r in rows:
        a, b = r["subject_id"], r["object_id"]
        value = r[column]
        if not value:
            continue
        rel[(a, b)] = value
        out.setdefault(a, set()).add(b)
    return rel, out


def triples(rel, out, features, include_dc, limit, seed):
    """Every A-B-C where A-B and B-C are known, optionally through DC too."""
    found = []
    for a, bs in out.items():
        for b in bs:
            r = rel[(a, b)]
            cs = out.get(b, set())
            if include_dc:
                cs = cs | (features - {a, b})
            for c in cs:
                if c == a or c == b:
                    continue
                s = rel.get((b, c), "DC")
                if not include_dc and s == "DC":
                    continue
                found.append((a, r, b, s, c, rel.get((a, c), "DC")))
    if limit and len(found) > limit:
        random.Random(seed).shuffle(found)
        found = found[:limit]
    found.sort()
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--relations", default="/data/relations.tsv")
    ap.add_argument("--out", default="/data/triples.jsonl")
    ap.add_argument("--claims-out", default="/data/claims.jsonl")
    ap.add_argument("--column", default="rcc8_raw",
                    choices=["rcc8_raw", "rcc8_norm"],
                    help="which reading to state as fact. The raw one is the "
                         "observation; the normalized one is a judgement and "
                         "says so in the output")
    ap.add_argument("--include-dc", action="store_true",
                    help="also build triples through a disjoint pair. A pair "
                         "absent from relations.tsv is DC")
    ap.add_argument("--limit", type=int, default=20000,
                    help="0 for all. 699,002 triples exist without --include-dc")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    rows = load(a.relations)
    rel, out = index(rows, a.column)
    features = {r["subject_id"] for r in rows} | {r["object_id"] for r in rows}
    found = triples(rel, out, features, a.include_dc, a.limit, a.seed)

    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for i, (x, r, y, s, z, observed) in enumerate(found):
            f.write(json.dumps({
                "id": f"t{i:07d}",
                "facts": [{"a": x, "relation": r, "b": y},
                          {"a": y, "relation": s, "b": z}],
                "query": {"a": x, "b": z},
                # Not part of the request. The prover ignores unknown keys,
                # and a checker needs the observation to compare against.
                "observed": observed,
                "reading": a.column,
            }, ensure_ascii=False) + "\n")

    seen = set()
    n = 0
    with open(a.claims_out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            held = set(r["sf_raw"].split(",")) if r["sf_raw"] else set()
            for claim, column in sorted(CLAIMS.items()):
                key = (r["de9im_raw"], claim)
                if key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps({
                    "id": f"c{n:07d}",
                    "matrix": r["de9im_raw"],
                    "claim": claim,
                    "observed": column in held,
                }, ensure_ascii=False) + "\n")
                n += 1

    print(f"{len(found):,} triples -> {a.out}  (reading {a.column})")
    print(f"{n:,} distinct matrix/claim pairs -> {a.claims_out}")
    uid, gid = os.environ.get("HOST_UID"), os.environ.get("HOST_GID")
    if uid and gid and os.geteuid() == 0:
        for p in (a.out, a.claims_out):
            try:
                os.chown(p, int(uid), int(gid))
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
