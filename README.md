# Milestone 1 — 2409.08594–2409.13593

## 1. Setup (run inside this code directory)

```bash
conda activate arxiv-ds
python -m pip install -r src/requirements.txt
python -c "import shutil; shutil.copyfile('.env.example','.env')"
```
If the environment does not exist: `conda env create -f environment.yml`.
Open `.env`, set CONTACT_EMAIL and S2_API_KEY. Never commit .env or share your key.
The copy command is for first setup only: do not overwrite an existing .env.

## 2. Smoke run, then full run

```bash
python -m src.crawl --limit 10
python -m src.crawl
```
Default full range contains 5,000 IDs. Re-run the same command to resume/retry.
One process at a time. Do not run this simultaneously on multiple machines against arXiv.
Ctrl+C stops; completed source receipts and reference checkpoints survive.
Discovery batches 50 IDs, arXiv requests are at least 3.1 seconds apart, and S2 at least
1.1 seconds apart with one key. Respects bounded backoff; long Retry-After pauses fail the
current task for a later run. Do not rerun immediately after a service cooldown.
`--refresh` refreshes metadata/references, while valid source version files remain cached.
Source size limits: 128 MiB HTTP response and 256 MiB decompressed data; oversize items
are explicit errors, never silent successes. Adjust the constants only after checking disk/RAM.

The API key is assumed to be a Semantic Scholar Academic Graph API key.
It does not speed up arXiv. At 3.1 seconds per request, 5,000 source downloads alone
have a theoretical request-spacing floor of about 4.3 hours; versions, network and retries add time.
No runtime guarantee is made.

## 3. What is saved

- data/metadata: publication metadata, all revision dates and version count.
- data/raw/<paper>/vN: original .tex/.bib, receipt with checksums and size measurements.
- data/references: all Semantic Scholar reference records, including non-arXiv references.
- data/status and s2_status: separate source and reference progress/errors.
- data/tables/papers, references: explicit-schema Parquet shards, 10,000 rows per shard.
- outputs/paper_stats.csv and summary.json: analysis for the current selected range.

Incomplete publications are retained in papers when metadata exists. They are not counted
as complete in the statistics. References exports keep arXiv-keyed candidates only.
`ref_submission_date` is filled only from verified local arXiv metadata; it remains null
for external references not yet resolved. S2 publicationDate is never mislabeled as submission date.
Before finalizing M1, run `python -m src.enrich_dates` to attempt resolution of those extra referenced IDs (additional API time). Explain any remaining missing dates in the report.
For a non-default crawl directory, pass the same --data-dir to enrich_dates and analyze. Rebuild analysis with `python -m src.analyze` after enrichment.
Source stage timings are measured per paper. S2 timings are measured separately; they overlap.
paper_span_seconds measures first stage start to last stage finish for each paper in the same run (including queue gaps, excluding batched discovery). Full system wall time is the benchmark wall time, not their sum. Resume runs are not cold benchmarks.
The selected range is overwritten in assignment.json each run; to report all 5,000 IDs, finish
with the full-range command, not --limit 10. Cached data for other IDs is not deleted.

## 4. CPU-only Colab benchmark

Upload/clone your own code, select CPU runtime, install dependencies and enter your key via
getpass or Colab Secrets (do not put it into a saved notebook cell). Use a fresh data directory.

```bash
python -m src.benchmark --data-dir data_benchmark --out stats -- python -m src.crawl --data-dir data_benchmark
```

Keep Colab persistent backups (e.g. mounted Drive) so a runtime reset does not erase hours
of data. You can choose an absolute Drive path with --data-dir. Record that storage choice
in your benchmark. A resumed run must be labelled resumed; it is not a cold run.
Disk measurements cover the selected data directory, not the whole operating system.
RAM and disk maxima are sampled estimates. Record Colab machine details and package versions:
`python -m pip freeze > installed-versions.txt` (retain with benchmark evidence).

## 5. Report: a SECOND repository

The sibling report/ directory is a separate Jupyter Book project pinned to v1 for reproducibility.
Copy it to its own public repository. Copy actual outputs/paper_stats.csv, outputs/summary.json,
stats/benchmark.json and stats/benchmark_samples.csv into report/results/.
These small derived reporting inputs belong in the report repo; raw corpus does not.

```bash
cd ../report
python -m pip install -r requirements.txt
jupyter-book build . --all --warningiserror
```

Figures and tables execute during build. Build intentionally fails if real inputs are missing.
Fill in group name, execution environment and interpretation after real collection; translate
prose if required by your programme. Enable GitHub Pages -> Source: GitHub Actions.
The provided workflow publishes on pushes to main. M2 can add a chapter to _toc.yml.
M1 submits code URL + book URL; no intermediate Hugging Face upload is required.

## 6. Validation and provenance

```bash
python -m pytest -q
```

See ATTRIBUTION.md for reused code and assistance. Understand the implementation and check
course rules before submission. Data quality and live API performance require your actual run.
Never include .env, raw data, archives or API credentials in the code repository.
