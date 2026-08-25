"""
PII/privacy data-quality detector (Assignment 1, Task 5 — TAI4SE).

Pipeline
--------
1. Regex/heuristic candidate generation per PII type (high recall).
2. Placeholder/denylist filtering + entropy scoring (precision boost),
   applied without any network call.
3. Optional LLM verification pass (Gemini 2.5 Flash-Lite) for the two
   types where heuristics are semantically weak: `name` and `username`
   (telling a real person's identifier apart from a class/product name
   or a role account). `password`, `key`, and `ip_address` are never
   sent to the LLM — entropy/shape and RFC-1918 membership are decided
   locally so real-looking secrets are never shipped to a third-party
   API.

The LLM stage reads its API key from the `GEMINI_API_KEY` environment
variable (loaded from a `.env` file in the repo root if present, via
python-dotenv). Never commit that file or print its contents.

`detect_candidates(text)` is the reusable core: it takes raw source
text and returns Candidate objects, independent of where the text came
from. The CLI below applies it to local files (the data/5 starter set);
the same function is meant to be called per-row when streaming Stack v2
in the later stage of the assignment, with blob_id/repo_name/etc.
attached from the dataset row rather than from a filesystem path.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from config import CONFIG

# ---------------------------------------------------------------------------
# Candidate record
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Candidate:
    pii_type: str          # email | name | username | password | key | ip_address
    line_no: int            # 1-indexed line the value appears on
    value: str               # the matched literal (never printed to stdout/report)
    method: str              # which detector rule fired, e.g. "regex:email"
    context: str              # +/- 1 line of surrounding source, value redacted
    signal: dict              # extra evidence (entropy, denylist hits, etc.)
    llm_verdict: Optional[dict] = None  # filled in by the LLM verifier stage


def _redact(line: str, value: str) -> str:
    if not value:
        return line
    return line.replace(value, "*" * min(len(value), 8))


def _context(lines: list[str], idx: int, value: str) -> str:
    lo, hi = max(0, idx - 1), min(len(lines), idx + 2)
    return "\n".join(_redact(lines[i], value) for i in range(lo, hi))


# ---------------------------------------------------------------------------
# Placeholder / denylist tables
# ---------------------------------------------------------------------------

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "domain.com",
    "email.com", "yourcompany.com", "company.com", "mail.com", "foo.com",
    "bar.com", "acme.com", "sample.com", "site.com", "website.com",
}

PLACEHOLDER_LOCALPARTS = {
    "user", "test", "admin", "foo", "bar", "someone", "xxx", "info",
    "noreply", "no-reply", "support", "name", "email", "example",
    "yourname", "johndoe", "janedoe",
}

PLACEHOLDER_NAMES = {
    "john doe", "jane doe", "foo bar", "test user", "first last",
    "your name", "john smith", "jane smith",
}

PLACEHOLDER_SECRETS = {
    "changeme", "change_me", "changeit", "password", "password123",
    "123456", "12345678", "secret", "test", "xxxxxx", "yourpassword",
    "dummy", "placeholder", "admin", "root", "pass", "letmein",
}

LOOPBACK_WILDCARD_EXTRA = {"0.0.0.0", "255.255.255.255"}

# Two-word phrases that match the "Capitalized Capitalized" name shape but
# are common non-name tokens likely to appear near copyright/author lines.
NAME_STOPWORDS = {
    "all rights", "open source", "apache license", "software foundation",
    "data service", "unit test", "test case", "base class",
}

_AUTHOR_CONTEXT_RE = re.compile(
    r"@author|created\s+by|written\s+by|author\s*:",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Regex patterns per type
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GOOGLE_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")
SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")
GENERIC_KEY_ASSIGN_RE = re.compile(
    r'(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|'
    r'client[_-]?secret|app[_-]?key|bearer[_-]?token)\b\s*[=:]\s*"([^"]{12,})"'
)

PASSWORD_ASSIGN_RE = re.compile(
    r'(?i)\b(password|passwd|pwd)\b\s*[=:]\s*"([^"]{3,})"'
)
JDBC_PASSWORD_RE = re.compile(r"(?i)password=([^&\"'\s]{3,})")

USERNAME_ASSIGN_RE = re.compile(
    r'(?i)\b(username|user_name|login|handle)\b\s*[=:]\s*"([^"]{2,})"'
)
# A bare handle-shaped token following an @author/"Created by" marker, e.g.
# "@author mkolvane81". Requires a digit so it doesn't swallow ordinary
# single-word tokens; deliberately does NOT match the Capitalized-Capitalized
# shape that NAME_CANDIDATE_RE targets, so the same marker line routes to
# exactly one of name/username based on the identifier's own shape, per the
# task's scoping rule.
HANDLE_AT_AUTHOR_RE = re.compile(r"\b([A-Za-z][A-Za-z]*[0-9][A-Za-z0-9]*)\b")

NAME_CANDIDATE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+)\b"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_secret(value: str) -> bool:
    """Entropy/shape heuristic: real generated secrets are high-entropy,
    mixed-character strings; placeholders are short dictionary words."""
    if value.lower() in PLACEHOLDER_SECRETS:
        return False
    if len(value) < CONFIG.detection.min_secret_length:
        return False
    has_digit = any(c.isdigit() for c in value)
    has_alpha = any(c.isalpha() for c in value)
    entropy = shannon_entropy(value)
    return entropy >= CONFIG.detection.entropy_threshold and has_digit and has_alpha


def is_placeholder_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return True  # not a valid IP at all -> not a candidate
    if value in LOOPBACK_WILDCARD_EXTRA:
        return True
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        return True
    return False


def is_placeholder_email(value: str) -> bool:
    local, _, domain = value.partition("@")
    if domain.lower() in PLACEHOLDER_DOMAINS:
        return True
    if local.lower() in PLACEHOLDER_LOCALPARTS:
        return True
    return False


def is_placeholder_name(value: str) -> bool:
    return value.lower() in PLACEHOLDER_NAMES or value.lower() in NAME_STOPWORDS


# ---------------------------------------------------------------------------
# Per-type detectors — each returns a list of Candidate (value + signal only;
# line_no/context are filled in by the caller, which has the full line list).
# ---------------------------------------------------------------------------


def _find_email(line: str) -> list[tuple[str, str, dict]]:
    out = []
    for m in EMAIL_RE.finditer(line):
        value = m.group(0)
        if is_placeholder_email(value):
            continue
        out.append((value, "regex:email", {}))
    return out


def _find_ip(line: str) -> list[tuple[str, str, dict]]:
    out = []
    for m in IPV4_RE.finditer(line):
        value = m.group(0)
        if is_placeholder_ip(value):
            continue
        ip = ipaddress.ip_address(value)
        out.append((value, "regex:ipv4", {"is_private": ip.is_private}))
    return out


def _find_key(line: str) -> list[tuple[str, str, dict]]:
    out = []
    for pat, name in (
        (AWS_KEY_RE, "regex:key:aws"),
        (GOOGLE_KEY_RE, "regex:key:google"),
        (GITHUB_TOKEN_RE, "regex:key:github"),
        (SLACK_TOKEN_RE, "regex:key:slack"),
    ):
        for m in pat.finditer(line):
            out.append((m.group(0), name, {"provider_pattern": True}))
    for m in GENERIC_KEY_ASSIGN_RE.finditer(line):
        value = m.group(2)
        if looks_like_secret(value):
            out.append((value, "regex:key:generic_assign",
                        {"entropy": round(shannon_entropy(value), 2)}))
    return out


def _find_password(line: str) -> list[tuple[str, str, dict]]:
    out = []
    for m in PASSWORD_ASSIGN_RE.finditer(line):
        value = m.group(2)
        if looks_like_secret(value):
            out.append((value, "regex:password:assign",
                        {"entropy": round(shannon_entropy(value), 2)}))
    for m in JDBC_PASSWORD_RE.finditer(line):
        value = m.group(1)
        if looks_like_secret(value):
            out.append((value, "regex:password:jdbc_url",
                        {"entropy": round(shannon_entropy(value), 2)}))
    return out


def _find_username(line: str) -> list[tuple[str, str, dict]]:
    out = []
    for m in USERNAME_ASSIGN_RE.finditer(line):
        value = m.group(2)
        if value.lower() in PLACEHOLDER_LOCALPARTS or value.lower() in PLACEHOLDER_SECRETS:
            continue
        if "@" in value:  # looks like an email, not a bare handle
            continue
        out.append((value, "regex:username:assign", {}))
    if _AUTHOR_CONTEXT_RE.search(line):
        marker_end = _AUTHOR_CONTEXT_RE.search(line).end()
        for m in HANDLE_AT_AUTHOR_RE.finditer(line, marker_end):
            value = m.group(1)
            if value.lower() in PLACEHOLDER_LOCALPARTS:
                continue
            out.append((value, "regex:username:author_context_handle", {}))
    return out


def _find_name(line: str) -> list[tuple[str, str, dict]]:
    out = []
    if not _AUTHOR_CONTEXT_RE.search(line):
        return out
    for m in NAME_CANDIDATE_RE.finditer(line):
        value = m.group(1)
        if is_placeholder_name(value):
            continue
        out.append((value, "regex:name:author_context", {}))
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def detect_candidates(text: str) -> list[Candidate]:
    lines = text.splitlines()
    candidates: list[Candidate] = []
    for idx, line in enumerate(lines):
        line_no = idx + 1

        for value, method, signal in _find_email(line):
            candidates.append(Candidate("email", line_no, value, method,
                                         _context(lines, idx, value), signal))
        for value, method, signal in _find_ip(line):
            candidates.append(Candidate("ip_address", line_no, value, method,
                                         _context(lines, idx, value), signal))
        for value, method, signal in _find_key(line):
            candidates.append(Candidate("key", line_no, value, method,
                                         _context(lines, idx, value), signal))
        for value, method, signal in _find_password(line):
            candidates.append(Candidate("password", line_no, value, method,
                                         _context(lines, idx, value), signal))
        for value, method, signal in _find_username(line):
            candidates.append(Candidate("username", line_no, value, method,
                                         _context(lines, idx, value), signal))
        for value, method, signal in _find_name(line):
            candidates.append(Candidate("name", line_no, value, method,
                                         _context(lines, idx, value), signal))
    return candidates


# ---------------------------------------------------------------------------
# LLM verification (name / username / email only — see module docstring for
# why password/key/ip_address never reach this stage)
# ---------------------------------------------------------------------------

LLM_VERIFIED_TYPES = {"name", "username", "email"}
# gemini-2.5-flash-lite has been retired for this API key ("no longer
# available to new users" as of 2026-08-24); Google's own API error message
# points at gemini-3.5-flash-lite as the replacement, confirmed against
# https://ai.google.dev/gemini-api/docs/pricing — checked 2026-08-24.
LLM_MODEL = CONFIG.llm.model
GEMINI_INPUT_USD_PER_M_TOKENS = CONFIG.llm.input_usd_per_m_tokens
GEMINI_OUTPUT_USD_PER_M_TOKENS = CONFIG.llm.output_usd_per_m_tokens

_VERIFIER_SYSTEM = """You audit source files scraped from public code repositories \
for a data-quality research project. For each candidate line, decide whether the \
highlighted value is a REAL identifier belonging to an actual individual person \
(a real personal name, a real personal account handle, or a real person's email \
address) as opposed to: a placeholder/tutorial value, a role or bot account \
(e.g. "admin", "noreply"), or a non-person identifier (a class name, product \
name, or company name that happens to match the pattern).

Respond with a JSON array, one object per candidate, in the same order, each \
with exactly these fields:
{"id": <int>, "is_real_pii": <true|false>, "confidence": <0.0-1.0>, "reason": "<short reason>"}
Output only the JSON array, nothing else."""


def _build_verifier_batch(candidates: list[Candidate]) -> str:
    items = []
    for i, c in enumerate(candidates):
        items.append({
            "id": i,
            "type": c.pii_type,
            "line": c.value if c.pii_type != "password" else "[REDACTED]",
            "context": c.context,
        })
    return json.dumps(items, indent=2)


def verify_with_llm(candidates: list[Candidate], model: str = LLM_MODEL) -> Optional[dict]:
    """Mutates candidates in place, filling in `llm_verdict`. Only called on
    candidates whose pii_type is in LLM_VERIFIED_TYPES; batches all
    candidates from one call together to amortize request overhead. Returns
    usage/cost stats for the report, or None if there was nothing to verify."""
    targets = [c for c in candidates if c.pii_type in LLM_VERIFIED_TYPES]
    if not targets:
        return None

    from google import genai  # deferred import: only required when --verify-llm is used
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    batch_payload = _build_verifier_batch(targets)

    response = client.models.generate_content(
        model=model,
        contents=batch_payload,
        config=types.GenerateContentConfig(
            system_instruction=_VERIFIER_SYSTEM,
            temperature=CONFIG.llm.temperature,
            response_mime_type="application/json",
        ),
    )

    text = response.text or "[]"
    try:
        verdicts = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]") + 1
        verdicts = json.loads(text[start:end])

    for verdict in verdicts:
        idx = verdict.get("id")
        if idx is not None and 0 <= idx < len(targets):
            targets[idx].llm_verdict = verdict

    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count or 0
    output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    cost = (
        input_tokens * GEMINI_INPUT_USD_PER_M_TOKENS
        + output_tokens * GEMINI_OUTPUT_USD_PER_M_TOKENS
    ) / 1_000_000
    print(
        f"[llm] model={model} input_tokens={input_tokens} "
        f"output_tokens={output_tokens} cost=${cost:.5f} "
        f"candidates_verified={len(targets)}",
        file=sys.stderr,
    )

    verdict_true = sum(1 for c in targets if c.llm_verdict and c.llm_verdict.get("is_real_pii"))
    verdict_false = sum(1 for c in targets if c.llm_verdict and not c.llm_verdict.get("is_real_pii"))
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "candidates_verified": len(targets),
        "verdict_true": verdict_true,
        "verdict_false": verdict_false,
    }


# ---------------------------------------------------------------------------
# CLI — runs the detector over a local directory of source files (the
# data/5 starter set). Output is a JSONL of candidates for evaluation.
# ---------------------------------------------------------------------------


def scan_directory(directory: Path, extensions: tuple[str, ...] = tuple(CONFIG.detection.extensions)) -> Iterable[tuple[Path, list[Candidate]]]:
    for path in sorted(directory.rglob("*")):
        if path.suffix not in extensions or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        yield path, detect_candidates(text)


def build_report(
    scan_dir: Path,
    files_scanned: int,
    all_candidates: list[tuple[Path, Candidate]],
    llm_stats: Optional[dict],
    max_examples_per_type: int,
) -> str:
    """Human-readable run summary. Never includes a raw candidate value —
    only the type, location, detector rule, and pre-redacted context, same
    redaction contract as candidates.jsonl."""
    flagged_files = sorted({path.name for path, _ in all_candidates})
    by_type: dict[str, list[tuple[Path, Candidate]]] = {}
    for path, c in all_candidates:
        by_type.setdefault(c.pii_type, []).append((path, c))
    by_method = Counter(c.method for _, c in all_candidates)

    lines: list[str] = []
    lines.append("# PII Detection Report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- Scanned directory: `{scan_dir}`")
    lines.append(f"- Files scanned: {files_scanned}")
    lines.append(f"- Files flagged: {len(flagged_files)}")
    lines.append(f"- Total candidates: {len(all_candidates)}")
    lines.append("")

    lines.append("## Candidates by type")
    lines.append("")
    lines.append("| Type | Count | Files |")
    lines.append("| --- | --- | --- |")
    for pii_type, items in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        n_files = len({path.name for path, _ in items})
        lines.append(f"| {pii_type} | {len(items)} | {n_files} |")
    lines.append("")

    lines.append("## Candidates by detector rule")
    lines.append("")
    lines.append("| Method | Count |")
    lines.append("| --- | --- |")
    for method, count in by_method.most_common():
        lines.append(f"| {method} | {count} |")
    lines.append("")

    if llm_stats is not None:
        lines.append("## LLM verification")
        lines.append("")
        lines.append(f"- Model: `{llm_stats['model']}`")
        lines.append(f"- Candidates verified: {llm_stats['candidates_verified']}")
        lines.append(
            f"- Tokens: {llm_stats['input_tokens']} in / {llm_stats['output_tokens']} out"
        )
        lines.append(f"- Cost: ${llm_stats['cost_usd']:.5f} total, "
                      f"${llm_stats['cost_usd'] / max(llm_stats['candidates_verified'], 1):.5f} per verified candidate")
        lines.append(
            f"- Verdicts: {llm_stats['verdict_true']} is_real_pii=true, "
            f"{llm_stats['verdict_false']} is_real_pii=false"
        )
        lines.append("")

    lines.append("## Flagged examples")
    lines.append(
        f"(up to {max_examples_per_type} per type; context is redacted, "
        "matched values are never printed here)"
    )
    lines.append("")
    for pii_type, items in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"### {pii_type} ({len(items)} candidates)")
        lines.append("")
        for path, c in items[:max_examples_per_type]:
            verdict = ""
            if c.llm_verdict is not None:
                verdict = (
                    f", llm_verdict={c.llm_verdict.get('is_real_pii')}"
                    f" (confidence={c.llm_verdict.get('confidence')})"
                )
            lines.append(f"- `{path.name}` line {c.line_no} — `{c.method}`{verdict}")
        if len(items) > max_examples_per_type:
            lines.append(f"- ... and {len(items) - max_examples_per_type} more")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="Directory of source files to scan")
    parser.add_argument("--out", type=Path, required=True, help="Output JSONL path")
    parser.add_argument(
        "--verify-llm",
        action="store_true",
        default=CONFIG.llm.verify_by_default,
        help="Run the LLM verifier pass on name/username/email candidates",
    )
    parser.add_argument("--llm-model", default=LLM_MODEL)
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=CONFIG.detection.extensions,
        help="File extensions to scan, e.g. --extensions .java .kt",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path for the human-readable run report (default: <out>.report.md)",
    )
    parser.add_argument(
        "--report-max-examples",
        type=int,
        default=CONFIG.report.max_examples_per_type,
        help="Max example candidates listed per type in the report",
    )
    args = parser.parse_args()

    scanned_paths = list(scan_directory(args.dir, tuple(args.extensions)))
    files_scanned = len(scanned_paths)

    all_candidates: list[tuple[Path, Candidate]] = []
    for path, cands in scanned_paths:
        for c in cands:
            all_candidates.append((path, c))

    llm_stats = None
    if args.verify_llm:
        llm_stats = verify_with_llm([c for _, c in all_candidates], model=args.llm_model)

    with args.out.open("w", encoding="utf-8") as f:
        for path, c in all_candidates:
            record = {
                "file": path.name,
                "pii_type": c.pii_type,
                "line_span": [c.line_no, c.line_no],
                "method": c.method,
                "signal": c.signal,
                "context_redacted": c.context,
                "llm_verdict": c.llm_verdict,
            }
            f.write(json.dumps(record) + "\n")

    print(f"Wrote {len(all_candidates)} candidates to {args.out}", file=sys.stderr)

    report_path = args.report or args.out.with_suffix(".report.md")
    report_text = build_report(
        args.dir, files_scanned, all_candidates, llm_stats, args.report_max_examples
    )
    report_path.write_text(report_text, encoding="utf-8")
    print(f"Wrote report to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
