PYTHON3            = python3
SOURCEDIR          = qoala_bench
TESTDIR            = tests
EXAMPLEDIR         = examples
BENCHMARKDIR       = benchmark
RUNEXAMPLES        = ${EXAMPLEDIR}/run_examples.py
LINTDIRS           = ${SOURCEDIR} ${TESTDIR} ${EXAMPLEDIR} ${BENCHMARKDIR}

# euqalyptus, qoala-mlir and qoala are all published on PyPI; only NetSquid
# still needs its private index (free account at https://netsquid.org/).
PIP_FLAGS          = --extra-index-url=https://${NETSQUIDPYPI_USER}:${NETSQUIDPYPI_PWD}@pypi.netsquid.org

# qoala-opt / qoala-translate are consumed as release artifacts of qoala-mlir
# rather than built from source. `make tools` drops them in ${TOOLS_DIR}.
QOALA_MLIR_VERSION = 0.1.0
QOALA_MLIR_URL     = https://github.com/SoftwareQuTech/qoala-mlir/releases/download/v$(QOALA_MLIR_VERSION)/qoala-mlir-$(QOALA_MLIR_VERSION)-linux-x86_64.tgz
TOOLS_DIR          = .tools/bin

DOCKER_IMAGE       = qoala-bench:latest

help:
	@echo "install           Installs the package (editable)."
	@echo "install-dev       Installs the package (editable) with dev extras."
	@echo "tools             Downloads the qoala-opt/qoala-translate release binaries."
	@echo "verify            Runs the linter, type-checker, tests, and examples."
	@echo "tests             Runs the pytest suite under tests/."
	@echo "tests-parallel    Runs the tests with pytest-xdist (auto core count)."
	@echo "examples          Runs the examples and makes sure they work."
	@echo "mypy              Runs the mypy type-checker."
	@echo "lint              Runs the linter (isort, black, flake8)."
	@echo "docker-build      Builds the docker image (needs NetSquid credentials)."
	@echo "docker-verify     Runs the tests and examples inside the docker image."
	@echo "clean             Removes all .pyc files."

_check_variables:
ifndef NETSQUIDPYPI_USER
	$(error Set the environment variable NETSQUIDPYPI_USER before installing)
endif
ifndef NETSQUIDPYPI_PWD
	$(error Set the environment variable NETSQUIDPYPI_PWD before installing)
endif

clean:
	@/usr/bin/find . -name '*.pyc' -delete

lint-isort:
	$(info Running isort...)
	@$(PYTHON3) -m isort --check --diff ${LINTDIRS}

lint-black:
	$(info Running black...)
	@$(PYTHON3) -m black --check ${LINTDIRS}

lint-flake8:
	$(info Running flake8...)
	@$(PYTHON3) -m flake8 ${LINTDIRS}


lint: lint-isort lint-black lint-flake8

mypy:
	$(info Running mypy...)
	@$(PYTHON3) -m mypy ${SOURCEDIR}

tests:
	$(info Running pytest...)
	@$(PYTHON3) -m pytest

tests-parallel:
	$(info Running pytest with pytest-xdist...)
	@$(PYTHON3) -m pytest -n auto

examples:
	$(info Running examples...)
	@$(PYTHON3) ${RUNEXAMPLES}

tools:
	$(info Downloading qoala-mlir $(QOALA_MLIR_VERSION) binaries...)
	@mkdir -p $(TOOLS_DIR)
	@curl -sSfL $(QOALA_MLIR_URL) | tar -xz -C $(TOOLS_DIR)
	@chmod +x $(TOOLS_DIR)/qoala-opt $(TOOLS_DIR)/qoala-translate
	@echo "qoala-opt and qoala-translate installed in $(TOOLS_DIR)."
	@echo "They need SCIP 9.2 (libscip.so.9.2) at runtime; put them on PATH with:"
	@echo '  export PATH="$(CURDIR)/$(TOOLS_DIR):$$PATH"'

install: _check_variables
	@$(PYTHON3) -m pip install -e . ${PIP_FLAGS}

install-dev: _check_variables
	@$(PYTHON3) -m pip install -e .[dev] ${PIP_FLAGS}

docker-build: _check_variables
	@DOCKER_BUILDKIT=1 docker build \
		--secret id=netsquid_user,env=NETSQUIDPYPI_USER \
		--secret id=netsquid_pwd,env=NETSQUIDPYPI_PWD \
		-t $(DOCKER_IMAGE) .

docker-verify:
	@docker run --rm $(DOCKER_IMAGE) make tests examples

verify: clean lint mypy tests examples _verified

_verified:
	@echo "Everything works!"

.PHONY: clean lint lint-isort lint-black lint-flake8 mypy tests tests-parallel \
        examples tools verify install install-dev docker-build docker-verify help
