"""H4 property check for toy__clamp-1.

From the issue: "clamp(value, low, high) should return value limited to the range [low, high]".

Property: for every integer value, low and high in [-12, 12] with low <= high, clamp returns the
nearest point of [low, high] to value. The grid is small, so it is checked whole.
"""

import itertools
import sys

from toy.clamp import clamp  # pyright: ignore[reportMissingImports]

span = range(-12, 13)
for value, low, high in itertools.product(span, span, span):
    if low > high:
        continue
    expected = min(max(value, low), high)
    result = clamp(value, low, high)
    if result != expected:
        sys.exit(f"clamp({value}, {low}, {high}) returned {result}, expected {expected}")
