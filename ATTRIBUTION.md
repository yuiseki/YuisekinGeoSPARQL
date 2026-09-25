# Attribution and licence

## Which licence applies depends on what you load

`SOURCES` decides, and the licence of the result is the strictest of the
sources in it. `manifest.json` records the answer for the graph that was
actually built.

| loaded | licence | share-alike | attribution |
|---|---|---|---|
| `ne-admin0`, `ne-admin1` | public domain | no | not required |
| anything including `tokyo23` | ODbL-1.0 | yes | required |

Share-alike is contagious. One ODbL source makes the whole derived database
ODbL whatever else is in it, so there is no combination in which Natural
Earth's terms soften OpenStreetMap's.

## OpenStreetMap, when tokyo23 is loaded

This repository then serves a Derivative Database of OpenStreetMap.

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

    data/*.ttl             the features as RDF and WKT
    data/relations.tsv     the DE-9IM matrix of every pair that is not disjoint
    data/manifest.json     counts, digests, and the licence of the result

So are the answers the endpoint gives. A set of statements generated from
those answers, or a corpus containing them, carries ODbL too.

This matters when mixing sources. Wikidata is CC0 and OurAirports is public
domain; a containment asserted by Wikidata's P131 can be used without
inheriting anything. A containment *computed from these polygons* cannot. Keep
the two apart rather than discovering later that a whole corpus went ODbL.

## Natural Earth, always

Natural Earth places its data in the public domain. No permission is needed
and no attribution is required, though the project asks for credit where
practical:

> Made with Natural Earth. Free vector and raster map data @
> naturalearthdata.com

The frozen copies are
[`yuiseki/ne-admin0-10m`](https://huggingface.co/datasets/yuiseki/ne-admin0-10m)
at version 5.1.1, admin-0 countries and admin-1 states and provinces.

## The code

MIT. See LICENSE. It does not cover the data, and the data does not cover it.

## Apache Jena

The endpoint is Apache Jena Fuseki 6.2.0, Apache License 2.0, fetched from
Maven Central and pinned by sha256. Not modified.
