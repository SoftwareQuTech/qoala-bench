PYTHON3         = python3
SOURCEDIR       = qoala_bench
GL_HOST         = gitlab.tudelft.nl
GL_PROJECT_ID   = 25060
GL_PROJECT_ID_2 = 18119
GL_PROJECT_ID_3 = 7457
PIP_FLAGS       = --extra-index-url=https://${NETSQUIDPYPI_USER}:${NETSQUIDPYPI_PWD}@pypi.netsquid.org \
                 --extra-index-url=https://__token__:$(GITLAB_PYPI_TOKEN)@$(GL_HOST)/api/v4/projects/$(GL_PROJECT_ID)/packages/pypi/simple \
				 --extra-index-url=https://__token__:$(GITLAB_PYPI_TOKEN)@$(GL_HOST)/api/v4/projects/$(GL_PROJECT_ID_2)/packages/pypi/simple \
				 --extra-index-url=https://__token__:$(GITLAB_PYPI_TOKEN)@$(GL_HOST)/api/v4/projects/$(GL_PROJECT_ID_3)/packages/pypi/simple
		 	 

help:
	@echo "install           Installs the package (editable)."
	@echo "install-dev       Installs the package (editable) with dev extras."
	@echo "verify            Runs the linter, type-checker, and tests."
	@echo "tests             Runs the pytest suite under tests/."
	@echo "tests-parallel    Runs the tests with pytest-xdist (auto core count)."
	@echo "mypy              Runs the mypy type-checker."
	@echo "lint              Runs the linter (isort, black, flake8)."
	@echo "clean             Removes all .pyc files."

_check_variables:
ifndef NETSQUIDPYPI_USER
	$(error Set the environment variable NETSQUIDPYPI_USER before installing)
endif
ifndef NETSQUIDPYPI_PWD
	$(error Set the environment variable NETSQUIDPYPI_PWD before installing)
endif
ifndef GITLAB_PYPI_TOKEN
	$(error Set the environment variable GITLAB_PYPI_TOKEN before installing)
endif

clean:
	@/usr/bin/find . -name '*.pyc' -delete

lint-isort:
	$(info Running isort...)
	@$(PYTHON3) -m isort --check --diff ${SOURCEDIR}

lint-black:
	$(info Running black...)
	@$(PYTHON3) -m black --check ${SOURCEDIR}

lint-flake8:
	$(info Running flake8...)
	@$(PYTHON3) -m flake8 ${SOURCEDIR}


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

install: _check_variables
	@$(PYTHON3) -m pip install -e . ${PIP_FLAGS}

install-dev: _check_variables
	@$(PYTHON3) -m pip install -e .[dev] ${PIP_FLAGS}

verify: clean lint mypy tests _verified

_verified:
	@echo "Everything works!"

.PHONY: clean lint mypy tests tests-parallel verify install install-dev help
