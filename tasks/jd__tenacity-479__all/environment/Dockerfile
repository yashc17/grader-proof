FROM swerebench/sweb.eval.x86_64.jd_1776_tenacity-479

WORKDIR /testbed

COPY upstream_tests.patch /tmp/upstream_tests.patch
RUN git apply /tmp/upstream_tests.patch && rm /tmp/upstream_tests.patch

SHELL ["/bin/bash", "-c"]
RUN source /opt/conda/bin/activate testbed && pip install -e .[dev]

RUN current=$(git symbolic-ref -q HEAD || true) \
    && git for-each-ref --format='delete %(refname)' \
        | grep -vxF "delete $current" \
        | git update-ref --no-deref --stdin \
    && for remote in $(git remote); do git remote remove "$remote"; done \
    && rm -rf .git/FETCH_HEAD .git/ORIG_HEAD .git/refs/original \
    && git reflog expire --expire=now --expire-unreachable=now --all \
    && git gc --prune=now --quiet
