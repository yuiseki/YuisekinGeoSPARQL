"""Shared fixtures: the endpoint, and whatever the builder wrote.

Which sources exist is a build-time choice, so the tests read the manifest
rather than assuming. A test that needs a source it was not given skips.
"""
import csv
import json
import os

import httpx
import pytest

ENDPOINT = os.environ.get("ENDPOINT", "http://localhost:3030/geo/sparql")
DATA = os.environ.get("DATA_DIR", "/data")
PREFIXES = """
PREFIX geo:   <http://www.opengis.net/ont/geosparql#>
PREFIX geof:  <http://www.opengis.net/def/function/geosparql/>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX gs:    <https://yuiseki.net/geosparql/schema#>
"""


@pytest.fixture(scope="session")
def ask():
    def run(query, timeout=300.0):
        r = httpx.post(ENDPOINT, data={"query": PREFIXES + query},
                       headers={"Accept": "application/sparql-results+json"},
                       timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if "boolean" in d:
            return d["boolean"]
        return [{k: v["value"] for k, v in b.items()}
                for b in d["results"]["bindings"]]
    return run


@pytest.fixture(scope="session")
def manifest():
    with open(os.path.join(DATA, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def built(manifest):
    return {s["source"]: s for s in manifest["sources"]}


@pytest.fixture(scope="session")
def relations(manifest):
    """What GEOS computed at build time, keyed by the pair of feature ids.

    One file over every source, not one per source: the cross-layer pairs are
    the point, and a per-source file cannot hold them.
    """
    path = os.path.join(DATA, manifest["relations"]["file"])
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return {(r["subject_id"], r["object_id"]): r for r in rows}


def require(built, key):
    if key not in built:
        import pytest as _p
        _p.skip(f"{key} was not built; SOURCES={sorted(built)}")
