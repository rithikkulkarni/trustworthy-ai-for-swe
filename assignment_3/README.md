# Assignment 3: Does quantization make code LLMs brittle?

Files: `A3_rrkulka3.ipynb` (the notebook, with all outputs and the Part 6 report) and this `README.md`.

## How to run

1. Open `A3_rrkulka3.ipynb` on a Colab **T4 GPU** runtime (I ran it in Colab; it can also be driven from VS Code connected to a Colab runtime).
2. Run the install cell. If it changes `torch`, restart the session and continue from the version-check cell.
3. Set `QUICK = False` and run every cell top to bottom. Keep the tab open: generations are cached on the Colab disk and the disk is wiped on disconnect.
4. Time on a T4: GPTQ about 9 minutes (523 s); E0 + E1 + E2 for all four configs 125 minutes (int8 is about 3x slower than the rest).

**Versions (printed by Part 0):** torch 2.11.0+cu130, transformers 5.17.0, llmcompressor 0.14.0, compressed-tensors 0.19.0, bitsandbytes 0.50.2, Tesla T4.

## What each TODO does

**TODO 1a, `load_model`.** `fp16` loads the original weights in float16. `int8` uses `BitsAndBytesConfig(load_in_8bit=True)`. `nf4` uses 4-bit NF4 with float16 compute (`bnb_4bit_quant_type="nf4"`, no double quantization). `gptq4` loads through `load_gptq4()` (see "Departures" below).

**TODO 1b, GPTQ.** `GPTQModifier(targets="Linear", scheme="W4A16", ignore=["lm_head"])` through `oneshot`, saved with `save_compressed=True` plus the tokenizer.
- **Calibration data:** `theblackcat102/evol-codealpaca-v1`, **256 samples, at most 512 tokens each**, shuffled with seed 42. Each sample is the instruction plus the reference answer, formatted with the model's chat template.
- **Why:** the evaluation is Python code completion through the chat template, so code instructions with answers match both the topic and the format. It is a different source from HumanEval and ReCode.
- **Keeping HumanEval out:** I drop any sample that defines a function with a HumanEval function name (`def <entry_point>(`). 62 of the first 1024 shuffled candidates were dropped before taking 256. This only checks names, so it would miss a rewritten HumanEval problem.
- **Precision:** the model is loaded in float32 for calibration, as the notebook requires. The provided fallback check passed (196 layers quantized, no Hessian failures).

**TODO 3, `recode_metrics` and `family_worst_case`.** Robust Pass@1 is the pass rate on the perturbed prompts. Robust Drop@1 is `(nominal - robust) / nominal`. Robust Relative@1 is the share of problems whose pass/fail outcome changes in either direction. Conditional robustness is the share of nominally solved problems still solved after the perturbation. Each perturbation is compared with its own nominal set (`FAMILY_NOMINAL`). `robust_drop` and `conditional_robust` return NaN if the nominal set solves nothing, so `check_complete()` would flag it. `family_worst_case` marks a problem robust only if it passes every variant in the family.

**TODO 4a, `run_evaloop` and `asl`.** Loop 1 reuses the E0 generation. Each later loop takes the code that passed in the previous loop, strips its docstring, asks the model to describe it (`describe_input`, stop at `DOC_STOP`, 256 new tokens), builds a new prompt from that description, generates code with `chat_input`, and tests it against the original problem's tests. Only problems that passed every earlier loop continue. All generations go through `cache.run`, and each program is logged in `SAMPLES` with `eval="E2"`, `variant=f"loop{k}"`. `survived[t]` is the number of consecutive loops passed, `pass_by_loop` is the share of all problems still passing, and ASL is the mean of `survived`.

**TODO 4b, `record_e3`.** Written (per-template pass@1 with a bootstrap CI, the spread max minus min with a bootstrap CI, and the count and share of template-sensitive problems) and tested on toy data, **but E3 was not run** (`RUN_E3 = False`).

**TODO 5, `bootstrap_ci` and `paired_compare`.**
- `bootstrap_ci`: 95% percentile bootstrap of the mean, 10,000 resamples, seed 0, resampling problems with replacement.
- `paired_compare(a, b)`: counts of problems only A solved and only B solved, the pass-rate difference A minus B, an exact two-sided McNemar test (a binomial test on those discordant problems, p = 1.0 if there are none), and a paired bootstrap 95% CI. The bootstrap resamples whole problems so each problem's two outcomes stay together.

## Which of E2 / E3

**E2 (EVALOOOP) was run. E3 was not.**

## Departures from the papers and from the standard path

- **`gptq4` is loaded by my own code, not `from_pretrained`.** With transformers 5.17.0 and compressed-tensors 0.19.0, `from_pretrained` on the saved checkpoint left the 196 quantized Linear layers randomly initialized (reported MISSING, with `weight_packed` / `weight_scale` UNEXPECTED), and the model produced garbage. The checkpoint itself was fine. `load_gptq4()` reads `model.safetensors`, unpacks the int4 weights with compressed-tensors' `unpack_from_int32`, multiplies by the saved per-group scales, and writes the result into an fp16 model. It checks that the checkpoint is symmetric 4-bit group-128 and that all 196 layers are used, and it prints the rebuilt weights' relative error versus the original fp16 weights (mean 0.159, max 0.276; the loader fails above 0.5). So `gptq4` runs as an ordinary fp16 model with 4-bit-valued weights: its accuracy is that of 4-bit weights, but its memory and speed are not.
- **EVALOOOP (E2):** HumanEval instead of MBPP+ and 3 loops instead of 10 (the class setting). The description step shows the model the *sanitized* version of the previous code (the same code that was tested) with its docstring removed, so self-tests the model appended do not leak into the description.
- **ReCode (E1):** the fixed class subset (2 transformations per family, seed 0), greedy decoding, one sample, so the paper's metrics reduce to the forms in TODO 3. I added conditional robustness, as the assignment requires.
- **GPTQ calibration:** the name-based HumanEval filter described above.
- **Sclar et al. (E3):** not run, so no departures to report.

## AI assistance

[TO FILL IN: describe accurately which AI tools you used and for what. The assignment requires this, and it should match what you actually did.]
