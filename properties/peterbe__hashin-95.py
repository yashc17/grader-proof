"""H4 property check for peterbe__hashin-95.

From the issue: "Order of hashes shouldn't matter" and "Nothing has actually changed but for some
reason, the order of the hashes is different this time. That would cause an unnecessary change."

Property: amending a requirements file with a package's same hashes in another order leaves the
file unchanged, and amending it with a different set of hashes changes it. The file pins 1 to 4
packages with 2 to 5 hashes each, in the issue's format (` \\` ends each continued line); 200
cases, seed 0. It calls `amend_requirements_content`, the function the upstream tests call.
"""

import random
import string
import sys

import hashin

rng = random.Random(0)


def random_name():
    # One length for all names, so no name is a prefix of another.
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(8))


def random_hash():
    return f"{rng.getrandbits(256):064x}"


def block(name, version, hashes):
    lines = [f"{name}=={version}"] + [f"    --hash=sha256:{h}" for h in hashes]
    return " \\\n".join(lines) + "\n"


for _ in range(200):
    names = list({random_name() for _ in range(rng.randint(1, 4))})
    pins = {
        name: (
            f"{rng.randint(0, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 20)}",
            [random_hash() for _ in range(rng.randint(2, 5))],
        )
        for name in names
    }
    requirements = "".join(block(name, *pins[name]) for name in names)
    name = rng.choice(names)
    version, hashes = pins[name]

    reordered = hashes[1:] + hashes[:1]
    rng.shuffle(reordered)
    if reordered == hashes:
        reordered.reverse()
    result = hashin.amend_requirements_content(
        requirements, [(name, block(name, version, reordered))]
    )
    if result != requirements:
        sys.exit(f"reordering the hashes of {name} changed\n{requirements}\ninto\n{result}")

    added = [*hashes, random_hash()]
    rng.shuffle(added)
    result = hashin.amend_requirements_content(requirements, [(name, block(name, version, added))])
    if result == requirements:
        sys.exit(f"adding a hash to {name} left\n{requirements}\nunchanged")
