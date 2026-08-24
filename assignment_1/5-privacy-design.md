# PII / Privacy Detection — Design Notes for `pii_detect.py`

Companion notes to [5-privacy.md](5-privacy.md), written to capture the design
decisions behind [src/pii_detect.py](src/pii_detect.py) so they can be pulled
into the final report (Sections 1–4) without having to re-derive them from the
code. This file is documentation, not a deliverable — the graded report should
be its own (≤3 page) document.

## 1. What counts as a problematic instance

`5-privacy.md` pins down the definition already; the detector operationalizes
it type by type:

| Type | Problematic instance | Not problematic |
| --- | --- | --- |
| `email` | An email address that identifies a real person | `user@example.com`, `test@test.com`, role/no-reply addresses |
| `name` | A person's full name, written where authorship is being claimed | A class/product/company name that happens to be two capitalized words |
| `username` | A personal account handle that names a person without being their full name | Generic role accounts (`admin`, `root`), placeholder handles |
| `password` | A password literal written into source | `changeme`, `password123`, short dictionary words |
| `key` | A provider-issued credential (API key, app key, access/bearer token) | N/A — any matched provider-shaped key is treated as real |
| `ip_address` | Any hard-coded IPv4 address, **including private ranges** | Loopback (`127.0.0.1`), unspecified (`0.0.0.0`), multicast, wildcard (`255.255.255.255`) |

Two design choices follow directly from the task's scoping rules and matter
for how the detector is built:

- **Scope is textual, not structural.** A scraper ingests comments,
  Javadoc, and commented-out code exactly like live code, so the detector
  runs on raw line text and does not special-case or skip comment blocks.
- **`name` and `username` are disambiguated by the shape of the identifier
  itself, not by where it appears.** Both are searched for in the same
  authorship-marker context (`@author`, "written by", "created by",
  "author:"); which bucket a hit lands in depends on whether it looks like
  `Firstname Lastname` (→ `name`) or a single handle-shaped token (→
  `username`), never on which line/field it was found in.

## 2. Detection method — design decisions

### 2.1 Pipeline

Three stages, each one only narrowing what the previous stage produced:

1. **Regex/heuristic candidate generation** (per type, high recall by design).
2. **Placeholder/denylist filtering + entropy scoring** (precision boost,
   purely local — no network call).
3. **Optional LLM verification** (Claude Haiku 4.5), for `name`, `username`,
   and `email` only — the three types where a regex match is syntactically
   plausible but semantically ambiguous (a class name matches the same
   `Capitalized Capitalized` shape as a person's name).

`password`, `key`, and `ip_address` never reach the LLM stage. This was a
deliberate boundary, not an oversight: these three are the types where the
matched *value itself* is the sensitive artifact (a working secret or an
internal address), so the design avoids ever sending them to a third-party
API — even for an evaluation harness working on synthetic data, the habit is
the point (see the "handle it like it's live" instruction in
`5-privacy.md`). Whether something is a real password/key/IP is also
answerable from local shape/entropy/RFC-1918 membership alone, so an LLM call
wouldn't add information for those three types anyway.

### 2.2 Per-type detectors

- **`email`** — standard RFC-ish regex, then dropped if the local-part or
  domain is in a hand-curated placeholder table (`example.com`,
  `noreply@...`, `user@...`, etc.).
- **`ip_address`** — IPv4 regex, then classified with Python's `ipaddress`
  module: loopback/unspecified/multicast and the `0.0.0.0` /
  `255.255.255.255` wildcards are dropped; private ranges (RFC 1918) are
  **kept**, per the task's explicit scoping rule that private addresses still
  count. `signal.is_private` records which bucket it fell in for later
  auditing.
- **`key`** — two tiers: (a) provider-specific formats with near-zero false
  positive rate (`AKIA[0-9A-Z]{16}` for AWS, `AIza...` for Google,
  `gh[pousr]_...` for GitHub, `xox[baprs]-...` for Slack) matched
  unconditionally; (b) a generic `api_key = "..."` / `access_token: "..."`
  assignment pattern, gated by `looks_like_secret` (≥8 chars, mixed
  digits+letters, Shannon entropy ≥ 3.3) so it doesn't fire on
  `api_key = "changeme"`.
- **`password`** — assignment pattern (`password = "..."`) and a JDBC
  connection-string pattern (`...password=...`), both gated by the same
  entropy/shape check as keys, and both excluded if the value is in the
  placeholder-secrets denylist (`changeme`, `123456`, `admin`, ...).
- **`username`** — two sources: (a) an explicit `username =` / `login =` /
  `handle =` assignment; (b) inside an authorship-marker line, a bare
  handle-shaped token that contains at least one digit (`mkolvane81`-style).
  The digit requirement is what keeps this from colliding with the `name`
  detector on the same line — an ordinary capitalized word never has a
  digit in it, so the two detectors partition the same author-context line
  by construction rather than by an explicit priority rule.
- **`name`** — restricted to lines that match the authorship-marker regex
  first, and only then scanned for the `Capitalized Capitalized` shape. This
  is the single biggest precision lever in the whole detector: without the
  authorship-context gate, a two-capitalized-word regex fires constantly on
  class names, license boilerplate, and phrases like "Software Foundation"
  or "Open Source" (also denylisted via `NAME_STOPWORDS` as a second line of
  defense). The trade-off is explicit: **this detector cannot find a name
  anywhere except next to an authorship claim.**

### 2.3 Why entropy + denylist instead of just denylist (or just entropy)

A denylist alone can't reject secrets it hasn't seen before; entropy alone
can't reject a short, low-entropy real password recorded verbatim (`admin`)
or accept a long but low-entropy real token. Combining them — denylist first
for known filler, then a shape/entropy floor for anything else — was chosen
to cheaply reject the tutorial-boilerplate case that dominates real corpora
without needing a trained classifier.

### 2.4 LLM verification stage (implemented, ultimately not needed)

- **Model:** `claude-haiku-4-5`.
- **Prompt:** a fixed system prompt (`_VERIFIER_SYSTEM` in the script)
  instructing the model to label each candidate `is_real_pii` (true/false)
  with a confidence and short reason, distinguishing a real person's
  name/handle/email from a placeholder, a role/bot account, or a non-person
  identifier that matches the pattern by coincidence.
- **Batching:** all `name`/`username`/`email` candidates from a run are sent
  in a single request as a JSON array (one item per candidate, with
  redacted context), and the model is asked to return a same-length JSON
  array of verdicts — this amortizes request overhead instead of one call
  per candidate.
- **Decision conversion:** each returned `{"id", "is_real_pii", "confidence",
  "reason"}` object is attached back to its `Candidate.llm_verdict` field by
  index; nothing currently *drops* a candidate based on the verdict — it's
  additive evidence for manual review, not an automatic filter. Wiring the
  verdict into a hard accept/reject threshold is a natural next step if the
  method is applied somewhere the local heuristics alone aren't precise
  enough.
- **Cost:** the script prints `input_tokens`, `output_tokens`, and a dollar
  estimate per run (`$1.00`/M input, `$5.00`/M output tokens, hard-coded in
  `verify_with_llm`) — that rate should be double-checked against current
  published Haiku 4.5 pricing before it goes in the report, since it's a
  constant baked into the script rather than looked up at run time.
- **Outcome on `data/5`:** not invoked for the result reported below.
  Running with `--verify-llm` would call the API only for the `email`
  candidates and the single `name`/`username` candidate each (see §3) — on
  the order of a few cents total — but the heuristic-only pass already
  reproduced the intended 6-file/6-type structure, so the LLM pass added no
  additional signal on this dataset. This is worth stating plainly in the
  report rather than treating it as a weakness: the assignment rewards a
  correctly evaluated simple method over an unnecessarily complex one, and
  here the complex stage turned out to be unnecessary for the specific,
  narrow definition of "problematic" that `5-privacy.md` uses. It should not
  be read as evidence the LLM stage is useless in general — see §4.

## 3. Evaluation on `data/5`

### 3.1 Setup

`data/5` has 206 `.java` files, exactly 6 of which contain PII (one per
type, no file with two types — an invariant stated in `5-privacy.md`). Ran:

```
python src/pii_detect.py --dir data/5 --out candidates.jsonl
```

(no `--verify-llm`).

### 3.2 Results

The heuristic-only pass produced **8 line-level candidates**, collapsing to
**exactly 6 distinct files**, and the 6 types are the 6 required types with
no repeats:

| File | Type | Detector rule |
| --- | --- | --- |
| `ArticlesController.java` | `username` | `username:author_context_handle` |
| `DataFileListTest.java` | `email` (2 lines) | `regex:email` |
| `DB.java` | `password` | `password:jdbc_url` |
| `LocalGenerateModelLoader.java` | `name` | `name:author_context` |
| `MultiplierBolt.java` | `ip_address` (2 lines) | `regex:ipv4`, private-range |
| `UboxHttp.java` | `key` | `key:generic_assign` |

Zero other files across the remaining 200 produced any candidate.

Treating the task at the file-level granularity the submission format asks
for (`5-privacy.csv`: one file→type row per required type), this is
**precision = 6/6 = 100%, recall = 6/6 = 100%, F1 = 100%**, with 0 false
positives among 206 files and 0 false negatives among the 6 required types.
The two files with two line-level hits (`DataFileListTest.java`,
`MultiplierBolt.java`) are not double counted as errors — they're the same
value appearing on two lines of one positive file, which the file-level
grading granularity treats as a single correct row.

*Caveat:* this repo does not contain an official answer key, so "100%" here
means the flagged set exactly matches the dataset's known structural
invariants (6 files, all 6 types present, no type repeated, no file with two
types) — which is strong circumstantial evidence of correctness, not an
independently verified ground-truth comparison. Say so plainly in the report
rather than asserting confirmed accuracy.

### 3.3 Why zero false positives

The three precision levers doing the actual work, in order of impact:

1. **Author-context gating for `name`** — by far the biggest lever; without
   it the `Capitalized Capitalized` regex would fire on nearly every file.
2. **Entropy/shape gate for `password`/`key`** — rejects the common
   tutorial-boilerplate secrets (`password=123456`, `key="changeme"`)
   without needing a denylist entry for every possible filler value.
3. **Domain/local-part and IP-range denylists** — reject the specific
   placeholder conventions (`example.com`, `127.0.0.1`, `0.0.0.0`) that
   otherwise look exactly like the real thing to a pure regex.

## 4. Limitations — what this method would miss

- **`name` is only found next to an explicit authorship marker.** A name
  written elsewhere (a contact field, a commit-message-style comment, a
  string literal) is invisible to this detector by construction. This is the
  single largest coverage gap.
- **`username` requires a digit in the handle.** A purely alphabetic handle
  next to an `@author` tag (`@author jsmith`) is missed, because the digit
  requirement is what currently keeps the `name` and `username` detectors
  from colliding on the same line.
- **Secrets are only caught in `key = "..."` / `password = "..."` /
  JDBC-URL shapes.** A secret embedded as a bare string literal, split
  across a concatenation, base64-encoded, or loaded from a YAML/properties
  block with different syntax would not match any current regex.
- **IPv4 only** — no IPv6 pattern exists yet.
- **English-centric, hand-curated denylists.** Placeholder tables for
  domains/local-parts/names/secrets were built by inspection of the
  provided data, not derived systematically; they will under-generalize to
  corpora with different conventions (non-English tutorials, different
  placeholder idioms).
- **No cross-line context.** Each line is scored independently, so a
  key/password split across a multi-line string, or a name given on one
  line and referenced by initials on the next, is not reconstructed.
- **100% on 206 curated files is not evidence of 100% on Stack v2 at
  scale.** This dataset was hand-built so that exactly 6 files are positive
  and the rest are (presumably) genuinely clean or at least not built to
  contain adversarial near-misses. A larger, unfiltered sample will surface
  patterns (test fixtures full of fake-but-plausible emails, seeded RNG
  values that pass the entropy check, forked repos with the same author
  block copy-pasted thousands of times) that this method has not yet been
  stress-tested against.

## 5. Implications for building trustworthy corpora

The cheap, local, no-API stages here are enough to clear the *obvious* cases
(known key formats, JDBC passwords, denylistable placeholders) essentially
for free, at corpus scale. What they can't do — telling a real person's name
or handle apart from a same-shaped non-person identifier — is exactly the
ambiguous middle where an LLM-verification pass (§2.4) is designed to add
value, even though it wasn't the deciding factor on this particular 206-file
sample. That split (cheap deterministic filtering for the unambiguous
majority, a semantic pass reserved for the genuinely ambiguous minority) is
a reasonable template for scaling PII screening across a corpus the size of
Stack v2, where running an LLM over every file is not viable but running it
over the small fraction that survives the first filter is.

## 6. Open items before this becomes the graded report

- [ ] Apply the method to a sampled subset of the actual Stack v2 (§5 of the
      assignment) — not yet done; everything above is `data/5` only.
- [ ] Produce `candidates.jsonl` in the assignment's required schema
      (`blob_id`, `src_encoding`, `repo_name`, `path`, revision/snapshot/
      directory id, `line_span`, `flag_reason`) — the current script's
      output schema is close but not identical (it has `file`/`method`/
      `signal` instead of the required Stack v2 provenance fields).
- [ ] Write `README.md` (how to run, dependencies, how instances were
      obtained).
- [ ] Verify the hard-coded Haiku 4.5 per-token cost rate in
      `verify_with_llm` against current published pricing before quoting it
      in the report.
- [ ] Decide whether to keep the LLM stage in the final pipeline at all,
      given §3 shows it wasn't needed for the provided dataset — if kept,
      it should be justified for the Stack v2 stage (§5), not for `data/5`.
