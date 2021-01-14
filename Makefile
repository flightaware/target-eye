BLACK=black
MYPY=mypy
PYLINT=pylint
PYTHON=python3

# Run a Python tool with a specified module name
pytool = . venv/bin/activate && $(PYTHON) -m $(1) $(2)

.PHONY: all beautiful check clean format lint pip-compile pip-sync test type-check venv

# Include all the Docker-specific targets from their own file
include Makefile.docker

clean:
	rm -rf venv build dist *.egg-info
	find . -iname "*.pyc" -exec rm -- {} +

venv: venv/bin/activate
	. venv/bin/activate

venv/bin/activate:
	test -d venv || $(PYTHON) -m venv venv
	$(call pytool, pip, install pip-tools)

pip-compile: venv
	. venv/bin/activate && make -C requirements all

pip-sync: venv pip-compile
	. venv/bin/activate && venv/bin/pip-sync $(wildcard requirements/*.txt)

pip-sync-base: venv 
	. venv/bin/activate && venv/bin/pip-sync $(wildcard requirements/base.txt)

pip-all: pip-compile pip-sync

check: type-check test lint

format: venv
	$(call pytool, $(BLACK), *.py fa_target_eye test)

beautiful: format

lint: venv
	$(call pytool, $(PYLINT), fa_target_eye test)

type-check: venv
	$(call pytool, $(MYPY), --check-untyped-defs fa_target_eye test)

test: venv
	$(call pytool, pytest, test)

