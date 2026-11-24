PY := .venv/bin/python

.PHONY: data ingest qc eval summary gate faults test lint all
data:        ## download and verify the configured GrandTour topics (about 932 MB, 42 missions)
	$(PY) -m frle download
ingest:      ## archives -> Parquet lake (idempotent; add ARGS=--force to rebuild)
	$(PY) -m frle ingest $(ARGS)
qc:          ## data-quality checks -> reports/qc.{json,md}
	$(PY) -m frle qc
eval:        ## APE against the prism -> reports/eval.{json,md}
	MPLBACKEND=Agg $(PY) -m frle eval
summary:     ## evaluation of all missions + summary -> reports/summary.{json,md}
	MPLBACKEND=Agg $(PY) -m frle summary
gate:        ## regression gate on the committed fixture
	MPLBACKEND=Agg $(PY) -m frle gate
faults:      ## run every seeded fault through the gate -> reports/seeded_faults.{json,md}
	MPLBACKEND=Agg $(PY) scripts/seeded_faults.py
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
all: data ingest qc summary
