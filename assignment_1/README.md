# README

Assignment 1, Task 5 (PII detection in code)

## Dependencies

```
pip install -r requirements.txt
```

requirements.txt:
```
google-genai>=1.0.0
python-dotenv>=1.0.0
datasets>=2.19.0
huggingface_hub>=0.23.0
boto3>=1.34.0
smart_open[s3]>=7.0.0
```

- `google-genai` (LLM verification calls)
- `python-dotenv` (loads `.env`)
- `datasets` + `huggingface_hub` (Stack v2 metadata streaming)
- `boto3` + `smart_open[s3]` (Stack v2 file content download from the SoftwareHeritage S3 bucket)

Only `pii_detect.py --dir data/5 ...` (the starter-data evaluation) needs nothing beyond `google-genai`/`python-dotenv`. Sampling from Stack v2 itself needs the credentials below.

## Credentials (`.env`)

Create a `.env` file at the repo root that mocks `.env.example` (same directory `load_dotenv()` walks up to find) with:

```
GEMINI_API_KEY=...        # Google AI Studio key, for the LLM verification stage
HF_TOKEN=...              # Hugging Face token; the account must have accepted the gated-access terms on
                          # huggingface.co/datasets/bigcode/the-stack-v2-dedup
AWS_ACCESS_KEY_ID=...     # SoftwareHeritage/AWS S3 credentials, granted
AWS_SECRET_ACCESS_KEY=... # separately via the Stack v2 content-access agreement
```

`.env` should be gitignored if using git.

## Tools / models used

- **Detection heuristics**: Python regex & denylist/entropy
  rules (no ML).
- **LLM verification**: `gemini-3.5-flash-lite` via the `google-genai` SDK, called only on `name`/`username`/`email` candidates (never `password`/`key`/`ip_address`)

## How to run

All commands run from root. Configurable parameters (sample size, filters, entropy thresholds, LLM model/pricing, report verbosity) all live in `src/config.json`. Edit it to change defaults, or pass the matching CLI flag to override a single run. Run any script with `--help` to see all flags.

### 1. Evaluate the detector on the starter data (`data/5`)

```
python src/pii_detect.py --dir data/5 --out data5_candidates.jsonl
```

Writes `data5_candidates.jsonl` (one record per flagged line, redacted context) and `data5_candidates.report.md` (human-readable summary: counts by type/detector rule, flagged examples). `data/5` is 206 Java files with 6 known positives (one per type); the report's "files flagged" / "candidates by type" sections are how correctness is checked.

### 2. Sample files from The Stack v2

```
python src/sample_stackv2.py
```

Streams `bigcode/the-stack-v2-dedup`, config `"Java"`, shuffled with a fixed seed (`config.json: sampling.seed`, default 42) for reproducibility. Filters out generated/vendored files and files outside a 200 B–200 KB size range, caps at 3 files per `repo_name` so no single repository dominates, and downloads each kept file's content from `s3://softwareheritage/content/{blob_id}`. Writes:

- `data/stackv2_sample/*.java`: the sampled file contents
- `stackv2_sample_manifest.jsonl`: one row per sampled file with its Stack v2 provenance (`blob_id`, `src_encoding`, `repo_name`, `path`, `revision_id`, `snapshot_id`, `directory_id`, `star_events_count`, `length_bytes`)

Default sample size is `config.json: sampling.n` (currently 3000). You can override with `--n <count>`. Re-running with the same seed reproduces the same sample unless the output directory already has files in it. Clear `data/stackv2_sample/` first for a clean re-run.

### 3. Run the detector on the sampled files

```
python src/pii_detect.py --dir data/stackv2_sample --out stackv2_candidates.jsonl --verify-llm
```

Same detector as step 1, applied to the Stack v2 sample instead of `data/5`, with the LLM verification pass enabled. Writes `stackv2_candidates.jsonl` and `stackv2_candidates.report.md`.

### 4. Build the graded `candidates.jsonl`

```
python src/build_candidates.py --detections stackv2_candidates.jsonl --manifest stackv2_sample_manifest.jsonl --out candidates.jsonl --max 20
```

Joins step 3's detections back to step 2's manifest on filename, and selects up to `--max` representative instances (round-robin across PII types, preferring ones the LLM verifier also confirmed) in the schema the assignment requires: `blob_id`, `src_encoding`, `repo_name`, `path`, `revision_id`/`snapshot_id`/`directory_id`, `line_span`, `flag_reason`. No raw matched value is ever written to this file or to any intermediate output (see **Safety** below).

## How the submitted instances were obtained

1. Sampled ~3,000 Java files from `bigcode/the-stack-v2-dedup` (the near-dedup split, chosen to reduce the fork/copy-paste duplication problem discussed in the report), filtered and repo-capped as described above (step 2).
2. Ran the three-stage detector: regex candidate generation → placeholder denylist/entropy filtering → optional LLM verification for the semantically ambiguous types (step 3).
3. Joined the flagged candidates back to their Stack v2 provenance and selected up to 20 representative instances spanning all detected types (step 4) into `candidates.jsonl`.

## Tracing an instance back to The Stack v2

Each row in `candidates.jsonl` carries `blob_id` and `src_encoding`, the two fields the official Stack v2 retrieval procedure needs:

```python
from smart_open import open as smart_open_open
s3_url = f"s3://softwareheritage/content/{blob_id}"
with smart_open_open(s3_url, "rb", compression=".gz",
                      transport_params={"client": s3_client}) as fin:
    content = fin.read().decode(src_encoding)
```

`repo_name` + `path` locate the file within its repository. `revision_id`/`snapshot_id`/`directory_id` (whichever the row has, `the-stack-v2-dedup` provides all three) pin the exact commit/tree the file was captured from. `line_span` localizes the issue within the file without requiring the raw content to be shipped alongside the metadata.

## Safety

Per the assignment's handling rules, this pipeline never prints or writes a raw matched PII value to any output file:

- `Candidate.value` (the actual matched string) is used only in-memory to build the LLM verification payload for `name`/`username`/`email` types and is never serialized to `candidates.jsonl`, `*.report.md`, or stdout.
- Every context snippet (`context_redacted` in the detector's raw JSONL output) has **every** PII-shaped value found in that +/- 1 line window redacted, not just the one candidate it belongs to. This closes a gap found during development where two real values on the same or an adjacent line (e.g. two co-authors credited together) could each unredact the other.
- `password` values are never sent to the LLM at all (see `report.md` §2).
- Nothing in this repo attempts to use, validate, or contact any discovered credential, email, or name.
