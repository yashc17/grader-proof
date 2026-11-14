FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest

# The builder's test.sh runs `source /opt/conda/bin/activate testbed`.
# SWE-rebench images have that conda env; here the system Python plays its part.
RUN mkdir -p /opt/conda/bin && echo ':' > /opt/conda/bin/activate

COPY . /testbed
ENV PYTHONPATH=/testbed
WORKDIR /testbed
RUN git init -q && git add -A && git -c user.name=toy -c user.email=toy@example.com commit -qm base
