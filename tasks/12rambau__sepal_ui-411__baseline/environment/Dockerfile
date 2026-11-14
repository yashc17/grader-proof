FROM swerebench/sweb.eval.x86_64.12rambau_1776_sepal_ui-411

WORKDIR /testbed

COPY upstream_tests.patch /tmp/upstream_tests.patch
RUN git apply /tmp/upstream_tests.patch && rm /tmp/upstream_tests.patch
