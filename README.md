# YuisekinGeoSPARQL

A GeoSPARQL endpoint over published, pinned geographic data, which gives the
same answers today as it will next year.

```bash
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose up --build
```

That builds the graphs, starts the server and runs the tests. Nothing else is
needed and nothing is fetched afterwards.

```bash
curl -s --get http://localhost:3030/geo/sparql \
  --data-urlencode 'query=
    PREFIX geo:  <http://www.opengis.net/ont/geosparql#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX gs:   <https://yuiseki.net/geosparql/schema#>
    SELECT ?country WHERE {
      ?w rdfs:label "台東区"@ja .
      ?c a gs:Country ; rdfs:label ?country ; geo:sfContains ?w .
      FILTER(lang(?country) = "en")
    }'
```

    Japan

The ward on the left is OpenStreetMap; the country on the right is Natural
Earth. Different sources, different licences, different scales, one
topological question.

## What is loaded

| source | features | from | licence |
|---|---|---|---|
| `tokyo23` | 23 wards | [`yuiseki/osm-tokyo23-src-2026-08`](https://huggingface.co/datasets/yuiseki/osm-tokyo23-src-2026-08) | ODbL-1.0 |
| `tokyo23-poi` | 7,265 named places | the same dataset, point and polygon tables | ODbL-1.0 |
| `ne-admin0` | 258 countries | [`yuiseki/ne-admin0-10m`](https://huggingface.co/datasets/yuiseki/ne-admin0-10m) | public domain |
| `ne-admin1` | 4,596 states | the same dataset, admin-1 subset | public domain |
| `ne-admin2` | 3,224 counties | the same dataset, admin-2 subset, the United States only | public domain |
| `abr-pref` | 47 prefectures | [`yuiseki/jp-admin-2026-09`](https://huggingface.co/datasets/yuiseki/jp-admin-2026-09) | CC BY 4.0 |
| `abr-muni` | 1,909 municipalities | the same dataset | CC BY 4.0 |

`SOURCES` picks what to load, and with it what the result carries:

```bash
docker compose up --build                       # the default four, so ODbL
SOURCES="ne-admin0 ne-admin1 ne-admin2" docker compose up --build  # public domain
SOURCES="abr-pref abr-muni"             docker compose up --build  # CC BY
SOURCES=all                             docker compose up --build  # everything
```

The default is `tokyo23 tokyo23-poi ne-admin0 ne-admin1`, which is what the
tests and the published digests are about. `all` is 97,000 features, hours of
pairwise geometry, and a graph that mixes ODbL with CC BY and therefore comes
out ODbL, so it is available and not the default.

`abr-pref` and `abr-muni` are Japan without OpenStreetMap in it: the Address
Base Registry's names on the 2020 census boundaries. A graph of those two is
CC BY, so what is built from it carries no share-alike. They sit beside the
`tokyo23` and `jp-*` layers rather than replacing them, because the two
disagree in ways worth being able to see: OpenStreetMap has 1,740
municipalities at `admin_level=7` and the registry has 1,918, since the 171
wards of the designated cities sit at a different level in one and not in the
other.

Nine of the registry's 1,918 have no boundary and are dropped here, which is
why the count above is 1,909: six villages of the Northern Territories the
census does not survey, and three wards Hamamatsu created in 2024.

Share-alike is contagious: one ODbL source makes the whole derived database
ODbL whatever else is in it. CC BY is not: it asks to be credited and stops
there. The builder works that out from the sources it
was given and writes the answer into `manifest.json`, so a reader of the
output does not have to.

## Why it repeats

Reproducible is easy to claim and easy to lose. Each of these was a decision:

**Every dataset is pinned to a commit, not a branch.** A branch makes the
answer depend on the day.

**Nothing reaches the network at query time.** No Overpass, no live OSM, no
federated `SERVICE`. A test asserts that a query naming an external endpoint
fails rather than quietly succeeding on someone else's data.

**Both images are pinned by digest** and Apache Jena is pinned by sha256,
checked at build time. Python dependencies are exact versions; PyPI will not
re-upload a version that exists, so a pinned version is an immutable artefact.

**Rows are sorted and coordinates are rounded** before serialisation, to seven
decimals, about a centimetre. Neither Parquet's row order nor a different GEOS
build can move a byte.

**The output is checksummed and the checksum is asserted.** The tests fail if
a graph changes, so moving a revision is a visible act rather than a silent
drift.

## What comes out

    data/tokyo23.ttl        23 wards as geo:Feature with geo:asWKT
    data/tokyo23-poi.ttl    7,265 named places, one per Wikidata id
    data/ne-admin0.ttl      258 countries
    data/ne-admin1.ttl      4,596 states
    data/relations.tsv      every pair of features that is not disjoint
    data/manifest.json      revisions, counts, digests, and the licence

The endpoint is at `/geo/sparql`; `/geo/query` and `/geo/` are the same thing.

### relations.tsv

One file over every feature from every source, not one per source. The
cross-layer pairs are the point: a ward inside a country, a state inside the
country it names.

| column | |
|---|---|
| `subject_source` `subject_layer` `subject_id` `subject_name` `subject_kind` | where the left side came from, and whether it is a point, a line or an area |
| `object_source` `object_layer` `object_id` `object_name` `object_kind` | and the right |
| `de9im_raw` | the DE-9IM matrix |
| `sf_raw` | which Simple Features predicates hold, read off the matrix |
| `rcc8_raw` | the RCC8 relation, read off the same matrix, empty unless both kinds are `area` |
| `outside_area_deg2` `outside_ratio` | how far the subject leaves the object |
| `norm_method` `norm_tolerance` `rcc8_norm` | empty unless `--normalize` was given |

The raw columns are observations. The normalized ones are a judgement, and
carry the method and the tolerance that produced them, so a reader can
disagree with the judgement without losing the observation. They are never
mixed.

There are two methods and the second exists because the first does not always
apply.

`--normalize snap` moves the subject's vertices onto the object's where they
are within a distance, then reads the matrix again. It closes a hairline.

`--normalize area-ratio` reads an overlap smaller than a fraction of the
subject as a touch. Japan's census boundaries are digitised per municipality,
and neighbours across a border do not share their nodes: 川崎市幸区 and
大田区 overlap across the Tama river by 1.2% of a ward. Snapping at a hundred
metres does not close that, because it is not a hairline but two readings of
where the river is. On the CC BY layers the rule turns all 3,394 overlaps
into EC, leaves every containment alone, and the largest overlap it has to
cover is 0.032 against a threshold of 0.05. That is not much room, and a
later edition that exceeds it will show as a PO that survives normalisation
rather than as a silent rewrite.

Only pairs that are **not** disjoint are written, and only between layers
that are compared at all. 12,142 features make 147,416,022 ordered pairs;
24,114,442 of them are formed, and 51,436 are anything other than disjoint.

`tokyo23-poi` is compared against `tokyo23` and against nothing else. 7,265
places against each other is a different dataset with a different cost, and
the question the layer was added for is which ward a place is in.
`layers_compared` in the manifest says which comparisons were made, so a
reader can tell a pair that was looked at and found disjoint from a pair that
was never formed.

A compared pair that is absent is disjoint, and how that is spelled depends on
the kinds: `FF2FF1212` for two areas, `FF0FFF212` for a point against an area.
The manifest carries the whole table in `omitted_matrix_by_kinds`. A reader
that fills in absent pairs with the area/area matrix gives every place a
boundary it does not have.

| RCC8 | pairs |
|---|---|
| `EC` | 26,906 |
| `NTPP` / `NTPPi` | 5,134 each |
| `PO` | 3,140 |
| `TPP` / `TPPi` | 2,083 each |
| `EQ` | 58 |
| none | 6,898 |

The last row is not a failure to classify. RCC8 is a calculus of regions: a
point is not a region, so a place mapped as a node has no RCC8 relation to the
ward it sits in, and the column is empty rather than holding the nearest
relation that fits. Its Simple Features column is filled in the usual way, and
`sfWithin` is what says the place is in the ward.

Two of the eight Simple Features predicates are defined by cases on the kinds,
which is why the kinds are in the file. `sfOverlaps` needs both operands to
have the same dimension. `sfCrosses` needs them to differ, in a fixed argument
order: a point crosses an area, an area does not cross a point. Reading the
pattern without the case made every ward claim to cross every place inside
it.

## Checking it against a proof

The counts are not compared against numbers somebody wrote down. The builder
computes with GEOS through shapely; the endpoint computes with JTS inside
Jena; the tests compare the two, pair by pair, for all eight Simple Features
predicates. Two implementations of one standard agreeing is evidence. One
agreeing with itself is not.

Beyond that, [LeanGeospatial](https://github.com/yuiseki/LeanGeospatial) has
machine-checked proofs of the RCC8 weak composition table and of the DE-9IM
patterns behind the Simple Features relations. `src/prover_requests.py` in
[geo-triples-tokyo23](https://github.com/yuiseki/geo-triples-tokyo23) turns
`relations.tsv` into the JSON Lines its prover reads. It used to live here as
`builder/triples.py`, and moved because it reads this repository's output
rather than helping to produce it, which is the line the builder image draws:

```bash
python3 src/prover_requests.py \
    --relations ../YuisekinGeoSPARQL/data/relations.tsv \
    --out data/prover/triples.jsonl \
    --claims-out data/prover/claims.jsonl --limit 0

lean-geospatial-prover < data/prover/triples.jsonl > verdicts.jsonl
```

Each request states A r B and B s C and asks what holds between A and C. The
prover answers from the table it has proved; the observed A-C relation rides
along in an `observed` key it ignores, so a checker can compare without the
prover being told the answer.

Last run, over every source:

| | |
|---|---|
| triples | 699,002 |
| the table allows the observed relation | 646,290 |
| the table allows only one, and it is the observed one | 52,712 |
| contradictions | 0 |
| cells of the 64 exercised | 27 |

and for the DE-9IM claims, 144 distinct matrix and predicate pairs: 38
entailed, 106 refuted, nothing in disagreement.

## Two things about the source data

**練馬区 arrives as two rows.** osm2pgsql splits a relation's parts, and one
of Nerima's is 2,696 square metres: the exclave at 西大泉町, a single lot
surrounded by Saitama. Dropping the small row would make the ward a `Polygon`
and lose a piece of Tokyo. Keeping the rows apart would make 23 wards into 24
features. They are merged, and the manifest records that it happened.

**40.7% of states leave their own country's polygon.** Natural Earth builds
admin-0 and admin-1 to agree, and they do: every one of the 4,596 states names
a country that exists, with no orphans. But the two layers draw the same
border twice, independently, and the vertices do not land in the same places.
The median area outside is zero. Five states differ by more than 10% and all
five are islands or a divided country: Coral Sea Islands, Alo, Niuas, Nicosia,
Pohnpei.

This is why `outside_ratio` is a column, and why the normalized reading lives
in its own. As an observation the relation is `PO`; as a statement about
geography it is containment. The composition check above runs on the raw
reading and passes; a geographical claim should read the normalized one.

## What depends on this

[`yuiseki/geo-triples-tokyo23`](https://github.com/yuiseki/geo-triples-tokyo23)
is built from `relations.tsv` and nothing else. Its claim to be reproducible
rests on this repository being reproducible, so this one exists partly to be
checked: anyone who wants to verify that dataset starts here, runs
`docker compose up --build`, and compares the digests in `manifest.json`
against the ones that dataset records.

## Layout

    builder/     downloads the pinned revisions, writes the graphs and relations.tsv
    builder/rcc8.py    reads RCC8 and Simple Features off a DE-9IM matrix, by pattern
    fuseki/      Apache Jena Fuseki 6.2.0, one jar, with a GeoSPARQL assembler
    tests/       the graphs are what they say, and Jena agrees with GEOS

## Licence

Code MIT. The data is whatever the loaded sources carry, and the manifest says
which. With `tokyo23` loaded that is ODbL from OpenStreetMap, and so is
everything this produces, including the answers the endpoint gives. With only
the Natural Earth sources it is public domain.

See [ATTRIBUTION.md](ATTRIBUTION.md), which explains why that matters when
mixing sources.
