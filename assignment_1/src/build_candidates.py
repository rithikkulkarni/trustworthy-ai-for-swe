"""
Build the assignment's required candidates.jsonl from the detector's raw
output plus the Stack v2 sampling manifest (Assignment 1, Task 5).

pii_detect.py's output is keyed by local filename and carries detection
metadata (type, line, rule, redacted context, LLM verdict); it has no Stack
v2 provenance because it also runs on plain local directories like data/5.
sample_stackv2.py's manifest has the provenance (blob_id, src_encoding,
repo_name, path, revision/snapshot/directory_id) keyed by that same local
filename. This script joins the two on `file` / `local_file` and selects up
to --max representative candidates, spread across PII types rather than
just taking the first N (which would be dominated by whichever type is most
common).

Selection: round-robin across pii_type, each type's own candidates ordered
by (has an LLM verdict of is_real_pii=true) first, then by file name, so
that reused fields the report already vouches for are what get submitted.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rank_key(candidate: dict) -> tuple[int, str]:
    verdict = candidate.get("llm_verdict")
    confirmed = 0 if (verdict is not None and verdict.get("is_real_pii")) else 1
    return (confirmed, candidate["file"])


def select_representative(candidates: list[dict], max_n: int) -> list[dict]:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_type[c["pii_type"]].append(c)
    for items in by_type.values():
        items.sort(key=rank_key)

    selected: list[dict] = []
    types = sorted(by_type)
    i = 0
    while len(selected) < max_n and any(by_type[t] for t in types):
        t = types[i % len(types)]
        if by_type[t]:
            selected.append(by_type[t].pop(0))
        i += 1
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detections", type=Path, required=True, help="pii_detect.py output JSONL")
    parser.add_argument("--manifest", type=Path, required=True, help="sample_stackv2.py manifest JSONL")
    parser.add_argument("--out", type=Path, required=True, help="Output candidates.jsonl path")
    parser.add_argument("--max", type=int, default=20, help="Max instances to include")
    args = parser.parse_args()

    detections = load_jsonl(args.detections)
    manifest_rows = load_jsonl(args.manifest)
    manifest_by_file = {row["local_file"]: row for row in manifest_rows}

    joined = []
    unmatched = 0
    for c in detections:
        row = manifest_by_file.get(c["file"])
        if row is None:
            unmatched += 1
            continue
        joined.append(c)

    selected = select_representative(joined, args.max)

    with args.out.open("w", encoding="utf-8") as f:
        for c in selected:
            row = manifest_by_file[c["file"]]
            verdict = c.get("llm_verdict")
            flag_reason = f"detector_rule={c['method']}"
            if verdict is not None:
                flag_reason += (
                    f"; llm_verdict={verdict.get('is_real_pii')}"
                    f" (confidence={verdict.get('confidence')})"
                )
            record = {
                "blob_id": row["blob_id"],
                "src_encoding": row["src_encoding"],
                "repo_name": row["repo_name"],
                "path": row["path"],
                "revision_id": row.get("revision_id"),
                "snapshot_id": row.get("snapshot_id"),
                "directory_id": row.get("directory_id"),
                "pii_type": c["pii_type"],
                "line_span": c["line_span"],
                "flag_reason": flag_reason,
            }
            f.write(json.dumps(record) + "\n")

    print(
        f"Wrote {len(selected)} candidates to {args.out} "
        f"(joined={len(joined)}, unmatched={unmatched}, pool={len(detections)})"
    )


if __name__ == "__main__":
    main()
