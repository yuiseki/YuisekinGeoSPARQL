"""The endpoint answers the eight predicates, and agrees with GEOS.

No count here is compared against a number somebody wrote down. Each is
compared against relations.tsv, which the builder computed with GEOS through
shapely, while the endpoint computes with JTS inside Jena. Two implementations
of one standard agreeing is evidence. One implementation agreeing with itself
is not.
"""
import pytest

from conftest import require

PREDICATES = ("sfEquals", "sfDisjoint", "sfIntersects", "sfTouches",
              "sfWithin", "sfContains", "sfOverlaps", "sfCrosses")

# Which feature class each source puts in the graph.
CLASS = {"tokyo23": "Ward", "ne-admin0": "Country"}


def pairs_from(ask, source, predicate):
    """Every ordered pair of distinct features the endpoint relates."""
    rows = ask("""
        SELECT ?a ?b WHERE {
          ?fa a gs:%s ; geo:%s ?fb .
          ?fb a gs:%s .
          FILTER(?fa != ?fb)
          BIND(REPLACE(STR(?fa), "^.*/", "") AS ?a)
          BIND(REPLACE(STR(?fb), "^.*/", "") AS ?b)
        }""" % (CLASS[source], predicate, CLASS[source]))
    return {(r["a"], r["b"]) for r in rows}


@pytest.mark.parametrize("predicate", PREDICATES)
def test_jena_and_geos_agree_on_every_pair(ask, relations, built, predicate):
    for source in built:
        theirs = pairs_from(ask, source, predicate)
        ours = {k for k, v in relations[source].items() if v[predicate] == "1"}
        assert theirs == ours, {
            "source": source, "predicate": predicate,
            "only jena": sorted(theirs - ours)[:5],
            "only geos": sorted(ours - theirs)[:5],
        }


def test_the_feature_counts_match_the_manifest(ask, built):
    for source, s in built.items():
        rows = ask("SELECT (COUNT(DISTINCT ?f) AS ?n) WHERE { ?f a gs:%s }"
                   % CLASS[source])
        assert int(rows[0]["n"]) == s["features"], source


def test_touching_and_intersecting_are_the_same_set(ask, built):
    """Administrative areas of one level partition their parent: they meet
    along boundaries and share no area. If these ever differ, two of them have
    begun to overlap, which is a fact about the data worth being told.
    """
    for source in built:
        assert (pairs_from(ask, source, "sfTouches")
                == pairs_from(ask, source, "sfIntersects")), source


def test_nothing_contains_or_overlaps_its_own_kind(ask, built):
    for source in built:
        assert pairs_from(ask, source, "sfWithin") == set(), source
        assert pairs_from(ask, source, "sfContains") == set(), source
        assert pairs_from(ask, source, "sfOverlaps") == set(), source
        assert pairs_from(ask, source, "sfEquals") == set(), source


def test_taito_touches_exactly_five_wards(ask, built):
    require(built, "tokyo23")
    rows = ask("""
        SELECT ?name WHERE {
          ?a rdfs:label "台東区"@ja ; geo:sfTouches ?b .
          ?b a gs:Ward ; rdfs:label ?name .
          FILTER(?a != ?b) FILTER(lang(?name) = "ja")
        } ORDER BY ?name""")
    assert [r["name"] for r in rows] == ["中央区", "千代田区", "墨田区", "文京区", "荒川区"]


def test_japan_touches_no_country_by_land(ask, built):
    require(built, "ne-admin0")
    rows = ask("""
        SELECT ?name WHERE {
          ?j gs:iso3 "JPN" ; geo:sfTouches ?o .
          ?o a gs:Country ; rdfs:label ?name FILTER(lang(?name) = "en")
        }""")
    assert rows == []


def test_a_ward_is_inside_a_country_from_the_other_source(ask, built):
    """The join the two datasets exist for. Left is an OpenStreetMap
    administrative area, right is a Natural Earth border: different sources,
    different licences, different scales, one topological question.
    """
    require(built, "tokyo23")
    require(built, "ne-admin0")
    rows = ask("""
        SELECT ?country WHERE {
          ?w rdfs:label "台東区"@ja .
          ?c a gs:Country ; rdfs:label ?country ; geo:sfContains ?w .
          FILTER(lang(?country) = "en")
        }""")
    assert [r["country"] for r in rows] == ["Japan"]


def test_relate_takes_a_pattern_and_answers_a_boolean(ask, built):
    """geof:relate is the three-argument form: it tests a DE-9IM pattern
    rather than returning the matrix. The matrix is in relations.tsv, which is
    what a later formal check would read.
    """
    require(built, "tokyo23")
    rows = ask("""
        SELECT ?touches ?separate WHERE {
          ?a rdfs:label "台東区"@ja ; geo:hasDefaultGeometry/geo:asWKT ?wa .
          ?b rdfs:label "墨田区"@ja ; geo:hasDefaultGeometry/geo:asWKT ?wb .
          BIND(geof:relate(?wa, ?wb, "FF2F11212") AS ?touches)
          BIND(geof:relate(?wa, ?wb, "FF*FF****") AS ?separate)
        }""")
    assert rows[0]["touches"] == "true"
    assert rows[0]["separate"] == "false"


def test_the_matrix_relate_confirms_is_the_one_geos_recorded(ask, relations, built):
    """For adjacent pairs, the pattern GEOS wrote is one geof:relate accepts.
    This is the link between the file and the endpoint: if they part company,
    the file is what a formal check would have believed.
    """
    for source in built:
        adjacent = [(k, v) for k, v in relations[source].items()
                    if v["sfTouches"] == "1"]
        assert adjacent, source
        for (a, b), row in adjacent[:8]:
            answer = ask("""
                SELECT ?ok WHERE {
                  ?fa a gs:%s ; geo:hasDefaultGeometry/geo:asWKT ?wa .
                  ?fb a gs:%s ; geo:hasDefaultGeometry/geo:asWKT ?wb .
                  FILTER(REPLACE(STR(?fa), "^.*/", "") = "%s")
                  FILTER(REPLACE(STR(?fb), "^.*/", "") = "%s")
                  BIND(geof:relate(?wa, ?wb, "%s") AS ?ok)
                }""" % (CLASS[source], CLASS[source], a, b, row["de9im"]))
            assert answer, ("no such pair in the graph", source, a, b)
            assert answer[0]["ok"] == "true", (row["a_name"], row["b_name"],
                                               row["de9im"])


def test_a_query_cannot_reach_outside(ask):
    """No SERVICE clause resolves: the container has the graphs and nothing
    else, which is what makes a result depend only on the pinned inputs.
    """
    import httpx
    with pytest.raises((httpx.HTTPStatusError, httpx.ReadTimeout)):
        ask("""SELECT * WHERE {
                 SERVICE <https://query.wikidata.org/sparql> { ?s ?p ?o }
               } LIMIT 1""", timeout=30.0)
