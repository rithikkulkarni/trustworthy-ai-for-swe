"""
Sample a subset of The Stack v2 for PII detection.

Strategy:
- Java only, from bigcode/the-stack-v2-dedup (near-dedup split, to avoid the
  fork/copy-paste duplication problem noted in the detector's limitations).
- Streamed and shuffled with a fixed seed for reproducibility.
- Drop generated/vendored files (`is_generated`, `is_vendor` fields) and files
  outside a sane size range, since those are noise the detector was never
  meant to run on.
- Capped per repo_name so one popular/forked repo can't dominate the sample.

This script only downloads *metadata* rows (blob_id, repo_name, path, etc.)
plus streamed file content via the datasets `.map(download_contents)` step
from the official Stack v2 usage example. It writes the sampled rows'
content to local .java files under --out-dir, plus a manifest.jsonl that
records the Stack v2 provenance fields (blob_id, src_encoding, repo_name,
path, revision_id/snapshot_id/directory_id) needed for candidates.jsonl
later.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import CONFIG  # noqa: E402 - after load_dotenv, before use


def build_stream(hf_token: str, dataset_name: str, dataset_revision: str, language_config: str, seed: int, buffer_size: int):
    from datasets import load_dataset

    ds = load_dataset(
        dataset_name,
        language_config,
        split="train",
        streaming=True,
        token=hf_token,
        revision=dataset_revision,
    )
    ds = ds.shuffle(seed=seed, buffer_size=buffer_size)
    return ds


def passes_filters(row: dict, min_bytes: int, max_bytes: int, extension: str) -> bool:
    if row.get("is_generated") or row.get("is_vendor"):
        return False
    length = row.get("length_bytes") or 0
    if length < min_bytes or length > max_bytes:
        return False
    if row.get("extension") != extension:
        return False
    return True


def download_content(row: dict, s3_client) -> str:
    from smart_open import open as smart_open_open

    s3_url = f"s3://softwareheritage/content/{row['blob_id']}"
    with smart_open_open(
        s3_url, "rb", compression=".gz", transport_params={"client": s3_client}
    ) as fin:
        return fin.read().decode(row["src_encoding"], errors="replace")


def main() -> None:
    sc = CONFIG.sampling
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-name", default=sc.dataset_name)
    parser.add_argument(
        "--dataset-revision",
        default=sc.dataset_revision,
        help="Pinned dataset commit SHA, so a re-run reproduces the same "
             "shuffled stream even if the dataset's default branch moves",
    )
    parser.add_argument("--language-config", default=sc.language_config)
    parser.add_argument("--extension", default=sc.extension)
    parser.add_argument("--n", type=int, default=sc.n, help="Target sample size (post-filter)")
    parser.add_argument("--seed", type=int, default=sc.seed)
    parser.add_argument("--buffer-size", type=int, default=sc.buffer_size, help="Shuffle buffer size")
    parser.add_argument("--min-bytes", type=int, default=sc.min_bytes)
    parser.add_argument("--max-bytes", type=int, default=sc.max_bytes)
    parser.add_argument("--max-files-per-repo", type=int, default=sc.max_files_per_repo)
    parser.add_argument("--out-dir", type=Path, default=Path(sc.out_dir))
    parser.add_argument("--manifest", type=Path, default=Path(sc.manifest_path))
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=sc.scan_limit,
        help="Safety cap on rows pulled from the stream before giving up",
    )
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        sys.exit("HF_TOKEN not set (check .env)")

    aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not aws_key or not aws_secret:
        sys.exit("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set (check .env)")

    import boto3

    session = boto3.Session(aws_access_key_id=aws_key, aws_secret_access_key=aws_secret)
    s3_client = session.client("s3")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    stream = build_stream(hf_token, args.dataset_name, args.dataset_revision, args.language_config, args.seed, args.buffer_size)

    per_repo_count: dict[str, int] = {}
    kept = 0
    scanned = 0

    with args.manifest.open("w", encoding="utf-8") as manifest_f:
        for row in stream:
            scanned += 1
            if scanned > args.scan_limit:
                print(f"[stop] scan_limit ({args.scan_limit}) reached", file=sys.stderr)
                break
            if kept >= args.n:
                break

            if not passes_filters(row, args.min_bytes, args.max_bytes, args.extension):
                continue

            repo = row["repo_name"]
            if per_repo_count.get(repo, 0) >= args.max_files_per_repo:
                continue

            try:
                content = download_content(row, s3_client)
            except Exception as exc:  # noqa: BLE001 - log and skip on any S3/decode failure
                print(f"[skip] {row['blob_id']}: {exc}", file=sys.stderr)
                continue

            per_repo_count[repo] = per_repo_count.get(repo, 0) + 1
            kept += 1

            local_name = f"{kept:05d}_{row['blob_id'][:12]}.{args.extension}"
            (args.out_dir / local_name).write_text(content, encoding="utf-8")

            manifest_f.write(
                json.dumps(
                    {
                        "local_file": local_name,
                        "blob_id": row["blob_id"],
                        "src_encoding": row["src_encoding"],
                        "repo_name": row["repo_name"],
                        "path": row["path"],
                        "revision_id": row.get("revision_id"),
                        "snapshot_id": row.get("snapshot_id"),
                        "directory_id": row.get("directory_id"),
                        "star_events_count": row.get("star_events_count"),
                        "length_bytes": row.get("length_bytes"),
                    }
                )
                + "\n"
            )

            if kept % 50 == 0:
                print(f"[progress] kept={kept} scanned={scanned}", file=sys.stderr)

    print(
        f"Done. kept={kept} scanned={scanned} unique_repos={len(per_repo_count)} "
        f"out_dir={args.out_dir} manifest={args.manifest}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
