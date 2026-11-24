# field-robot-log-eval

Work in progress. An ingest, data-quality and evaluation pipeline for public field-robot logs.
Independent project on public data; no affiliation with any company.

## Status
- [x] Ingest: GrandTour zarr topic archives (download with sha256 checks) into canonical Parquet tables with a versioned schema, DuckDB views on top. Re-runs are idempotent, one mission can be re-ingested alone, and a broken archive fails only its own topic.
- [x] Data quality per mission and topic, with criteria written down before the first run: [docs/data_quality.md](docs/data_quality.md). Latest report: [reports/qc.md](reports/qc.md).
- [ ] Evaluation: score odometry against ground truth with evo (APE/RPE, bootstrap intervals).
- [ ] Triage and failure attribution.
- [ ] CI regression gate, tested with seeded faults.
- [ ] ROS 1 bag -> ROS 2 MCAP path, Airflow DAG, Docker compose.

## Run
```bash
uv venv --python 3.13 && uv pip install -e ".[dev]"
make all     # download (about 41.5 MB), ingest, qc
make test
```

## Data
The GrandTour Dataset, Robotic Systems Lab, ETH Zurich (https://grand-tour.leggedrobotics.com/),
Hugging Face `leggedrobotics/grand_tour_dataset`, CC BY-SA 4.0. Mission used so far: 2024-11-04-10-57-34
(topics `prism_position`, `cpt7_ie_tc_odometry`, `dlio_map_odometry`, `anymal_state_odometry`, `tf`).
Raw data is not committed; `data/manifest.json` lists paths, sizes and checksums. The 10 s test fixture in
`tests/fixtures/grandtour_10s/` is a cut of that mission under the same license.

## Layout
- `frle/download.py`: manifest from the Hugging Face tree API, download, checksum checks
- `frle/ingest.py`, `frle/schema.py`: archives -> `data/lake/<table>/<mission>/<topic>.parquet`
- `frle/qc.py`: data-quality checks -> `reports/qc.{json,md}`
- `scripts/make_fixture.py`: cuts the test fixture
