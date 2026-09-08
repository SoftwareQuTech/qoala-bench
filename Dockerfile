# syntax=docker/dockerfile:1.7
#
# Self-contained qoala-bench image: the compiler toolchain (qoala-opt /
# qoala-translate) plus the full Python stack needed to compile, simulate and
# analyse Qoala programs.
#
# Unlike the artifact image that accompanied the paper, nothing is built from
# source here. euqalyptus and the qoala-mlir Python bindings come from PyPI,
# and the two qoala-mlir binaries come from that project's GitHub release, so
# the image builds in minutes instead of hours.
#
# This image is meant to be built and used locally. It is deliberately not
# published to any registry: NetSquid is licensed software that each user has
# to obtain under their own account, so redistributing a built image is not
# ours to do.
#
# Build (BuildKit required, for the NetSquid credential secrets):
#
#   docker build \
#     --secret id=netsquid_user,env=NETSQUIDPYPI_USER \
#     --secret id=netsquid_pwd,env=NETSQUIDPYPI_PWD \
#     -t qoala-bench:latest .
#
# or `docker compose build`, which reads the credentials from a local .env.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Python 3.10 comes from deadsnakes rather than Ubuntu 24.04's own 3.12:
# the stack pins matplotlib==3.6.3 (via qoala), which has no cp312 wheel.
ARG PYTHON_VERSION=3.10
RUN apt-get update && apt-get install -y --no-install-recommends \
      software-properties-common ca-certificates curl make \
 && add-apt-repository ppa:deadsnakes/ppa -y \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      "python${PYTHON_VERSION}-full" \
 && "python${PYTHON_VERSION}" -m ensurepip \
 && "python${PYTHON_VERSION}" -m pip install --no-cache-dir --upgrade pip \
 && ln -sf "/usr/bin/python${PYTHON_VERSION}" /usr/local/bin/python \
 && ln -sf "/usr/bin/python${PYTHON_VERSION}" /usr/local/bin/python3 \
 && rm -rf /var/lib/apt/lists/*

# SCIP runtime: qoala-opt links against libscip.so.9.2 for its MILP-based
# reordering pass. apt pulls in the full dependency chain (libblas, libboost,
# libtbb12, …), which is why the image is Ubuntu-based and not python:slim.
ARG SCIP_VERSION=9.2.2
RUN apt-get update \
 && curl -sSfL -o /tmp/scip.deb \
      "https://www.scipopt.org/download/release/SCIPOptSuite-${SCIP_VERSION}-Linux-ubuntu24.deb" \
 && apt-get -y install /tmp/scip.deb \
 && rm /tmp/scip.deb \
 && rm -rf /var/lib/apt/lists/*

# qoala-opt / qoala-translate, from the qoala-mlir GitHub release.
ARG QOALA_MLIR_VERSION=0.1.0
RUN curl -sSfL \
      "https://github.com/SoftwareQuTech/qoala-mlir/releases/download/v${QOALA_MLIR_VERSION}/qoala-mlir-${QOALA_MLIR_VERSION}-linux-x86_64.tgz" \
    | tar -xz -C /usr/local/bin \
 && chmod +x /usr/local/bin/qoala-opt /usr/local/bin/qoala-translate \
 && qoala-opt --version

# qoala-bench itself, installed editable so the tests and examples in the
# source tree run against exactly this checkout.
#
# NetSquid is licensed software served from a private index; the credentials
# are mounted as build secrets so they stay out of the image and its history.
# Register at https://netsquid.org/ to obtain them (free for research).
#
# setuptools-scm cannot see the version because .dockerignore excludes .git,
# hence the explicit pretend-version.
ARG QOALA_BENCH_VERSION=0.0.0
COPY . /workspace/qoala-bench
WORKDIR /workspace/qoala-bench
RUN --mount=type=secret,id=netsquid_user \
    --mount=type=secret,id=netsquid_pwd \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_QOALA_BENCH="${QOALA_BENCH_VERSION}" \
    python -m pip install --no-cache-dir -e ".[dev]" \
      --extra-index-url="https://$(cat /run/secrets/netsquid_user):$(cat /run/secrets/netsquid_pwd)@pypi.netsquid.org"

CMD ["/bin/bash"]
