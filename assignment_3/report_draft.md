# Assignment 3 report draft: Does quantization make code LLMs brittle?

Draft for notebook Part 6 (sections 9.1 to 9.5). Every number comes from the saved outputs of the full run
(`QUICK = False`, 164 problems, E0 + E1 + E2). Items marked **[CHECK]** need your confirmation before submitting.

**Terms used below.**
- *Plain prompt* (called "nominal" in the notebook): the original, unmodified HumanEval problem.
- *Perturbed prompt*: the same problem after a ReCode change (renamed function, reworded docstring, and so on).
- *Points*: percentage points of pass rate. "4 points lower" means 0.70 versus 0.66.
- *Gap*: fp16's score minus the quantized model's score. A positive gap means quantization made it worse.
- *Conditional robustness*: out of the problems a model solves on the plain prompt, the share it still solves after the
  perturbation. It separates "the model got worse at the task" from "the model is more easily thrown by changes".

---

## 9.1 Quantization

**Setup.** Colab Tesla T4 GPU. torch 2.11.0+cu130, transformers 5.17.0, llmcompressor 0.14.0, compressed-tensors 0.19.0,
bitsandbytes 0.50.2. Model: `Qwen/Qwen2.5-Coder-1.5B-Instruct`, float16, greedy decoding.

| Config | How it was made |
|---|---|
| `fp16` | original weights, no quantization |
| `int8` | 8-bit, LLM.int8() through bitsandbytes |
| `nf4` | 4-bit NF4 through bitsandbytes |
| `gptq4` | 4-bit GPTQ (group size 128), run by me with llmcompressor; `lm_head` left unquantized |

**GPTQ calibration data.** GPTQ picks its rounding by looking at a small set of example text, so the choice of that text
can matter.
- **What I used:** `theblackcat102/evol-codealpaca-v1` (code instructions with answers), 256 samples of up to 512 tokens,
  formatted with the model's chat template, shuffled with seed 42.
- **Why:** the evaluation asks the model to complete Python code through the chat template, so code instructions with
  answers match both the topic and the format. It is a different source from HumanEval and ReCode.
- **Keeping HumanEval out:** I dropped any sample that defines a function with a HumanEval function name. Of the first 1024
  shuffled candidates, **62 (6%) were dropped**, so a filter was needed. It only checks names, so it would miss a rewritten
  version of a HumanEval problem. **[CHECK: say whether you accept that limit.]**
- **Precision:** I ran calibration in float32. In float16 the numbers overflow on a T4 and llmcompressor quietly falls
  back to simple rounding instead of GPTQ. The notebook's check confirmed that did not happen: 196 layers quantized, no warnings
  or NaN errors, 523 seconds.
- **Not tested:** I used one calibration set and did not compare against another (for example wikitext), so I can't say how
  much this choice affects the results.

**A problem I hit with loading the GPTQ model.** Loading the saved checkpoint with the library's normal `from_pretrained`
did not work here. The 196 quantized layers were left randomly initialized, and the model produced garbage (0 of 20 problems
on the quick test run). The saved checkpoint and its config were fine (4-bit, group size 128, `lm_head` excluded). I could not
tell from the library code why the load failed. So I wrote my own loader (`load_gptq4`): it reads the 4-bit weights from
the checkpoint file, multiplies them by their saved scales to get ordinary fp16 numbers, and puts them into the fp16 model.
This is the same step the library does on the first forward pass. As a check, the rebuilt weights are on average **0.159
(16%) away from the original fp16 weights, at most 0.276**, which is the normal size of 4-bit rounding error. A wrong layout would
be off by more than 1.

**Memory, speed and size (T4).**

| Config | Weights in memory | Peak GPU memory | Tokens per second | Size on disk |
|---|---|---|---|---|
| fp16 | 3.09 GB | 6.38 GB | 90.1 | n/a |
| int8 | 1.78 GB | 5.41 GB | 29.4 | n/a |
| nf4 | 1.12 GB | 4.50 GB | 80.5 | n/a |
| gptq4 | 3.09 GB | 6.38 GB | 85.2 | 1.64 GB |

- nf4 saves the most memory (about 64% less weight memory than fp16) and is only about 10% slower.
- int8 saves 42% of the weight memory but is **about 3x slower** than fp16. It was the main reason the full run took 125 minutes.
- **gptq4 gets no memory or speed benefit here.** It is stored in 4 bits (1.64 GB on disk), but I run it as an ordinary
  fp16 model, so in memory and in speed it looks like fp16. Its *accuracy* is that of 4-bit weights, but a dedicated 4-bit
  engine (such as vLLM) would give different memory and speed numbers.

---

## 9.2 Results

### Clean accuracy (E0)

Pass@1 is the share of problems solved on the first try, out of 164. There are two plain sets: the full original
prompts (`nominal`) and the half-written-code versions that the syntax and format perturbations start from
(`nominal_partial`).

| Config | nominal | gap to fp16 | nominal_partial | gap to fp16 |
|---|---|---|---|---|
| fp16 | 0.701 | | 0.744 | |
| int8 | 0.701 | 0.0 points | 0.738 | 0.6 points |
| nf4 | 0.659 | 4.3 points | 0.707 | 3.7 points |
| gptq4 | 0.689 | 1.2 points | 0.726 | 1.8 points |

To check whether a gap is real I compared each model with fp16 *problem by problem* (a McNemar test). Two models can score
the same while solving different problems, and the test looks at the problems where only one of them succeeds. The p-value
is the chance of a split at least this lopsided if the two models were really equally good; below 0.05 is the usual bar.

| Config | Prompt set | Only fp16 solved | Only the config solved | p-value |
|---|---|---|---|---|
| int8 | nominal | 4 | 4 | 1.00 |
| int8 | nominal_partial | 1 | 0 | 1.00 |
| gptq4 | nominal | 8 | 6 | 0.79 |
| gptq4 | nominal_partial | 5 | 2 | 0.45 |
| nf4 | nominal | 9 | 2 | 0.065 |
| nf4 | nominal_partial | 13 | 7 | 0.26 |

**In short:** int8 matches fp16. gptq4 is a little lower, but not by more than chance could produce. nf4 is about 4 points
lower on plain prompts; that is borderline (95% range for the gap: 0.6 to 8.5 points, p = 0.065).

### Robustness to perturbations (E1)

A problem counts as robust for a family only if the model passes **both** perturbations in it. *Robust Pass@1* is the
share of problems solved on the perturbed prompts. *Conditional* is defined at the top. *Robust Drop@1* is the relative loss
from the plain score (for example, 0.200 means the model lost 20% of what it solved).

| Family (compared with) | Metric | fp16 | int8 | nf4 | gptq4 |
|---|---|---|---|---|---|
| docstring (nominal) | Robust Pass@1 | 0.561 | 0.543 | 0.494 | 0.537 |
| | Conditional | 0.791 | 0.774 | 0.741 | 0.770 |
| | Robust Drop@1 | 0.200 | 0.226 | 0.250 | 0.221 |
| func_name (nominal) | Robust Pass@1 | 0.683 | 0.665 | 0.610 | 0.652 |
| | Conditional | 0.957 | 0.939 | 0.926 | 0.947 |
| | Robust Drop@1 | 0.026 | 0.052 | 0.074 | 0.053 |
| syntax (nominal_partial) | Robust Pass@1 | 0.402 | 0.390 | 0.396 | 0.390 |
| | Conditional | 0.541 | 0.529 | 0.543 | 0.538 |
| | Robust Drop@1 | 0.459 | 0.471 | 0.440 | 0.462 |
| format (nominal_partial) | Robust Pass@1 | 0.683 | 0.671 | 0.634 | 0.646 |
| | Conditional | 0.918 | 0.909 | 0.879 | 0.891 |
| | Robust Drop@1 | 0.082 | 0.091 | 0.103 | 0.109 |

**Does quantization make any family worse?** Not clearly.
- **Syntax is the hardest family for every model**, fp16 included (it costs all four about 45% of their score). That comes
  from the perturbation, not from quantization.
- **nf4** has somewhat lower conditional robustness in three families (docstring, format, func_name), but I did not test
  whether those gaps are real, so I treat them as hints only.
- **int8 and gptq4** stay within 2 to 3 points of fp16 everywhere.

**Where the absolute and conditional numbers disagree (the confound).** A model that solves fewer plain problems has less
to lose, so it can look more robust by accident.
- **syntax, nf4:** its Robust Drop is 0.440 against fp16's 0.459, which looks *better*. But its Robust Pass is actually
  lower (0.396 vs 0.402), and its conditional robustness is the same (0.543 vs 0.541). The smaller "drop" only appears
  because nf4 started lower (0.707 vs 0.744).
- **docstring/ButterFingers, nf4:** the drop looks as good as fp16's (0.074 vs 0.078), yet nf4 solves 3.6 points fewer
  problems (0.610 vs 0.646) and has lower conditional robustness (0.852 vs 0.887). Here the drop number hides a real loss.
- **func_name/CamelCase, nf4:** its 5.5 point deficit (0.646 vs 0.701) is almost all clean-accuracy loss. Its conditional
  robustness is 0.981 vs fp16's 0.983: it lost only 2 of the 108 problems it solved on plain prompts. Of the 11 problems
  fp16 solves and nf4 fails on CamelCase, **at least 9 are problems nf4 already failed on the plain prompt** (it fails 58
  problems on CamelCase and 56 on the plain prompt).

**Is the loss bigger on perturbed prompts than on plain ones?** For nf4, no: its gaps on perturbed prompts stay within
about 5 points of its plain-prompt gap, in both directions, with no consistent extra loss. For gptq4 two comparisons stand
out: func_name/ButterFinger (4.3 points behind fp16, versus 1.2 on plain prompts) and syntax/VarRenamerCB (5.5 points,
versus 1.8).

### Testing all the comparisons against fp16

I compared each quantized model with fp16 on all 10 datasets (2 plain sets and 8 perturbations), 30 comparisons in total.

| Config | Raw p < 0.05 | Biggest gap | Pattern |
|---|---|---|---|
| int8 | 0 of 10 (smallest p = 0.375) | 1.8 points | no pattern: 7 positive, 2 zero, 1 negative |
| nf4 | 2 of 10 | 6.7 points | fp16 ahead in 8 of 10, average gap 3.7 points |
| gptq4 | 1 of 10 | 5.5 points | fp16 ahead or equal in all 10, average gap 2.1 points |

- The three results below 0.05 are **nf4 on func_name/ButterFinger** (fp16 won 15 problems, nf4 won 4, p = 0.019), **nf4 on
  func_name/CamelCase** (11 vs 2, p = 0.022) and **gptq4 on syntax/VarRenamerCB** (12 vs 3, p = 0.035).
- With 30 tests, about 1.5 of them would fall below 0.05 by chance alone, and the smallest p-value here (0.019) is not
  small enough to stand out from that. I treat these three as hints, not proof. I did not apply a formal multiple-comparison
  correction.
- **How small a difference this can detect:** with 164 problems, the 95% range around each gap is roughly plus or minus
  4 to 6 points. Differences of about 5 points or more can show up as significant; a 2 point loss would not.

**Do nf4 and gptq4 differ?** nf4 is lower than gptq4 on both plain sets (3.0 and 1.9 points) and on 5 of the 8
perturbations (higher on 3), always by less than 5 points. I only compared each against fp16, not against each other, so I
can't say this difference is real. The numbers fit nf4 losing a little more accuracy than gptq4.

### Self-consistency loop (E2)

In each loop the model writes a description of its own code, then writes new code from that description. A problem
"survives" a loop if the new code still passes the tests. ASL (average sustainable loops) is the average number of loops
survived per problem, out of 3. The table shows how many of the 164 problems were still passing.

| Config | Loop 1 | Loop 2 | Loop 3 | ASL | Loop 3 as a share of loop 1 |
|---|---|---|---|---|---|
| fp16 | 115 (0.701) | 72 (0.439) | 67 (0.409) | 1.549 | 0.583 |
| int8 | 115 (0.701) | 77 (0.470) | 71 (0.433) | 1.604 | 0.617 |
| nf4 | 108 (0.659) | 72 (0.439) | 69 (0.421) | 1.518 | 0.639 |
| gptq4 | 113 (0.689) | 72 (0.439) | 67 (0.409) | 1.537 | 0.593 |

I calculated ASL from these counts (the sum of the three loop counts divided by 164); it has no confidence interval.

- Loop 1 is the same as the plain-prompt score. The first description round trip (loop 2) knocks out about a third of
  the solved problems (33 to 37%) in every config. Loop 3 removes only 3 to 6 more.
- ASL only ranges from 1.52 to 1.60, and at loop 3 the configs differ by at most 4 problems out of 164. Three of four
  configs have exactly the same loop 2 count (72). I did not test these differences and I would not call any of them real.
- **The same confound shows up here:** nf4 looks best in the last column (0.639) only because it started lowest (108). Its
  actual loop 3 count (69) is about the same as fp16's (67).
- **What this means for ASL under greedy decoding.** Greedy decoding is deterministic: once the model writes the same code
  twice, it describes it the same way and writes the same code again, so the set of survivors stops changing. Loop 3 already
  loses very little, so with three loops ASL mostly measures a single description round trip. It has little power to
  separate configs that differ by a few problems.

---

## 9.3 Flipped examples

These are problems from `func_name/CamelCase` (function names changed from snake_case to camelCase) that fp16 solves and
nf4 does not, taken from the output of `flips("func_name/CamelCase")`. **[CHECK: as noted above, at least 9 of the 11
such problems were already failing on nf4's plain prompt. The saved output does not say which of the examples below those
are. If you can rerun, `show("nominal", ...)` and the plain-prompt pass flags will settle it.]**

**1. HumanEval/98, `countUpper` (was `count_upper`)**
- fp16 passes: loops with `range(0, len(s), 2)` (even positions).
- nf4 fails (AssertionError): loops with `range(1, len(s), 2)`, which counts **odd** positions. The docstring says even
  positions, and its example (`countUpper('aBCdEf')` returns 1) only works for even ones.
- What went wrong: an off-by-one in where the loop starts, a small slip in reading the task. The new function name can't
  explain it, because the name has nothing to do with the indexing.

**2. HumanEval/65, `circularShift` (was `circular_shift`)**
- fp16 passes: `num_str[-shift:] + num_str[:-shift]`, a right rotation, as asked.
- nf4 fails (AssertionError): `str(x)[shift:] + str(x)[:shift]`, a **left** rotation.
- What went wrong: wrong direction. The docstring's example would not have caught it: for a two-digit number a one-step left
  and a one-step right rotation give the same answer (`"21"`).

**3. HumanEval/19, `sortNumbers` (was `sort_numbers`)**
- fp16 passes: sorts the words directly, with `key=lambda word: number_map[word]`.
- nf4 fails (`KeyError: 3`): turns the words into numbers, sorts the numbers, then tries to turn them back with
  `number_map[value]`. But `number_map` goes from words to numbers, not the other way, so looking up a number in it fails.
- What went wrong: a mistake in a two-step conversion. A logic error, unrelated to the name.

**4. HumanEval/57, `monotonic` (a control case)**
- fp16 passes with one loop that tracks whether the list is rising or falling (non-strict comparisons).
- nf4 fails (AssertionError) with `all(x < y ...)` and `all(x > y ...)`, which are **strict**, so a list with equal
  neighbours fails.
- What went wrong: `monotonic` is already one word, so the CamelCase change leaves the name as it was. This flip cannot be
  caused by the perturbation. It is a plain accuracy difference. **[CHECK with `show("nominal", "HumanEval/57")`.]**

**What the four have in common.** In each case nf4 understood the task but got a small detail wrong (which positions,
which direction, which lookup, strict vs non-strict). None of the mistakes involves the renamed function name. So the evidence
points to "nf4 makes more small implementation slips", not "nf4 is thrown off by unusual names". This agrees with the
CamelCase conditional robustness being the same for both (0.981 vs 0.983).

---

## 9.4 Conclusion and threats to validity

**Answer.** On this model, I found no evidence that any of the three quantization methods makes it *more fragile than its
clean score already shows*.
- **int8:** no measurable difference from fp16 on any dataset or in E2 (largest gap 1.8 points, smallest p = 0.375).
- **gptq4:** a small loss, 1 to 2 points on plain prompts and about 2 points on average across all perturbations.
  One comparison (syntax/VarRenamerCB, 5.5 points) is below 0.05, but that is not convincing among 30 tests.
- **nf4:** a small, fairly consistent accuracy loss (4.3 points on plain prompts, borderline significant). It shows up on
  perturbed prompts at about the same size (3.7 points on average), and for CamelCase it is almost entirely plain accuracy loss.
  Its conditional robustness is 3 to 5 points lower in three of four families (untested) and equal in the fourth.

Overall: a model's clean score is a reasonable guide to its robustness here. nf4 and gptq4 may carry a small extra loss
that this study is too small to confirm or rule out. This is consistent with Wei et al., whose abstract reports a quantized
recipe running a 6B model "without significant accuracy or robustness degradation".
**[CHECK: I only read their abstract. Compare against their ReCode tables before claiming more.]** The perturbation family
that matters most is syntax, and it hurts every model equally.

**What could make this wrong.**
- **One small model.** A 1.5B model may react differently to quantization than larger ones.
- **Limited statistical power.** With 164 problems, differences of 2 to 3 points can't be detected. With 30 comparisons and no
  formal correction, the three results below 0.05 are hints only.
- **Conditional robustness was not tested.** It is the key quantity for the confound, and I report it without a significance test.
- **One seed per perturbation, and only 8 of ReCode's transformations** (2 per family). Other transformations or seeds might
  change the family-level picture.
- **Greedy decoding.** It is fixed and repeatable, but it hides run-to-run variation. Batched fp16 generation can also differ
  slightly depending on how problems are grouped, so a rerun may not match exactly.
- **Calibration set.** One dataset, one size, one seed, filtered by function name only. A different set could shift gptq4's results.
- **gptq4 ran as fp16 through my own loader**, because the library's loader failed. The weights have 4-bit values, but real 4-bit
  kernels were not used, and my loader differs from the standard path.
- **E2:** three loops under greedy decoding saturate quickly, and I report no confidence intervals.
- **E3 (prompt wording sensitivity) was not run.**
- **The base model may have seen HumanEval during training.** That would inflate all four configs alike.

---

## 9.5 AI assistance

**[CHECK: edit this to describe what you actually did and used.]** I used Claude Code (Anthropic) throughout. It wrote
the implementations of the TODOs (the statistics helpers, the ReCode metrics, `load_model`, the GPTQ calibration and run,
`run_evaloop`, `record_e3`), tested them on toy data locally, diagnosed the GPTQ loading failure and wrote the workaround loader,
and drafted this report from the saved outputs. I ran every cell on a Colab T4, supplied the outputs, and made the decisions
on calibration data and scope. I am responsible for every number in this report, and I checked them against the notebook outputs.
