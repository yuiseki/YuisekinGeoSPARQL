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


# The eight Simple Features predicates, also as patterns, so that the file
# records what the matrix says rather than what a library was asked.
SF_PATTERNS = {
    "sfEquals":     ["T*F**FFF*"],
    "sfDisjoint":   ["FF*FF****"],
    "sfIntersects": ["T********", "*T*******", "***T*****", "****T****"],
    "sfTouches":    ["FT*******", "F**T*****", "F***T****"],
    "sfWithin":     ["T*F**F***"],
    "sfContains":   ["T*****FF*"],
    "sfOverlaps":   ["T*T***T**"],
    "sfCrosses":    ["T*T******"],
}


def simple_features(matrix):
    """Which of the eight hold, read off the matrix.

    sfOverlaps and sfCrosses are the two whose definition depends on the
    dimensions of the operands. These patterns are the area/area readings;
    for a line or a point they are not the right ones, and this file only ever
    sees areas.
    """
    out = {}
    for name, pats in SF_PATTERNS.items():
        out[name] = any(matches(matrix, p) for p in pats)
    return out
