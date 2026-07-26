# Evaluation Metrics & Approaches

This document defines the evaluation framework for the Research-Agent synthesis pipeline. Metrics are organized by category to cover quality, retrieval, clustering, validation, end-to-end performance, user experience, and resource efficiency.

---

## 1. Synthesis Quality Metrics

These measure how good the generated research gaps are.

### 1.1 Citation Grounding Rate

**Definition:** Percentage of gaps where every `[N]` citation actually supports the claim.

**Measurement:** Run `validate_gap_citations()` from `citation_validation.py` on each gap. Compute the fraction where `status` is `"grounded"` or `"weakly_supported"`.

**Target:** > 90% grounded

### 1.2 Hallucination Rate

**Definition:** Percentage of gaps flagged as `"Hallucinated"` by `verify_gap_with_llm()`.

**Measurement:** Count gaps where `llm_verification.status == "hallucinated"`.

**Target:** < 5%

### 1.3 Semantic Overlap Between Gaps

**Definition:** Whether gaps across different clusters are meaningfully distinct or redundant.

**Measurement:** Compute cosine similarity between gap descriptions (using the embedding model). Flag pairs with similarity > 0.85 as duplicates.

**Target:** < 10% of gap pairs are near-duplicates

### 1.4 Gap Actionability Score

**Definition:** Whether proposed directions are concrete experiments rather than vague wishes.

**Measurement:** Heuristic count of imperative verbs and specific parameter mentions in `proposed_direction`. Classify as "concrete" or "vague".

**Target:** > 80% concrete directions

### 1.5 LLM Self-Consistency

**Definition:** Whether the gap description uses only claims supported by the cited paper contexts.

**Measurement:** For each sentence ending with `[N]`, verify the claim terms appear in the cited paper's contribution/limitations/future-work text.

**Target:** 100% of sentences pass grounding check

---

## 2. Retrieval Quality Metrics

These measure how well the paper search retrieves relevant literature.

### 2.1 Precision@10

**Definition:** Of the top 10 retrieved papers, how many are relevant to the topic?

**Measurement:** Have domain experts label 50+ query topics as relevant/not relevant. Compute `relevant_retrieved / 10`.

**Target:** > 0.75

### 2.2 Recency Coverage

**Definition:** Fraction of retrieved papers from the last 2 years.

**Measurement:** Count papers with `year >= current_year - 2` in results.

**Target:** > 30% (varies by topic)

### 2.3 Source Diversity

**Definition:** Are papers from multiple sources or dominated by one?

**Measurement:** Shannon entropy of source distribution (`semantic_scholar`, `openalex`, `arxiv`, `tavily`).

**Target:** Entropy > 0.5 (balanced across sources)

### 2.4 Deduplication Accuracy

**Definition:** Are duplicate papers properly merged?

**Measurement:** Inject known duplicate pairs (same paper from different sources) into test queries. Check deduplication rate.

**Target:** > 95%

### 2.5 Filter Precision

**Definition:** Do year and venue filters work correctly?

**Measurement:** Test with known date-bounded topics (e.g., "transformers 2017-2019"). Verify all results fall in range.

**Target:** 100% in range

---

## 3. Clustering Quality Metrics

These measure how meaningful the UMAP+HDBSCAN clusters are.

### 3.1 DBCV Score (Density-Based Clustering Validation)

**Definition:** Internal cluster validity score already computed by HDBSCAN (`relative_validity_`).

**Measurement:** Monitor `cluster_accuracy` field in synthesis response. Range: -1 to 1, higher is better.

**Target:** > 0.3 (meaningful clustering)

### 3.2 Cluster Purity (Human Evaluation)

**Definition:** Do papers within a cluster genuinely share a research theme?

**Measurement:** Have domain experts label 20+ clusters as "coherent" or "incoherent".

**Target:** > 80% coherent

### 3.3 Noise Ratio

**Definition:** Percentage of papers labeled as noise (`label == -1` by HDBSCAN).

**Measurement:** Count `-1` labels in output.

**Target:** < 10%

### 3.4 Cluster Size Distribution

**Definition:** Are clusters balanced or is one cluster dominant?

**Measurement:** Coefficient of variation of cluster sizes. Report min, max, median, mean cluster sizes.

**Target:** CV < 1.0 (no single cluster dominates)

---

## 4. Citation Validation Metrics

These measure the accuracy of the citation grounding system.

### 4.1 Semantic Grounding Accuracy

**Definition:** Does cosine similarity correctly distinguish grounded from hallucinated citations?

**Measurement:** Create a labeled dataset of 100+ (claim, cited_paper) pairs. Compute ROC-AUC for the 0.18 threshold.

**Target:** ROC-AUC > 0.85

### 4.2 Threshold Calibration

**Definition:** Is 0.18 the right hallucination threshold?

**Measurement:** Vary threshold from 0.05 to 0.50. Plot precision-recall curve. Find optimal threshold.

**Target:** F1 > 0.80 at optimal threshold

### 4.3 Cross-Paper Validation Accuracy

**Definition:** Does `validate_gap_against_supported_papers` correctly identify when a gap IS and ISN'T addressed by the cluster?

**Measurement:** Test with known cases where papers in the cluster DO address the gap and cases where they don't.

**Target:** Accuracy > 0.80

---

## 5. End-to-End Pipeline Metrics

### 5.1 Synthesis Latency

**Definition:** Time from receiving a synthesis request to returning the complete result.

**Measurement:** Log timestamp at each pipeline stage: `prepare`, `retrieval`, `embedding`, `clustering`, `gaps`, `visualizations`, `complete`.

**Target:** < 60s for 20 papers, < 120s for 50 papers

### 5.2 Token Cost Per Synthesis

**Definition:** Total LLM tokens consumed per synthesis run (input + output across all LLM calls).

**Measurement:** Sum token counts from all `_call_openrouter` and `_call_local_model` invocations.

**Target:** < 50K tokens per synthesis run (for ~15 papers)

### 5.3 Success Rate

**Definition:** Percentage of synthesis runs that complete without falling back entirely to heuristic gaps.

**Measurement:** Track ratio of LLM-generated gaps vs heuristic-only gaps.

**Target:** > 90% of clusters get LLM-generated gaps

### 5.4 Cache Hit Rate

**Definition:** Percentage of synthesis requests served from cache instead of running the full pipeline.

**Measurement:** Track `is_cached` field in response vs total requests.

**Target:** > 20% for repeated queries on same topic

### 5.5 Error Rate

**Definition:** Percentage of synthesis runs that fail with an error.

**Measurement:** Monitor exceptions in `run_synthesis_pipeline`.

**Target:** < 1%

---

## 6. User Experience Metrics

### 6.1 Time-to-First-Result

**Definition:** How quickly does the first progress event appear after the user submits a query?

**Measurement:** Frontend timestamp of first SSE event minus query submit time.

**Target:** < 5 seconds

### 6.2 Gap Relevance (User Rating)

**Definition:** Do users find the generated gaps useful and accurate?

**Measurement:** Add thumbs up/down interaction on gaps (already partially tracked in `gap_feedback_signals`). Compute positive rating ratio.

**Target:** > 70% positive ratings

### 6.3 Exploration Depth

**Definition:** How many clusters/gaps do users examine before forming a conclusion?

**Measurement:** Track interaction events per session.

**Target:** > 3 gaps examined per session

### 6.4 Task Completion Rate

**Definition:** Percentage of users who export or share a report after synthesis.

**Measurement:** Track download/share button clicks.

**Target:** > 20%

---

## 7. Resource Efficiency Metrics

### 7.1 LLM Token Usage

**Breakdown per synthesis run:**

| Component | Typical Usage |
|-----------|---------------|
| Retrieval (cached) | 0 tokens |
| Embedding | 0 tokens (local) |
| Clustering | 0 tokens (local) |
| Gap generation (per cluster) | ~800-3000 input tokens |
| Gap verification (per cluster) | ~200-500 input tokens |
| Pattern analysis | 0 tokens (local) |
| Total for 10 clusters | ~10K-35K tokens |

**Target:** < 30K tokens per synthesis run (15 papers)

### 7.2 P95 Synthesis Time

**Definition:** 95th percentile of synthesis completion time.

**Measurement:** Histogram of `complete_stage - prepare_stage` durations.

**Target:** P95 < 45s

### 7.3 DB Operation Latency

**Definition:** Time spent in MongoDB operations per synthesis run.

**Measurement:** Instrument `save_search_history`, `_save_report_to_mongo`, `append_gap_dataset_record`.

**Target:** < 1s for all DB operations combined

### 7.4 Memory Usage (Peak RSS)

**Definition:** Peak resident set size of the synthesis process.

**Measurement:** Monitor via `psutil` or `/proc/self/status`.

**Target:** < 1.5 GB peak RSS

### 7.5 Fallback Rate

**Definition:** Percentage of OpenRouter calls that had to fall back to the fallback model.

**Measurement:** Track primary vs fallback model usage in `_call_openrouter`.

**Target:** < 5%

---

## 8. Recommended Evaluation Setup

### Ground Truth Dataset

Curate 50-100 known literature review topics with expert-annotated gaps:

- Each topic should have 5-10 known gaps with citations
- Gaps should span different themes (methodology, evaluation, deployment)
- Include both well-grounded and borderline cases

### Automated Evaluation Pipeline

```
synthesis_run(topic)
  → extract_gaps(result)
  → compare_vs_ground_truth(topic, gaps)
  → compute(grounding_rate, hallucination_rate, novelty_score, actionability_score)
  → log_metrics(run_id, metrics)
```

### Human Evaluation Protocol

1. Have 3+ domain experts rate gap quality on a 1-5 scale for 20+ topics
2. Inter-rater reliability measured by Cohen's kappa
3. Compare LLM-generated gaps vs heuristic-only gaps
4. Compare original prompt vs optimized prompt outputs

### A/B Testing Scenarios

| Test | Variation | Measure |
|------|-----------|---------|
| Prompt length | Full prompt vs trimmed prompt | Grounding rate, hallucination rate |
| Min cluster size | 2 vs 3 vs 4 | Cluster quality (DBCV) + gap coverage |
| Verification tokens | 300 vs 1500 max_tokens | Verification accuracy |
| Dedup threshold | 0.75 vs 0.85 vs 0.95 | Duplicate gap rate |
| Cross-validation skip | Enabled vs disabled for base_score < 0.3 | Quality impact |

---

## 9. Monitoring Dashboard (Recommended)

Track these live metrics in a dashboard:

- Synthesis latency (per stage, P50/P95/P99)
- Token cost per run (daily/weekly averages)
- Cache hit rate
- Error rate
- Grounding rate (sample 10% of runs)
- Hallucination rate (sample 10% of runs)
- DBCV score distribution
- Fallback model usage rate
- Peak memory usage
- DB operation latency