PY := .venv/bin/python

.PHONY: data ingest qc eval test lint all
data:        ## download and verify the configured GrandTour topics (about 41.5 MB for one mission)
	$(PY) -m frle download
ingest:      ## archives -> Parquet lake (idempotent; add ARGS=--force to rebuild)
	$(PY) -m frle ingest $(ARGS)
qc:          ## data-quality checks -> reports/qc.{json,md}
	$(PY) -m frle qc
eval:        ## APE against the prism -> reports/eval.{json,md}
	MPLBACKEND=Agg $(PY) -m frle eval
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
all: data ingest qc eval
