.PHONY: venv install check-venv test lint typecheck check compose-config data artifacts figures notebooks

VENV_DIR ?= .venv
PYTHON ?= $(VENV_DIR)/bin/python
BOOTSTRAP_PYTHON ?= python3.12

venv:
	@command -v "$(BOOTSTRAP_PYTHON)" >/dev/null || { \
		echo "Python 3.12 is required. Set BOOTSTRAP_PYTHON to its executable."; \
		exit 1; \
	}
	@"$(BOOTSTRAP_PYTHON)" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 is required")'
	@test -x "$(PYTHON)" || "$(BOOTSTRAP_PYTHON)" -m venv "$(VENV_DIR)"
	@"$(PYTHON)" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1 || { \
		echo "Project environment must use Python 3.12. Remove the incompatible .venv and run 'make install'."; \
		exit 1; \
	}

install: venv
	"$(PYTHON)" -m pip install -r requirements.txt
	"$(PYTHON)" -m pip install --no-deps -e .

check-venv:
	@test -x "$(PYTHON)" || { \
		echo "Project environment missing. Run 'make install' with Python 3.12."; \
		exit 1; \
	}
	@"$(PYTHON)" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1 || { \
		echo "Project environment must use Python 3.12. Remove the incompatible .venv and run 'make install'."; \
		exit 1; \
	}

test: check-venv
	"$(PYTHON)" -m pytest

lint: check-venv
	"$(PYTHON)" -m ruff check .

typecheck: check-venv
	"$(PYTHON)" -m mypy

compose-config:
	docker compose config --quiet

check: test lint typecheck compose-config

# Download and checksum-verify the NHANES and MEPS public-use files into data/raw.
data: check-venv
	"$(PYTHON)" scripts/retrieve_surveys.py

# Rebuild the NHANES and MEPS artifacts and manifests from the verified files in data/raw.
# Part D and ClinicalTrials.gov are dated API snapshots: rebuild them with
# `scripts/build_public_landscape.py partd trials` after their retrieve_* scripts.
artifacts: check-venv
	"$(PYTHON)" -m ckd_intelligence.analysis.nhanes_pipeline
	"$(PYTHON)" scripts/build_public_landscape.py meps

figures: check-venv
	"$(PYTHON)" scripts/make_figures.py

# Execute every notebook in place so committed outputs match the current artifacts.
notebooks: check-venv
	for notebook in notebooks/*.ipynb; do \
		PATH="$(abspath $(VENV_DIR))/bin:$$PATH" "$(PYTHON)" -m jupyter nbconvert --to notebook \
			--execute --inplace "$$notebook" --ExecutePreprocessor.timeout=900 || exit 1; \
	done
