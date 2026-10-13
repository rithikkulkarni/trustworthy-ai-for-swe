# Assignment 3 Roadmap — Does Quantization Make Code LLMs Brittle?

Notebook: [A3_rrkulka3.ipynb](A3_rrkulka3.ipynb) · Individual work · Runs on a Colab **T4 GPU**

## The question

Quantization papers report clean pass@1 and call 4-bit "near-lossless" when it barely moves.
**When the clean score holds, does robustness hold too?** There is no answer key. A well-supported
"no significant change" earns full credit. Grading is on protocol, reproducibility, and claims matching evidence.

## What is fixed (do not change)

- Model: `Qwen/Qwen2.5-Coder-1.5B-Instruct`
- Decoding: greedy, `max_new_tokens=512`, no repetition penalty
- Prompt template (except inside E3) and the ReCode subset (2 transformations per family, seed 0)
- **Never** use HumanEval or any ReCode file as GPTQ calibration data (test-set leakage)

## Grading map

| Part | Work | Pts |
|---|---|---|
| 1 | Load `fp16`, `int8`, `nf4`; run GPTQ yourself for `gptq4` | 20 |
| 2 | E0 clean baseline, 4 configs | 10 |
| 3 | E1 ReCode robustness, 4 perturbation families | 25 |
| 4 | E2 **or** E3 (both = bonus) | 15 |
| 5 | Paired statistics and uncertainty | 10 |
| 6 | Report | 15 |
| – | Submission: notebook with outputs + `README.md` | 5 |
| bonus | Both E2 and E3, or a fifth config (e.g. AWQ) | +5 |

## TODOs in the notebook

| # | Function(s) | What it must do |
|---|---|---|
| 1a | `load_model(config)` | fp16; int8 via `BitsAndBytesConfig(load_in_8bit)`; nf4 via 4-bit NF4 with fp16 compute; gptq4 loads the checkpoint from `GPTQ_DIR` |
| 1b | `build_calibration_set`, `run_gptq`, `CALIB_DATASET` | Pick and justify a calibration set, tokenize it, load the model in **float32**, run `oneshot` with `GPTQModifier` (scheme `W4A16`, `lm_head` ignored), `save_compressed=True`, save tokenizer too |
| 3 | `recode_metrics`, `family_worst_case` | Robust Pass@1, Robust Drop@1, Robust Relative@1, **conditional robustness**; per-family worst case (pass every variant) |
| 4a | `run_evaloop`, `asl` | EVALOOOP loop: code → docstring description → code, up to 3 loops; ASL = mean consecutive loops survived |
| 4b | `record_e3` | pass@1 per template, spread (max − min), count of template-sensitive problems |
| 5 | `bootstrap_ci`, `paired_compare` | 95% percentile bootstrap (10k resamples, fixed seed); discordant counts, diff, exact McNemar p-value, paired bootstrap CI |
| 6 | Report cells 9.1–9.5 | See below |

## Suggested order of work

### Phase 0 — Setup (Colab)
- [ ] Upload the notebook, switch to a T4 runtime, run the install cell. **Restart the session if `torch` changed.**
- [ ] Keep `QUICK = True` (first 20 problems) until everything runs end to end.

### Phase 1 — The easy, self-contained pieces
- [ ] **TODO 5** (`bootstrap_ci`, `paired_compare`). Pure NumPy/SciPy, no GPU. `record_e0` depends on `bootstrap_ci`.
- [ ] **TODO 3** (`recode_metrics`, `family_worst_case`). Also no GPU. Compare each perturbation against *its own* nominal set (`FAMILY_NOMINAL`).
- [ ] Unit-test both on tiny hand-made dicts (e.g. check the McNemar p-value against `scipy.stats.binomtest`).

### Phase 2 — Quantization
- [ ] **TODO 1a** `load_model` for all four configs.
- [ ] **TODO 1b** choose calibration data, implement `build_calibration_set` and `run_gptq`.
  - Candidates: `theblackcat102/evol-codealpaca-v1` (code instructions), `wikitext` (general text), chat data.
  - Defaults: 256 samples × 512 tokens. Record dataset, count, and length for the report.
  - **Load in float32**, or the Hessians overflow and GPTQ silently degrades to round-to-nearest. `run_gptq_checked` deletes the checkpoint if more than 10% of layers fell back.
- [ ] Run the sanity-check cell (two problems on `fp16`) and confirm the output is not empty or garbled.

### Phase 3 — E2 or E3
- [ ] **E2:** implement `run_evaloop` (use `cache.run` for every generation; add `SAMPLES` rows with `eval="E2"`, `variant=f"loop{k}"`) and `asl`. Only problems still passing continue to the next loop.
- [ ] **E3:** implement `record_e3`. Set `RUN_E3 = True`. Costs roughly another hour.
- [ ] Doing both earns the +5 bonus. E2 is on by default, so E3 is the extra.
- [ ] Document any departure from the EVALOOOP paper (HumanEval instead of MBPP+, 3 loops instead of 10).

### Phase 4 — QUICK dry run
- [ ] Run everything with `QUICK = True`, then `check_complete()`. Fix crashes while they are cheap.

### Phase 5 — Full run
- [ ] Set `QUICK = False`. Start early, because it takes about **2.5 hours** for E0–E2 (plus about 1 hour for E3). GPTQ is about 10 minutes. `int8` is about 3× slower than the rest.
- [ ] **Keep the browser tab open.** The Colab local disk is wiped on disconnect. Re-running resumes from the cache only while the runtime lives.
- [ ] Download the `.ipynb` with outputs as soon as it finishes.

### Phase 6 — Report (notebook Part 6, markdown cells)
- [ ] **9.1 Quantization:** library versions, GPTQ calibration choice with justification, efficiency table, and the caveat that `transformers` decompresses GPTQ to fp16 on a T4, so memory and speed do not reflect a real int4 kernel.
- [ ] **9.2 Results:** E0 and E1 per config, **absolute and conditional side by side**. Which families get worse? Do `nf4` and `gptq4` differ? Which differences survive McNemar and the paired CI? Then E2 (ASL and the per-loop curve) and/or E3 (spread).
- [ ] **9.3 Three flipped examples:** use the `flips()` helper. For each, give the perturbation, both completions, and what went wrong.
- [ ] **9.4 Conclusion and threats to validity:** one model, one seed, greedy decoding, a subset of perturbations, calibration set, decompressed GPTQ inference.
- [ ] **9.5 AI assistance:** what was used and for what.

### Phase 7 — Submit to Gradescope
- [ ] `.ipynb` with all outputs from the `QUICK = False` run, top to bottom.
- [ ] `README.md` covering: how to run it and library versions; per-TODO notes; GPTQ calibration set, size, and why; departures from ReCode/EVALOOOP/Sclar; whether E2 and/or E3 was run; material AI assistance.

## Pitfalls to watch

1. **The confound.** A config that solves fewer nominal problems has fewer to lose, so it can look more robust. Always report conditional robustness next to absolute numbers and discuss any disagreement.
2. **Wrong nominal baseline.** Syntax and format families use `nominal_partial`; docstring and func_name use `nominal`.
3. **Noise.** With 164 problems, a 3-point gap is often noise. Report discordant counts, not just p-values.
4. **GPTQ in fp16** silently becomes RTN. Calibrate in float32 and respect the fallback check.
5. **Calibration leakage.** No HumanEval or ReCode data.
6. **EVALOOOP fixed point.** Under greedy decoding, loops 3–5 gave identical pass rates in the pilot. Discuss what that means for ASL as a robustness measure.
7. **Cell order.** The TODO functions must be defined before the "Run everything" cell executes.

## Readings

- ReCode (Wang et al., arXiv:2212.10264), §3 and §4
- Wei et al., *Greener yet Powerful* (arXiv:2303.05378): ReCode on quantized code models. Compare your findings with theirs.
- EVALOOOP (arXiv:2505.12185) for E2; Sclar et al. (arXiv:2310.11324) for E3
- GPTQ (arXiv:2210.17323); LLM.int8() (arXiv:2208.07339); QLoRA (arXiv:2305.14314)
