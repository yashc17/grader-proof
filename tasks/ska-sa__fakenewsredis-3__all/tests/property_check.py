"""H4 property check for ska-sa__fakenewsredis-3.

From the issue: "According to the redis documentation, only operations that completely replace a
key (rather than modifying it) clear the expiry." It names decr, incr, incrby, incrbyfloat, setbit,
ltrim and rpoplpush as operations that modify a value.

Property: after any sequence of those operations on a key that has an expiry, the key still has
one. Each of 200 cases (seed 0) gives a key a random value and expiry, then applies 1 to 5 random
operations that keep the key's type and leave it non-empty, and checks the expiry after each.
"""

import random
import sys

from fakenewsredis import FakeStrictRedis

rng = random.Random(0)
redis = FakeStrictRedis()
redis.flushall()


def integer_steps(key):
    redis.set(key, rng.randint(-1000, 1000), ex=rng.randint(100, 10000))
    for _ in range(rng.randint(1, 5)):
        operation = rng.choice(("incr", "decr", "incrby"))
        amount = rng.randint(1, 100)
        getattr(redis, operation)(key, amount)
        yield f"{operation}({key!r}, {amount})"


def float_steps(key):
    redis.set(key, rng.randint(-1000, 1000) / 8, ex=rng.randint(100, 10000))
    for _ in range(rng.randint(1, 5)):
        amount = rng.randint(-1000, 1000) / 8
        redis.incrbyfloat(key, amount)
        yield f"incrbyfloat({key!r}, {amount})"


def bit_steps(key):
    value = bytes(rng.randrange(256) for _ in range(rng.randint(1, 8)))
    redis.set(key, value, ex=rng.randint(100, 10000))
    for _ in range(rng.randint(1, 5)):
        offset, bit = rng.randrange(8 * len(value)), rng.randint(0, 1)
        redis.setbit(key, offset, bit)
        yield f"setbit({key!r}, {offset}, {bit})"


def list_steps(key):
    redis.rpush(key, *(rng.randint(0, 9) for _ in range(rng.randint(1, 8))))
    redis.expire(key, rng.randint(100, 10000))
    for _ in range(rng.randint(1, 5)):
        if rng.random() < 0.5:
            source = f"{key}:source"
            redis.rpush(source, rng.randint(0, 9))
            redis.rpoplpush(source, key)
            yield f"rpoplpush({source!r}, {key!r})"
        else:
            length = redis.llen(key)
            start = rng.randrange(length)
            end = rng.randrange(start, length)
            redis.ltrim(key, start, end)
            yield f"ltrim({key!r}, {start}, {end})"


for case in range(200):
    key = f"key{case}"
    steps = rng.choice((integer_steps, float_steps, bit_steps, list_steps))(key)
    done = []
    for step in steps:
        done.append(step)
        ttl = redis.ttl(key)
        if ttl is None or ttl <= 0:
            sys.exit(f"{key} lost its expiry (ttl {ttl}) after {', '.join(done)}")
