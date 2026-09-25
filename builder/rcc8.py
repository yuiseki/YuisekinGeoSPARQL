#!/usr/bin/env python3
"""Read an RCC8 relation off a DE-9IM matrix, and nothing else.

The matrix is the primitive. Every relation below is a pattern over its nine
cells, in the order II IB IE BI BB BE EI EB EE, with `F` meaning empty and
`T` meaning nonempty, where a dimension digit counts as nonempty. This is the
same reading LeanGeospatial formalises, so the names written here are the
names its prover accepts.

Nothing here is approximate. A relation derived by tolerance belongs in a
different column, computed by a different function, and labelled with the
method and the tolerance that produced it. Mixing the two would put a judgement
into a field that is supposed to hold an observation.
"""

# II IB IE BI BB BE EI EB EE  ->  II BI EI IB BB EB IE BE EE
TRANSPOSE = (0, 3, 6, 1, 4, 7, 2, 5, 8)

# The converse pair. Rather than write mirrored patterns and get one of them
# subtly wrong, the converse relations are read from the transposed matrix.
CONVERSE = {"TPP": "TPPi", "NTPP": "NTPPi"}

# Patterns for two areas, read forwards. Exactly one must match, and of_matrix
# asserts that, so a matrix RCC8 cannot classify is an error rather than a
# silent fallback.
#
# Two areas, and only two areas. RCC8 is a calculus of regions: a point is not
# a region and has no RCC8 relation to anything. A caller with a point is
# expected to leave the RCC8 column empty rather than to reach for the nearest
# relation that fits, and the composition table has nothing to say about such
# a pair either.
#
# The distinction between TPP and NTPP is BB, whether the boundaries meet, not
# BI. Both have A's boundary inside B somewhere, so a pattern that tests BI
# matches them both; the first version of this file did, and called every
# non-tangential part tangential as well.
#
# EQ has to be kept out of TPP by EI: for a proper part, B's interior reaches
# outside A, and for equality it does not.
FORWARD = (
    ("EQ",   "T*F**FFF*"),
    ("DC",   "FF*FF****"),
    ("EC",   "FT*******"),
    ("EC",   "F**T*****"),
    ("EC",   "F***T****"),
    ("PO",   "T*T***T**"),
    ("TPP",  "TFF*T*T**"),
    ("NTPP", "TFF*F*T**"),
)


def transpose(matrix):
    """The matrix of the converse relation: B against A."""
    return "".join(matrix[i] for i in TRANSPOSE)


def matches(matrix, pattern):
    for got, want in zip(matrix, pattern):
        if want == "*":
            continue
        if want == "F":
            if got != "F":
                return False
        elif want == "T":
            if got == "F":
                return False
        else:
            raise ValueError(f"bad pattern character {want!r}")
    return True


def of_matrix(matrix):
    """The single RCC8 relation a 9-character matrix denotes, or None.

    Read forwards first. If nothing matches, read the transposed matrix and
    take the converse, which is how TPPi and NTPPi are recognised without a
    second set of hand-written patterns to get wrong.
    """
    if len(matrix) != 9:
        raise ValueError(f"a DE-9IM matrix has nine cells, got {matrix!r}")
    hits = {name for name, pat in FORWARD if matches(matrix, pat)}
    if len(hits) == 1:
        return hits.pop()
    if not hits:
        back = {name for name, pat in FORWARD if matches(transpose(matrix), pat)}
        if len(back) == 1:
            name = back.pop()
            return CONVERSE.get(name, name)
        if len(back) > 1:
            raise ValueError(f"{matrix} transposes to several relations: {back}")
        return None
    raise ValueError(f"{matrix} matches several relations: {hits}")


# The eight Simple Features predicates, as patterns, so that the file records
# what the matrix says rather than what a library was asked.
#
# Six of the eight read the same whatever the operands are. Two are defined by
# cases on their dimensions, and getting those cases from the operands rather
# than assuming a pair of areas is the whole reason this takes kinds at all.
#
# sfOverlaps holds only between operands of the same dimension, and its
# pattern carries that dimension: T*T***T** for two points or two areas,
# 1*T***T** for two lines. Between different dimensions it is undefined.
#
# sfCrosses is the mirror image, and it is not symmetric. SFA gives it to
# point/line, point/area and line/area, in that argument order, plus
# 0******** for two lines. The lower dimension has to come first: a.Crosses(b)
# where a is an area and b is a point is not one of the listed cases and is
# false, even though the matrix of a ward holding a point matches T*T******
# perfectly well. Reading the pattern without the case made every ward claim
# to cross every place inside it.
#
# Between two areas it is undefined and always false. Writing T*T****** there,
# which is the point/line reading, made nine matrices claim to cross;
# LeanGeospatial's prover refused them, and it was right.
#
# sfTouches is undefined between two points, which cannot meet without their
# interiors meeting.
KIND_DIMENSION = {"point": 0, "line": 1, "area": 2}

COMMON = {
    "sfEquals":     ["T*F**FFF*"],
    "sfDisjoint":   ["FF*FF****"],
    "sfIntersects": ["T********", "*T*******", "***T*****", "****T****"],
    "sfTouches":    ["FT*******", "F**T*****", "F***T****"],
    "sfWithin":     ["T*F**F***"],
    "sfContains":   ["T*****FF*"],
}

SF = ("sfEquals", "sfDisjoint", "sfIntersects", "sfTouches", "sfWithin",
      "sfContains", "sfOverlaps", "sfCrosses")


def kind_of(geom):
    """point, line or area, from a shapely geometry."""
    name = geom.geom_type
    if name in ("Point", "MultiPoint"):
        return "point"
    if name in ("LineString", "MultiLineString", "LinearRing"):
        return "line"
    if name in ("Polygon", "MultiPolygon"):
        return "area"
    raise ValueError(f"no Simple Features kind for {name}")


def patterns(a_kind="area", b_kind="area"):
    """The eight predicates' patterns for this pair of kinds.

    An empty list means SFA leaves the predicate undefined for these operands,
    which it answers as false rather than as an error.
    """
    da, db = KIND_DIMENSION[a_kind], KIND_DIMENSION[b_kind]
    out = dict(COMMON)
    if da == db:
        out["sfOverlaps"] = ["1*T***T**"] if da == 1 else ["T*T***T**"]
        out["sfCrosses"] = ["0********"] if da == 1 else []
        if da == 0:
            out["sfTouches"] = []
    else:
        out["sfOverlaps"] = []
        out["sfCrosses"] = ["T*T******"] if da < db else []
    return {name: out[name] for name in SF}


# Kept for the area/area case, which is what every caller wanting a constant
# wants, and what the tests pin.
SF_PATTERNS = patterns("area", "area")


def simple_features(matrix, a_kind="area", b_kind="area"):
    """Which of the eight hold between these two operands, off the matrix."""
    return {name: any(matches(matrix, p) for p in pats)
            for name, pats in patterns(a_kind, b_kind).items()}
