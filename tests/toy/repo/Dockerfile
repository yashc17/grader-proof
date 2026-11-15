FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest

# The builder's test.sh runs `source /opt/conda/bin/activate testbed`.
# SWE-rebench images have that conda env; here the system Python plays its part.
RUN mkdir -p /opt/conda/bin && echo ':' > /opt/conda/bin/activate

# Real images install the code under test with `pip install -e .`, which puts it on sys.path
# through site-packages. H4's check runs Python in isolated mode, which ignores PYTHONPATH.
RUN echo /testbed > "$(python -c 'import site; print(site.getsitepackages()[0])')/testbed.pth"

COPY . /testbed
WORKDIR /testbed
RUN git init -q && git add -A && git -c user.name=toy -c user.email=toy@example.com commit -qm base

# The history a SWE-rebench image keeps after the base commit: a later commit on a remote branch
# and a tag. The task builder must strip it (ADR 0011).
RUN git -c user.name=toy -c user.email=toy@example.com commit -q --allow-empty -m future \
    && git update-ref refs/remotes/origin/main HEAD && git tag future \
    && git reset -q --hard HEAD~1
