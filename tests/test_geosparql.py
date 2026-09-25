"""The endpoint answers the eight predicates, and agrees with GEOS.

No count here is compared against a number somebody wrote down. Each is
compared against relations.tsv, which the builder computed with GEOS through
shapely, while the endpoint computes with JTS inside Jena. Two implementations
of one standard agreeing is evidence. One implementation agreeing with itself
is not.
"""
import pytest

from conftest import require

# sfDisjoint is not among them. relations.tsv omits disjoint pairs, so the
# file has nothing to compare the endpoint's answer against; what it does have
# is checked by test_disjoint_is_the_pairs_the_file_leaves_out.
PREDICATES = ("sfEquals", "sfIntersects", "sfTouches",
              "sfWithin", "sfContains", "sfOverlaps", "sfCrosses")

# Only tokyo23 is small enough for the default run. Enumerating every pair of
# 258 countries through Jena costs about 65 seconds per predicate whether the
# subject is bound or not: 258 bound queries at 0.29s each come to the same as
# one unbound query, because the cost is 66,306 polygon comparisons either
# way. Seven predicates make that eight minutes. 23 wards take under a second.
SMALL = ("tokyo23",)

# Which feature class each source puts in the graph.
CLASS = {"tokyo23": "Ward", "tokyo23-poi": "Place",
         "ne-admin0": "Country", "ne-admin1": "State"}


def pairs_from(ask, source, predicate):
    """Every ordered pair of distinct features the endpoint relates.

    One query per subject rather than one for the whole class. With both
    sides unbound, Jena's property function cannot use the spatial index and
    compares every pair: 23 wards answer in 0.37 seconds and 258 countries in
    64, which is not the shape of a quadratic. Binding the subject takes each
    of the 258 to about 0.03.
    """
    subjects = ask("SELECT ?f WHERE { ?f a gs:%s }" % CLASS[source])
    pairs = set()
    for row in subjects:
        fa = row["f"]
        rows = ask("""
            SELECT ?a ?b WHERE {
              <%s> geo:%s ?fb .
              ?fb a gs:%s .
              FILTER(<%s> != ?fb)
              BIND("%s" AS ?a)
              BIND(REPLACE(STR(?fb), "^.*/", "") AS ?b)
            }""" % (fa, predicate, CLASS[source], fa,
                    fa.rsplit("/", 1)[-1]))
        pairs.update((r["a"], r["b"]) for r in rows)
    return pairs


def compare(ask, relations, source, predicate):
    theirs = pairs_from(ask, source, predicate)
    ours = {(a, b) for (a, b), v in relations.items()
            if v["subject_source"] == source and v["object_source"] == source
            and predicate in v["sf_raw"].split(",")}
    assert theirs == ours, {
        "source": source, "predicate": predicate,
        "only jena": sorted(theirs - ours)[:5],
        "only geos": sorted(ours - theirs)[:5],
    }


@pytest.mark.parametrize("predicate", PREDICATES)
def test_jena_and_geos_agree_on_every_pair(ask, relations, built, predicate):
    """Within each source. Jena answers with JTS, the file was written with
    GEOS, and two implementations of one standard agreeing is evidence. One
    agreeing with itself is not.

    sfCrosses is never true between two areas, so both sides say nothing and
    the comparison is still worth making: it is where the mistake was.
    """
    for source in SMALL:
        if source in built:
            compare(ask, relations, source, predicate)


@pytest.mark.full
@pytest.mark.parametrize("predicate", PREDICATES)
def test_jena_and_geos_agree_over_every_source(ask, relations, built, predicate):
    """The same comparison over ne-admin1 as well: 4,596 features, 21,946
    pairs among themselves. This is the twelve minutes, and it is the check
    that caught sfCrosses being read with the point/line pattern.
    """
    for source in built:
        if source not in SMALL:
            compare(ask, relations, source, predicate)


def test_disjoint_is_the_pairs_the_file_leaves_out(ask, relations, built, manifest):
    """The one predicate the file cannot be compared against directly.

    4,877 features make 23.8 million ordered pairs and all but 36,694 are DC,
    so they are omitted rather than written. What can be checked is the
    complement: within one source, the pairs Jena calls disjoint are exactly
    the ones the file does not mention.
    """
    for source in SMALL:
        if source not in built:
            continue
        n = built[source]["features"]
        theirs = pairs_from(ask, source, "sfDisjoint")
        written = {(a, b) for (a, b), v in relations.items()
                   if v["subject_source"] == source and v["object_source"] == source}
        assert len(theirs) + len(written) == n * (n - 1), source
        assert not (theirs & written), sorted(theirs & written)[:5]


def test_the_feature_counts_match_the_manifest(ask, built):
    for source, s in built.items():
        rows = ask("SELECT (COUNT(DISTINCT ?f) AS ?n) WHERE { ?f a gs:%s }"
                   % CLASS[source])
        assert int(rows[0]["n"]) == s["features"], source


def test_touching_and_intersecting_are_the_same_set(ask, built):
    """Administrative areas of one level partition their parent: they meet
    along boundaries and share no area. If these ever differ, two of them have
    begun to overlap, which is a fact about the data worth being told.

    ne-admin1 is excluded: its features come from 258 separate partitions and
    neighbouring countries' states do overlap at the seams.
    """
    for source in SMALL:
        if source not in built:
            continue
        assert (pairs_from(ask, source, "sfTouches")
                == pairs_from(ask, source, "sfIntersects")), source


def test_an_administrative_partition_never_contains_its_own_kind(ask, built):
    """True of one level of one partition. Not true of ne-admin1, whose
    features come from 258 separate partitions: 40.7% of states leave their
    own country's polygon, by an area whose median is zero, because the same
    border was drawn twice and independently.
    """
    for source in SMALL:
        if source not in built:
            continue
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
          ?w a gs:Ward ; rdfs:label "台東区"@ja .
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
          ?a a gs:Ward ; rdfs:label "台東区"@ja ;
             geo:hasDefaultGeometry/geo:asWKT ?wa .
          ?b a gs:Ward ; rdfs:label "墨田区"@ja ;
             geo:hasDefaultGeometry/geo:asWKT ?wb .
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
        if source not in SMALL:
            continue
        adjacent = [(k, v) for k, v in relations.items()
                    if v["subject_source"] == source
                    and v["object_source"] == source
                    and "sfTouches" in v["sf_raw"].split(",")]
        assert adjacent, source
        for (a, b), row in adjacent[:8]:
            answer = ask("""
                SELECT ?ok WHERE {
                  ?fa a gs:%s ; geo:hasDefaultGeometry/geo:asWKT ?wa .
                  ?fb a gs:%s ; geo:hasDefaultGeometry/geo:asWKT ?wb .
                  FILTER(REPLACE(STR(?fa), "^.*/", "") = "%s")
                  FILTER(REPLACE(STR(?fb), "^.*/", "") = "%s")
                  BIND(geof:relate(?wa, ?wb, "%s") AS ?ok)
                }""" % (CLASS[source], CLASS[source], a, b, row["de9im_raw"]))
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
