# The Inevitable Engine — common commands (AGENTS.md "Verify locally").
# Works in UserLAnd/Termux: no daemons, no background services.
PYTHON ?= python3
W ?= $(shell date -u +%G-W%V)

.PHONY: help install lint test guardrail dry-run validate review ingest editloop evidence clean

help:
	@echo "make install    # create .venv and install pinned dependencies"
	@echo "make lint       # schema/claims/brand/content validators (Content CI twin)"
	@echo "make test       # unit tests, zero API calls"
	@echo "make guardrail  # prove a planted false claim is rejected"
	@echo "make dry-run    # full weekly cycle with canned outputs, zero cost (W=$(W))"
	@echo "make review W=2026-W43   # your decision session (interactive)"
	@echo "make ingest W=2026-W43   # ingest pasted stats and refresh scores"
	@echo "make editloop W=2026-W43 # propose the voice learning PR"

install:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements-dev.txt
	@echo "installed. Use: .venv/bin/python -m amplify --help"

lint validate:
	$(PYTHON) -m amplify validate

test:
	$(PYTHON) -m pytest -q

guardrail:
	$(PYTHON) -m amplify guardrail

dry-run:
	$(PYTHON) -m amplify run-weekly --week $(W) --dry-run

review:
	$(PYTHON) -m amplify review --week $(W)

ingest:
	$(PYTHON) -m amplify ingest --week $(W) --no-agent

editloop:
	$(PYTHON) -m amplify editloop --week $(W)

evidence:
	$(PYTHON) -m amplify evidence list

clean:
	rm -rf .pytest_cache content/dry-run analytics/marketing.sqlite
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
