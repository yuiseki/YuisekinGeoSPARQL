# YuisekinGeoSPARQL

A GeoSPARQL endpoint over the 23 special wards of Tokyo, which gives the same
answers today as it will next year.

```bash
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose up --build
```

That builds the graph, starts the server and runs the tests. Nothing else is
needed and nothing is fetched afterwards.

The `.env` line makes the builder write as you rather than as root. Without it
`data/` ends up owned by root and removing it needs privileges that starting
from a clean checkout should not require.

```bash
curl -s --get http://localhost:3030/tokyo23/sparql \
  --data-urlencode 'query=
    PREFIX geo:  <http://www.opengis.net/ont/geosparql#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX t23s: <https://yuiseki.net/geosparql/tokyo23/schema#>
    SELECT ?name WHERE {
      ?a rdfs:label "台東区"@ja ; geo:sfTouches ?b .
      ?b a t23s:Ward ; rdfs:label ?name .
      FILTER(?a != ?b) FILTER(lang(?name) = "ja")
    } ORDER BY ?name'
```

    中央区  千代田区  墨田区  文京区  荒川区

## Why it repeats

Reproducible is easy to claim and easy to lose. Each of these was a decision:

**The dataset is pinned to a commit, not a branch.**
`yuiseki/osm-tokyo23-src-2026-08` at
`e60e017f6a77fa81014b11ca953ae0b2b177edaf`. A branch would make the answer
depend on the day.

**Nothing reaches the network at query time.** No Overpass, no live OSM, no
federated `SERVICE`. A test asserts that a query naming an external endpoint
fails rather than quietly succeeding on someone else's data.

**Both images are pinned by digest** and Jena is pinned by sha256, checked at
build time. Python dependencies are exact versions; PyPI will not re-upload a
version that exists, so a pinned version is an immutable artefact.

**Rows are sorted and coordinates are rounded** before serialisation, to seven
decimals, about a centimetre. Neither Parquet's row order nor a different GEOS
build can move a byte.

**The output is checksummed and the checksum is asserted.** `tokyo23.ttl` is
540,077 bytes with sha256 `7c7d3835…`; the tests fail if it changes. Changing
the revision is then a visible act rather than a silent drift.

## What comes out

| File | |
|---|---|
| `data/tokyo23.ttl` | 23 wards as `geo:Feature` with `geo:asWKT`, 22,307 positions |
| `data/relations.tsv` | the DE-9IM matrix and eight predicates for all 506 ordered pairs |
| `data/manifest.json` | the revision, the counts, the digests, the Wikidata id of each ward |

The endpoint is at `/tokyo23/sparql`, and `/tokyo23/query` and `/tokyo23/` are
the same thing.

## What the wards turn out to be

| predicate | ordered pairs |
|---|---|
| `sfDisjoint` | 392 |
| `sfIntersects` | 114 |
| `sfTouches` | 114 |
| `sfEquals`, `sfWithin`, `sfContains`, `sfOverlaps`, `sfCrosses` | 0 |

`sfIntersects` and `sfTouches` are the same 114 pairs, which is the shape an
administrative partition should have: wards meet along boundaries and share no
area. 114 ordered pairs is 57 adjacencies. If those two ever differ, two wards
have begun to overlap, and a test says so.

That they are equal also shows the rounding did no harm. Adjacent wards share
the same OSM ways, so their rings carry identical coordinates; rounding both
with the same function leaves them identical, and `sfTouches` stays exact. A
reprojection done carelessly would have turned every adjacency into a hairline
gap and every `sfTouches` into `sfDisjoint`, with nothing in the totals to say
so.

## How it is checked

The counts are not compared against a number somebody wrote down. The builder
computes every relation with GEOS through shapely and writes
`relations.tsv`; the endpoint computes with JTS inside Jena. The tests
compare the two, pair by pair, for all seven predicates. Two implementations
of one standard agreeing is evidence. One implementation agreeing with itself
is not.

`geof:relate` is checked the same way: for each adjacent pair, the DE-9IM
pattern GEOS recorded is handed back to the endpoint and has to be accepted.

```bash
docker compose run --rm tests
```

## Two things about the source data

**練馬区 arrives as two rows.** osm2pgsql splits a relation's parts, and one of
Nerima's is 2,696 square metres: the exclave at 西大泉町, a single lot
surrounded by Saitama. Dropping the small row would make the ward a `Polygon`
and lose a piece of Tokyo. Keeping the rows apart would make 23 wards into 24
features. They are merged, and the manifest records that it happened.

**和光市 is in the extract and is not a ward.** It is `admin_level=7` and sits
on the edge, so the extraction kept it whole. The rule is `admin_level=7` *and*
a name ending in 区, which is what the source dataset's own provenance states
and what this repository applies rather than trusts.

## Geometry, and what a later formal check would read

The Parquet geometry is EPSG:3857, as osm2pgsql writes it. GeoSPARQL's default
CRS is CRS84, longitude then latitude on WGS84, which is what a literal without
a CRS URI means. The builder reprojects once, with one transformer, and rounds.

`relations.tsv` carries the DE-9IM matrix itself, not only the eight readings
of it. The matrix is the primitive: `sfTouches` is `FF2F11212` and several
other patterns, and a formal treatment works on the matrix. Each row also
carries both OSM ids, so a relation can be traced back to the geometry it came
from, and each ward in the graph carries `owl:sameAs` to its Wikidata item.

Nothing here talks to
[LeanGeospatial](https://github.com/yuiseki/LeanGeospatial) yet. This is what
it would consume.

## Layout

    builder/     downloads the pinned revision, writes the graph and the relations
    fuseki/      Apache Jena Fuseki 6.2.0, one jar, with a GeoSPARQL assembler
    tests/       the graph is what it says, and Jena agrees with GEOS

## Licence

Code MIT. The data is ODbL from OpenStreetMap, and so is everything this
produces, including the answers the endpoint gives. See
[ATTRIBUTION.md](ATTRIBUTION.md), which also explains why that matters when
mixing this with CC0 sources.
