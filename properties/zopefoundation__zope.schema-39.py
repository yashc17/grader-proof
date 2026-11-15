"""H4 property check for zopefoundation__zope.schema-39.

From the issue: "What do we need to change to make field instances hashable?" and "There is a
inconsistency that breaks caching schema-fields in Plone with memoize."

Property: every field is hashable, and a cache keyed by a field finds the entry for a field built
from the same arguments. Python requires equal objects to have equal hashes for that to work.
Fields of 6 types get random titles, descriptions and flags, 300 cases with seed 0.
"""

import random
import sys

from zope.schema import ASCIILine, Bool, Float, Int, Text, TextLine

FIELD_TYPES = (ASCIILine, Bool, Float, Int, Text, TextLine)
rng = random.Random(0)


def random_text():
    return "".join(rng.choice("abc xyz") for _ in range(rng.randint(0, 8)))


for _ in range(300):
    field_type = rng.choice(FIELD_TYPES)
    arguments = {
        "title": random_text(),
        "description": random_text(),
        "required": rng.random() < 0.5,
        "readonly": rng.random() < 0.5,
    }
    first, second = field_type(**arguments), field_type(**arguments)
    case = f"{field_type.__name__}(**{arguments!r})"
    try:
        hashes = hash(first), hash(second)
    except TypeError as error:
        sys.exit(f"{case} is not hashable: {error}")
    if hashes[0] != hashes[1]:
        sys.exit(f"two {case} fields have different hashes {hashes}")
    if second not in {first: True}:
        sys.exit(f"a dict keyed by {case} does not find a second {case}")
