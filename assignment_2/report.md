# Assignment 2 — Code Embedding and Visualization: Findings

## Setup

- **Data**: 5 true-clone pairs (10 Java function snippets) sampled with a fixed seed (42) from
  `google/code_x_glue_cc_clone_detection_big_clone_bench` (streaming split, filtered to `label == True`).
- **Embeddings**: `microsoft/codebert-base`, mean-pooled over the last hidden layer (attention-mask-weighted
  average across tokens), giving one 768-dim vector per snippet.
- **Visualization**: scikit-learn `TSNE` (`perplexity=4`, since the default of 30 is invalid for only 10
  samples), PCA initialization, fixed random state.
- Full runnable pipeline is in [`assignment2.ipynb`](assignment2.ipynb); figure saved as
  [`tsne_codebert_clone_pairs.png`](TSNE_embeddings_visual.png).

## What we observed

**The TSNE plot does not show the 5 labeled clone pairs clustering together.** Out of 5 pairs, only one
(pair 3: `pair3A` / `pair3B`) landed visually close to its partner. The other four pairs (0, 1, 2, 4) are
scattered across the plot, each point closer to snippets from *unrelated* pairs than to its own labeled
clone partner.

We backed this up numerically with a cosine similarity matrix computed directly in the original 768-dim
embedding space (before the TSNE projection), plus a nearest-neighbor check: for each of the 10 snippets, is
its closest neighbor by cosine similarity actually its labeled clone partner?

- **Only 1 out of 10 snippets** (`pair3A`, whose nearest neighbor was `pair3B`) had its labeled clone
  partner as its closest match.
- All pairwise cosine similarities were extremely high and tightly clustered — roughly **0.965 to 0.996**
  across *every* pair of snippets, including pairs that are semantically unrelated (e.g., a URL-reading
  method vs. a stack-migration method). The gap between "same labeled pair" similarity and "different pair"
  similarity was small relative to the overall similarity range, so raw cosine similarity in this space
  barely discriminates between clone and non-clone snippets.

So overall: **raw, mean-pooled CodeBERT embeddings did not clearly separate true clone pairs from
unrelated code in either the TSNE plot or the underlying similarity space**, for this small 10-snippet
sample.

## Why this is plausible (not necessarily what we'd want, but consistent with known behavior)

- **CodeBERT-base is a pretrained masked-language-model encoder, not a sentence/code embedding model.** It
  was trained with masked language modeling + replaced-token detection objectives, not a
  contrastive/similarity objective (unlike, e.g., a sentence-transformers-style model or a model
  specifically fine-tuned for the clone-detection downstream task). Raw hidden states from such encoders are
  known to be **anisotropic** — they occupy a narrow cone in embedding space, which is exactly why we see
  cosine similarities uniformly bunched near 1.0 regardless of semantic relationship.
- **Mean pooling over raw (non-fine-tuned) BERT-family layers is a weak sentence-embedding strategy** in
  general; it's well documented (e.g., in the Sentence-BERT literature) that this produces embeddings
  dominated by generic lexical/frequency signals (shared boilerplate tokens like `public`, `void`, `throws
  IOException`, brace/parenthesis patterns common to all Java methods) rather than task-specific semantic
  content. Since all 10 of our snippets are Java methods with similar surface structure (access modifiers,
  exception declarations, common control-flow keywords), this shared "Java-ness" likely dominates the
  pooled vector more than the deeper semantic content that would distinguish true clones from unrelated
  code.
- **CodeXGLUE's BigCloneBench "clones" include semantic clones that are not textually similar** (Type-3/
  Type-4 clones — same behavior, very different implementation), which is a harder signal for a
  general-purpose pretrained encoder to pick up on without fine-tuning specifically on the clone-detection
  task (the way the CodeXGLUE benchmark's actual leaderboard models do, typically by fine-tuning CodeBERT
  with a classification head on exactly this pairwise task).
- Small sample size (n=10) also means TSNE's 2D projection is not very stable/meaningful — with so few
  points, apparent "closeness" in the 2D plot can shift a lot between runs/seeds and doesn't necessarily
  reflect true relative distances in the original 768-dim space well.

## Takeaway

This is a useful negative result: **off-the-shelf CodeBERT embeddings (mean-pooled, no fine-tuning) are not
a strong out-of-the-box semantic similarity signal for clone detection** — the model needs to be fine-tuned
on the clone-detection task (as the original CodeXGLUE benchmark models are) before its representations
reliably separate clones from non-clones. Simply loading the pretrained model and embedding snippets is not
sufficient to reproduce the "clones cluster together" intuition one might expect from the assignment
prompt's example finding.
