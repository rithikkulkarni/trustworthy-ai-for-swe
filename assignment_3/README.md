# README

Files:
- `A3_rrkulka3.ipynb` (notebook with all results and answers)
- `README.md` (this file that explains code)

## How to run

1. Open `A3_rrkulka3.ipynb` on a Colab T4 GPU runtime. I ran it in VSCode using the Google Colab extension to connect a Colab runtime, but it will run just the same on Google Colab in the browser itself.
2. Run the install cell (first code cell). If it changes `torch`, restart your Colab session and continue from the version-check cell.
3. Set `QUICK = False` and run every cell.
4. Time on a T4: GPTQ should take about 9 minutes. E0 + E1 + E2 for all four configs shuold take ~125 minutes (int8 is about 3x slower than the rest).

**Library Versions:**
- torch 2.11.0+cu130
- transformers 5.17.0
- llmcompressor 0.14.0
- compressed-tensors 0.19.0
- bitsandbytes 0.50.2
- **Tesla T4 GPU (Colab runtime)**

## What each TODO implementation does

### **TODO 1a Implementation:** `load_model`
`fp16` loads the original weights for in float16. `int8` uses `BitsAndBytesConfig(load_in_8bit=True)`. `nf4` uses 4-bit NF4 with float16 compute. `gptq4` is loaded through `load_gptq4()` which I had to use because the standard library loader was leading to many errors (this is noted in my **"departures from paper"** section).
### **TODO 1b Implementation:** 
**Calibration data:** `theblackcat102/evol-codealpaca-v1` which is 256 samples with at most 512 tokens each. I shuffled with seed 42. Each sample consists of instruction + answer and is formatted with the model's chat template.
**Why:** The evaluation is python code completion, so the code instructions with answers match both the topic and format. It's a difference source from HumanEval and ReCode. I dropped any sample that defines a function with a HumanEval function name. 62 of the first 1024 shuffled candiduates ended up being dropped before taking 256. This would mess up if a HumanEval problem was rewritten since it just checks the names.
**Precision:** The model is loaded in float32 for calibration. The fallback check passed (196 layers quantized without Hessian failures).

### **TODO 3 Implementation:** `recode_metrics` + `family_worst_case`
Robust Pass@1 is the pass rate for perturbed prompts. Robust Drop@1 is calculated with `(nominal - robust) / nominal`. Robust Relative@1 are the problems whose result changes in either direction. Conditional robustness is the share of nominally solved problems that are still solved after perturbation is done.

### **TODO 4a Implementation:** `run_evaloop`+ `asl`
Loop 1 reuses the E0 generation. Each of the later loops then takes the code that passed previously, takes its docstring, and asks the model to describe it. Then, using that description, generates code to solve the problem again. This is the EvaLoop robustness testing process. All generations go through `cache.run` and each program is logged in `SAMPLES`. `pass_by_loop` is the share of problems that are still passing after a loop.

### **TODO 4b Implementation:** `record_e3`
I did not run E3 at all.

### **TODO 5 Implementation:** `bootstrap_ci` + `paired_compare`
`bootstrap_ci` does a 95% bootstrap of the mean, 10000 resamples, seed 0, resampling problems with replacement.
`paired_compare(a, b)` counts the problems that only A and only B solved, takes the pass-rate difference of A minus B, and does a two-sided McNemar test with a 95% confidence interval (which is why our significance threshold is 0.05 in the report). The bootstrap resamples problems so that each problem's two outcomes will stay together.

## Which of E2 / E3

E2 (EVALOOP) was run. E3 was not.

## Departures from the papers and from the standard path

I used my own code to load gptq4. `from_pretrained` was causing the quantized linear layers to be randomly initialized and the model ended up producing garbage. `load_gptq4()` reads `model.safetensors` and unpacks the int4 weights using compressed tensors. In the end, `gptq4` runs as an ordinary fp16 model but with 4-bit-valued weights. This means that its accuracy is simialr to that of having 4-bit weights, but its memory and speed are not.

## AI assistance

I used Claude Code to assist in my implementations, especially with doing the workaround for loading gptq4, since `from_pretrained` kept running into huge errors in my notebook runs.
