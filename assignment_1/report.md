# Data Quality Issues in Code Corpora: Personally Identifiable Information

**Assignment 1 — CSC 591/791 Trustworthy AI for Software Engineering**

---

## 1. Data-Quality Issue

**Issue investigated.** Personally identifiable information (PII) committed into
source files and swept into a training corpus by an automated scraper: email
addresses, full names, account handles, passwords, provider-issued credentials,
and hard-coded IP addresses.

**Why it is a data-quality problem.** Code corpora such as The Stack v2 are
built by mirroring public repositories wholesale; nothing in that pipeline
distinguishes a developer's intentional public artifact from an accidental
personal disclosure (an author's name in a Javadoc header, a test credential
left in a connection string, a personal email pasted into a bug-report
comment). Once such text enters pretraining data, two distinct harms follow.
First, a privacy harm: models trained on memorized personal data can be made
to regurgitate it verbatim, and recent work shows this is not merely
theoretical — Yang et al. (arXiv:2512.07814) trace, via training dynamics,
how specific PII instances in code corpora become extractable from trained
models. Second, a corpus-quality harm independent of privacy: hard-coded
secrets and personal identifiers are exactly the kind of one-off, non-general
text a code model should not be learning to reproduce as "normal" code
structure.

**Definition of a problematic instance.** A candidate is problematic only if
the flagged value is a *real* identifier, not a placeholder or role account.
This distinction is the entire difficulty of the task — regex easily finds
the *shape* of an email or a name; nothing local tells you whether it names a
real person.

| Type | Problematic | Not problematic |
| --- | --- | --- |
| `email` | Identifies a real person | `user@example.com`, `noreply@...`, role addresses |
| `name` | A person's full name, at an authorship claim | A class/product name that happens to be two capitalized words |
| `username` | A personal handle that names a person without being their full name | `admin`, `root`, placeholder handles |
| `password` | A password literal in source | `changeme`, `password123`, dictionary words |
| `key` | A provider-issued credential | N/A — any matched provider-shaped key is treated as real |
| `ip_address` | Any hard-coded IPv4, **including private ranges** | Loopback, unspecified, multicast, wildcard addresses |

Two scoping decisions matter for how the detector is built. First, scope is
**textual, not structural**: a scraper ingests comments and commented-out
code exactly like live code, so the detector runs on raw line text without
special-casing comment blocks. Second, `name` and `username` are told apart
by **the shape of the identifier itself**, not by where it sits — both are
searched for in the same authorship-marker context (`@author`, "created by",
"written by"), and which bucket a hit lands in depends on whether it looks
like `Firstname Lastname` or a single handle-shaped token.

---

## 2. Detection Method

The detector (`src/pii_detect.py`) is a three-stage pipeline, each stage only
narrowing what the previous stage produced:

1. **Regex/heuristic candidate generation**, one detector per type, tuned for
   high recall.
2. **Placeholder-denylist + entropy filtering**, purely local (no network
   call), tuned for precision.
3. **Optional LLM verification**, for `name`/`username`/`email` only.

| Type | Detector logic |
| --- | --- |
| `email` | RFC-ish regex; dropped if local-part or domain is in a hand-curated placeholder table |
| `ip_address` | IPv4 regex, classified via Python's `ipaddress`; loopback/unspecified/multicast/wildcard dropped, **private (RFC 1918) ranges kept** per the task's scoping rule |
| `key` | Tier 1: provider-specific formats (AWS `AKIA...`, Google `AIza...`, GitHub `gh[pousr]_...`, Slack `xox[baprs]-...`) matched unconditionally. Tier 2: generic `api_key = "..."` assignment, gated by a Shannon-entropy/shape check |
| `password` | `password = "..."` assignment and JDBC connection-string `password=...`, both gated by the same entropy/shape check and a placeholder-secret denylist |
| `username` | Explicit `username =`/`login =`/`handle =` assignment, **or** a digit-containing handle token inside an authorship-marker line. The digit requirement is what keeps this from colliding with `name` on the same line |
| `name` | Restricted to authorship-marker lines, then scanned for a `Capitalized Capitalized` shape; denylisted against common non-name phrases (`Software Foundation`, `Open Source`) |

**Why entropy + denylist, not just one.** A denylist alone cannot reject
secrets it has never seen; entropy alone cannot reject a short, low-entropy
*real* password (`admin`) or accept a long, low-entropy real token. The two
combined — denylist first for known filler, then a shape/entropy floor for
everything else — cheaply rejects the tutorial-boilerplate case that
dominates real corpora, without a trained classifier.

**Why `password`/`key`/`ip_address` never reach the LLM.** For these three
types the matched *value itself* is the sensitive artifact — a working
secret or an internal address. The design deliberately never sends them to a
third-party API, on the principle stated in the assignment's safety notes
("handle it like it's live"). It is also unnecessary: whether something is a
real password/key/private-range IP is answerable from local shape, entropy,
and RFC-1918 membership alone.

**LLM verification stage.**
- **Model:** `gemini-3.5-flash-lite`, via the `google-genai` SDK, called with
  `temperature=0` and `response_mime_type="application/json"`.
- **Prompt (fixed system prompt):** instructs the model to label each
  candidate `is_real_pii` (true/false) with a confidence and short reason,
  distinguishing a real person's name/handle/email from a placeholder, a
  role/bot account, or a non-person identifier that matches the pattern by
  coincidence.
- **Batching:** all `name`/`username`/`email` candidates from one run are
  sent as a single JSON array (including the actual matched value, since the
  model needs the real string to judge it) and returned as a same-length
  array of verdicts.
- **Decision conversion:** each verdict is attached back to the candidate's
  `llm_verdict` field by index. It is currently **additive evidence**, not an
  automatic filter — nothing is dropped from `candidates.jsonl` based on the
  verdict.
- **Cost:** `$0.30`/M input tokens, `$2.50`/M output tokens (Google's
  published rate for this model, verified live against
  `ai.google.dev/gemini-api/docs/pricing`). Output-token accounting includes
  extended-thinking tokens, which are billed as output.

---

## 3. Evaluation and Findings

### 3.1 `data/5` (206 Java files, 6 known positives, one per type)

Ran the heuristic-only pass (no `--verify-llm`). Result: **8 line-level
candidates, collapsing to exactly 6 distinct files**, and the 6 types are the
6 required types with no repeats — zero other files across the remaining 200
produced any candidate.

| File | Type | Detector rule |
| --- | --- | --- |
| `ArticlesController.java` | `username` | `username:author_context_handle` |
| `DataFileListTest.java` | `email` (2 lines, same value) | `regex:email` |
| `DB.java` | `password` | `password:jdbc_url` |
| `LocalGenerateModelLoader.java` | `name` | `name:author_context` |
| `MultiplierBolt.java` | `ip_address` (2 lines, same value) | `regex:ipv4`, private-range |
| `UboxHttp.java` | `key` | `key:generic_assign` |

At the file-level granularity the submission format grades on, this is
**precision = recall = F1 = 100%** (0 false positives among 206 files, 0
false negatives among the 6 required types). *Caveat:* the repository
contains no independent answer key; "100%" here means the flagged set
exactly matches the dataset's stated structural invariants (6 files, all 6
types, no repeats), which is strong circumstantial evidence of correctness
but not an independently verified ground-truth comparison.

The three precision levers doing the actual work, ranked by impact: (1)
author-context gating for `name` — without it the two-capitalized-word regex
fires on nearly every file; (2) entropy/shape gating for `password`/`key` —
rejects tutorial-boilerplate secrets without a denylist entry for every
possible filler value; (3) domain/local-part and IP-range denylists — reject
placeholder conventions that otherwise look exactly like the real thing to a
pure regex.

### 3.2 Application to The Stack v2

**Sampling.** 3,000 `.java` files streamed from `bigcode/the-stack-v2-dedup`
(the near-dedup split, chosen to blunt the fork/copy-paste duplication
problem noted below), shuffled with a fixed seed (42) for reproducibility.
Filtered out generated/vendored files and files outside a 200 B–200 KB size
range; capped at 3 files per `repo_name` so one popular or heavily forked
repository could not dominate the sample — the cap barely engaged (2,979
unique repos across 3,000 files). Provenance for every sampled file
(`blob_id`, `src_encoding`, `repo_name`, `path`, revision/snapshot/
directory_id) was recorded to a manifest for later traceability. An initial
1,000-file pass found `name`/`email`/`username`/`ip_address` candidates but
zero `password` or `key`; the sample was extended to 3,000 files (same
seed, same filters — the larger sample's first 1,000 files are identical to
the original pass) specifically to get representation from all six types.

**Run.** The full pipeline (heuristics + `--verify-llm`) was applied to the
3,000-file sample.

| Metric | Value |
| --- | --- |
| Files scanned | 3,000 |
| Files flagged | 256 |
| Total candidates | 342 |
| Candidates by type | `name` 175, `email` 101, `username` 36, `ip_address` 28, `password` 1, `key` 1 |
| LLM candidates verified | 312 |
| LLM cost | $0.04587 total ($0.00015/candidate) |
| LLM verdicts | 272 `is_real_pii=true`, 40 `is_real_pii=false` |

At 3,000 files, one instance each of `password` and `key` appeared — a
`PWD = "..."` field assignment and a `DEVELOPER_KEY = "..."` Google API key
assignment, both caught by the same detector rules validated on `data/5`.
Their scarcity here (2 hits in 3,000 files vs. 2 hits in 206 curated files)
is itself informative: `data/5` was deliberately constructed to contain one
of each type, so it overstates how often `password`/`key` literals appear
in unfiltered real code relative to `name`/`email`, which concentrate
naturally in author-credit boilerplate and contact-info comments.

**Representative success case.** `00007_8d38afc7a12d.java`, line 3: a
`Written by:` authorship comment matched the `name` detector twice (two
names in the same credit line); the LLM verifier independently confirmed
both as real personal names at 0.9 confidence, agreeing with the heuristic
label. This is the intended common case — author-credit boilerplate is
exactly where personal names concentrate in scraped code.

**Representative failure case (heuristic/LLM disagreement).**
`00033_4ed153e4d904.java`, line 49: the `username:assign` detector fired on
a string-concatenation expression building a log/request message
(`"Username =" + user + ...`), a case the regex cannot distinguish from a
genuine `username = "value"` assignment. The LLM verifier correctly
overrode it (`is_real_pii=false`, "generic code variable placeholder
expression, not a real username," confidence 0.95). The same file's line 78
shows the mirror case for `email`: a `setFrom(...)` call to a support
address, which the LLM correctly flagged false at 0.9 confidence. Both cases
argue for the LLM stage's value at corpus scale, in contrast to `data/5`
where it changed nothing (§3.1 — that dataset's positives were unambiguous
by construction).

---

## 4. Limitations and Implications

**What the method misses.** `name` is found only adjacent to an explicit
authorship marker — a name in a contact field, a commit-message-style
comment, or a bare string literal is invisible by construction. `username`
requires a digit in the handle, so a purely alphabetic handle next to
`@author` is missed (the digit requirement is what keeps `name` and
`username` from colliding on the same line). Secrets are caught only in
`key = "..."`/`password = "..."`/JDBC-URL shapes — a secret split across a
concatenation, base64-encoded, or in a YAML/properties block is not
detected. Only IPv4 is covered. Placeholder denylists were built by
inspecting the provided data, not derived systematically, and will
under-generalize to corpora with different conventions. Each line is scored
independently, so no cross-line reconstruction is attempted.

**LLM reliability observation.** On one `username` candidate in the `data/5`
evaluation, the verifier's free-text `reason` asserted the handle
"corresponds to" a specific full person's name that appears nowhere in the
candidate's value or surrounding context — a fabricated attribution rather
than a grounded observation. The boolean verdict was still correct, but the
justification was not. This is worth stating plainly: an LLM verifier's
*verdict* and its *stated reasoning* can be reliable and unreliable
independently, so `llm_verdict.reason` should be treated as color for manual
review, never as a citable claim.

**Confidence in detected instances.** High for the unambiguous majority
(provider-shaped keys, JDBC passwords, `@author Firstname Lastname` lines) —
these are essentially unambiguous by shape or by provider-format uniqueness.
Lower for the LLM-arbitrated minority, where the model's judgment is
plausible but not independently verified against ground truth in this
project; the two disagreement cases in §3.2 show the LLM correcting the
heuristic in the intended direction, but a systematic audit against
human-labeled Stack v2 data was out of scope here.

**Implications for trustworthy corpora.** The cheap, local, no-API stages
here clear the *obvious* cases — known key formats, JDBC passwords,
denylistable placeholders — essentially for free, at corpus scale. What they
cannot do — telling a real person's name or handle apart from a
same-shaped non-person identifier — is exactly the ambiguous middle an LLM
pass is suited to, at a cost cheap enough to apply broadly ($0.00015 per
verified candidate here). The general template this suggests for building
cleaner training corpora: cheap deterministic filtering for the unambiguous
majority, a selective semantic pass reserved for the genuinely ambiguous
minority that survives the first filter — never running an LLM over every
file, but running it over the small fraction that needs judgment.

---

## Draft additions (for the two gaps flagged in the PDF review — pull into place, then delete this section)

### For §2.3 (LLM Verification) — one sentence on what the prompt asks

Drop this in wherever the model name/temperature/cost currently sit, before or
after the decision-conversion sentence:

> The system prompt instructs the model to label each candidate
> `is_real_pii` (true/false) with a confidence and short reason,
> distinguishing a real person's name, handle, or email from a placeholder,
> a role/bot account, or a non-person identifier that merely matches the
> regex shape by coincidence.

### For §3.2 (Application to The Stack v2) — manual-inspection count

Numbers, computed just now directly from `stackv2_candidates.jsonl`:

- **50 of the 342 candidates were manually inspected** (the first 50 in
  detection order — not cherry-picked), reading each one's redacted context
  and, where present, its LLM verdict.
- Of those 50: **49 had an LLM verdict** (40 `is_real_pii=true`, 9 `false`)
  and **manual reading agreed with the LLM's verdict in all 49/49 cases** —
  including the 9 cases where the LLM overrode a heuristic-stage false
  positive (a `username:assign` regex firing inside a log-message string
  concatenation, twice; a `setFrom()` system/rejection-notice address; and
  five near-identical `email` hits inside one Javadoc block that was really
  REST-API usage documentation, not a personal disclosure).
- The remaining **1 of the 50 had no LLM verdict** — an `ip_address`
  candidate (`00192_d1f3b7d9da9a.java` line 212), which bypasses the LLM
  stage by design (see §2, password/key/ip_address are never sent to the
  LLM). Manual inspection found it to be a false positive the pipeline
  currently has no way to catch: a JD-Core decompiler version banner
  (`JD-Core Version: 0.7.0.1`) whose four-part dotted format happens to
  match valid IPv4 shape. Worth stating directly: this is the one type
  with zero semantic disambiguation, by design, and this is a concrete
  instance of that trade-off actually firing.

Suggested one-line summary if space is tight: "50 of the 342 candidates
were manually inspected; manual judgment agreed with the LLM verdict in
49/49 cases with a verdict, and surfaced one additional false positive
(an `ip_address` match on a decompiler version string) in the one type the
LLM never sees."

A secondary, code-level finding from this same manual pass (optional, cut
if space doesn't allow): three redaction bugs were found and fixed in
`pii_detect.py` during the review — none changed detection counts or the
`data/5` 100% baseline, but each was closing a real leak in the
human-readable context field itself (a partial name match leaving a
trailing surname/hyphenated-surname fragment unredacted, and a non-Latin
transliteration of an already-redacted name left exposed). Worth a
one-clause mention in Limitations as evidence that manual review at the
"read the actual outputs" level catches classes of error that aggregate
precision/recall on `data/5` cannot.
