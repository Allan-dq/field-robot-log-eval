# field-robot-log-eval

An ingest, data-quality and evaluation pipeline for public field-robot logs, with failure triage and a
CI regression gate. Independent project on public data; no affiliation with any company.

## Results so far
- 42 public GrandTour missions (legged robot, ETH Zurich): every one scored against a total-station prism.
  The onboard LiDAR-inertial odometry (DLIO) has a median APE of 2.4 cm across missions and beats the leg
  odometry in 42 of 42 ([reports/summary.md](reports/summary.md)).
- Our own KISS-ICP run on raw Livox clouds (one mission): 6.0 cm APE, against 2.0 cm for DLIO on the same
  prism stamps ([reports/eval.md](reports/eval.md)).
- Triage traces the worst missions to ground-truth outliers: one bad prism sample out of 3,385 makes one
  mission's DLIO error 12× higher ([reports/triage.md](reports/triage.md)).
- The CI regression gate catches 14 of 14 seeded data and frame faults
  ([reports/seeded_faults.md](reports/seeded_faults.md)).

Every number comes from the scripts here (`make all`, `make kiss`, `make faults`). The rules for each
step were written before it was first run; later changes are dated in the docs.

## Status
- [x] Ingest: GrandTour zarr topic archives (download with sha256 checks) into canonical Parquet tables with a versioned schema, DuckDB views on top. Re-runs are idempotent, one mission can be re-ingested alone, and a broken archive fails only its own topic.
- [x] Data quality per mission and topic, with criteria written down before the first run: [docs/data_quality.md](docs/data_quality.md). Latest report: [reports/qc.md](reports/qc.md).
- [x] Evaluation: three onboard estimators scored against the total-station prism with evo (APE translation, lever arm from the URDF calibration, 10 s block-bootstrap intervals, paired comparisons). Protocol: [docs/evaluation.md](docs/evaluation.md). Latest report: [reports/eval.md](reports/eval.md).
- [x] Summary across missions: [reports/summary.md](reports/summary.md).
- [x] Triage: bad segments per mission are attributed to ground-truth jumps, estimator input data, estimator jumps or drift, using the independent LiDAR and leg odometry as witnesses; missions with too little path are flagged. Rules: [docs/triage.md](docs/triage.md). Report and plots: [reports/triage.md](reports/triage.md).
- [x] Our own odometry: KISS-ICP 1.3.0 (defaults, LiDAR only) on the raw Livox clouds of one mission, scored with the same protocol. Rules: [docs/kiss_icp.md](docs/kiss_icp.md).
- [ ] RPE / drift per distance; KISS-ICP on more missions.
- [ ] Triage and failure attribution.
- [x] CI regression gate: the full pipeline runs on a committed 10 s fixture and is compared with a baseline under rules written in advance ([docs/regression_gate.md](docs/regression_gate.md)). 14 seeded faults (data problems and code bugs) are run through it: [reports/seeded_faults.md](reports/seeded_faults.md).
- [ ] ROS 1 bag -> ROS 2 MCAP path, Airflow DAG, Docker compose.

## Run
```bash
uv venv --python 3.13 && uv pip install -e ".[dev]"
make all     # download (about 932 MB), ingest, qc, summary
make test
make gate    # regression gate on the fixture
make faults  # seeded faults through the gate
```

## Data
The GrandTour Dataset, Robotic Systems Lab, ETH Zurich (https://grand-tour.leggedrobotics.com/),
Hugging Face `leggedrobotics/grand_tour_dataset`, CC BY-SA 4.0. Missions: all 42 public missions with prism ground truth (`scripts/list_missions.py`, about 932 MB of topic archives;
topics `prism_position`, `dlio_map_odometry`, `anymal_state_odometry`, `tf`, plus `cpt7_ie_tc_odometry` for 2024-11-04-10-57-34).
Raw data is not committed; `data/manifest.json` lists paths, sizes and checksums. The 10 s test fixture in
`tests/fixtures/grandtour_10s/` is a cut of that mission under the same license.

## License
Code: MIT ([LICENSE](LICENSE)). Data and the derived test fixture: CC BY-SA 4.0, see above.

## Layout
- `frle/download.py`: manifest from the Hugging Face tree API, download, checksum checks
- `frle/ingest.py`, `frle/schema.py`: archives -> `data/lake/<table>/<mission>/<topic>.parquet`
- `frle/qc.py`: data-quality checks -> `reports/qc.{json,md}`
- `frle/frames.py`: static-transform convention and prism lever arm
- `frle/evaluate.py`: APE with evo, block bootstrap -> `reports/eval.{json,md}`
- `frle/summary.py`, `frle/triage.py`: cross-mission summary, failure attribution
- `frle/gate.py`, `frle/faults.py`, `config/gate.yaml`: regression gate and seeded faults
- `scripts/make_fixture.py`: cuts the test fixture (the 10 s window with the most turning)
