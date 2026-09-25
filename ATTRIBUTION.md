# Attribution and licence

## The data

This repository serves a Derivative Database of OpenStreetMap.

> (c) OpenStreetMap contributors, available under the Open Database License.
> https://www.openstreetmap.org/copyright

The geometry comes from
[`yuiseki/osm-tokyo23-src-2026-08`](https://huggingface.co/datasets/yuiseki/osm-tokyo23-src-2026-08)
at revision `e60e017f6a77fa81014b11ca953ae0b2b177edaf`, which is itself cut
from `planet-260831.osm.pbf` (md5 `c67437924cf55de40e8708c7192f354d`). That
snapshot is the only source.

The Open Database License is at
https://opendatacommons.org/licenses/odbl/1-0/ . ODbL-1.0 section 4.2 allows
the notice requirement to be met with the licence's URI rather than its text,
which is what this file does.

## What that means for anything built from this

ODbL's share-alike reaches a Derivative Database, not only a copy. Everything
this repository produces is one:

    data/tokyo23.ttl       the wards as RDF and WKT
    data/relations.tsv     the DE-9IM matrix of every ordered pair
    data/manifest.json     counts and digests of the above

So are the answers the endpoint gives. A set of statements generated from
those answers, or a corpus containing them, carries ODbL too.

This matters when mixing sources. Wikidata is CC0 and OurAirports is public
domain; a containment asserted by Wikidata's P131 can be used without
inheriting anything. A containment *computed from these polygons* cannot. Keep
the two apart rather than discovering later that a whole corpus went ODbL.

## The code

MIT. See LICENSE. It does not cover the data, and the data does not cover it.

## Apache Jena

The endpoint is Apache Jena Fuseki 6.2.0, Apache License 2.0, fetched from
Maven Central and pinned by sha256. Not modified.
