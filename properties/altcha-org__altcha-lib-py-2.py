"""H4 property check for altcha-org__altcha-lib-py-2.

From the issue: "`check_expires=True` produces an error".

Property: for a correctly solved challenge, `verify_solution(..., check_expires=True)` returns
without raising: true if the challenge expires in the future, false if it has expired. Challenges
get random keys, salts, numbers and expiry times from 2 minutes to 30 days before or after now,
so none sits near the boundary; 200 cases, seed 0. Challenges and payloads are built the way the
upstream tests build them.
"""

import base64
import datetime
import json
import random
import string
import sys

from altcha.altcha import ChallengeOptions, Payload, create_challenge, verify_solution

rng = random.Random(0)


def random_text(length):
    return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(length))


for _ in range(200):
    hmac_key = random_text(rng.randint(4, 32))
    number = rng.randint(0, 1000)
    seconds = rng.randint(120, 30 * 24 * 3600) * rng.choice((-1, 1))
    challenge = create_challenge(
        ChallengeOptions(
            algorithm="SHA-256",
            max_number=1000,
            salt_length=16,
            hmac_key=hmac_key,
            salt=random_text(rng.randint(4, 16)),
            number=number,
            expires=datetime.datetime.now().astimezone() + datetime.timedelta(seconds=seconds),
        )
    )
    payload = Payload(
        algorithm="SHA-256",
        challenge=challenge.challenge,
        number=number,
        salt=challenge.salt,
        signature=challenge.signature,
    )
    encoded = base64.b64encode(json.dumps(payload.__dict__).encode()).decode()
    case = f"a challenge with salt {challenge.salt!r} that expires in {seconds} s"
    try:
        verified = verify_solution(encoded, hmac_key, check_expires=True)[0]
    except Exception as error:
        sys.exit(f"verify_solution raised {error!r} on {case}")
    if verified != (seconds > 0):
        sys.exit(f"verify_solution returned {verified} on {case}")
