# Benchmark run 2026-10-17_ultra_0508fe7

Commit `0508fe7`. Answer model `nvidia:nvidia/nemotron-3-ultra-550b-a55b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `nvidia:openai/gpt-oss-20b`. Each question is asked about its own document, web search off.

Notes: Revision D code with NVIDIA Nemotron 3 Ultra (550B, free) as the answer model instead of Nemotron 3 Super (internal fast steps stay on Super); everything else as in the revision-d dev run.

## FinanceBench (18 questions)

| Metric | Value |
|---|---|
| Accuracy | **83.3%** (95% CI 60.8%–94.2%) |
| Wrong answers | 11.1% |
| Declined to answer | 5.6% |
| Gold page among the sources | 83.3% |
| Gold page among the cited sources | 72.2% |
| First word, median / p90 | 16.1s / 29.9s |
| Full answer, median / p90 | 21.6s / 43.5s |
| Model calls per question | 4.1 |
| Tokens per question | 19175 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 3 (1) |
| Ingestion | 10 documents, 3778 chunks; upload 345.6s, background 1577.6s (index built at `fd4356a`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 6 | 66.7% |
| metrics-generated | 6 | 100.0% |
| novel-generated | 6 | 83.3% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 6 | 83.3% |
| Information extraction | 4 | 75.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 100.0% |
| Numerical reasoning | 6 | 100.0% |
| Numerical reasoning OR information extraction | 1 | 0.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_00476 | Which debt securities are registered to trade on a national securities exchange under American Express' name … | There are none | The assistant lists debt securities, contradicting the reference answer that states none exist. |
| financebench_id_00723 | Does AMEX have an improving operating margin profile as of 2022? If operating margin is not a useful metric f… | Performance is not measured through operating margin | The assistant provides an answer that contradicts the reference, claiming operating margin is relevant and declining, w… |
| financebench_id_01981 | Was American Express able to retain card members during 2022? | Yes | Assistant declined instead of answering Yes. |

## MMLongBench-Doc (31 questions)

| Metric | Value |
|---|---|
| Accuracy | **87.1%** (95% CI 71.1%–94.9%) |
| Wrong answers | 12.9% |
| Declined to answer | 0.0% |
| Accuracy on answerable questions | 88.5% |
| Unanswerable questions correctly declined (5) | 80.0% |
| F1 (MMLongBench-Doc definition) | 86.8% |
| Gold page among the sources | 100.0% |
| Gold page among the cited sources | 88.5% |
| First word, median / p90 | 17.6s / 30.2s |
| Full answer, median / p90 | 22.6s / 35.4s |
| Model calls per question | 3.5 |
| Tokens per question | 33509 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 2 (2) |
| Ingestion | 4 documents, 580 chunks; upload 90.0s, background 901.3s (index built at `408ac1a`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 100.0% |
| Figure | 11 | 81.8% |
| Multi-page | 12 | 83.3% |
| Not answerable | 5 | 80.0% |
| Pure-text | 4 | 100.0% |
| Single-page | 14 | 92.9% |
| Table | 13 | 92.3% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 8 | 87.5% |
| Financial report | 10 | 100.0% |
| Guidebook | 6 | 66.7% |
| Tutorial/Workshop | 7 | 85.7% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0084 | What is the color on the watch that shows the aerobic zone? | yellow | The assistant incorrectly states the color as green instead of the reference answer yellow. |
| mm_0087 | How many distinct button functions are there during a workout? | 5 | The assistant answered 6 instead of the correct 5. |
| mm_0441 | How many times do various sizes of the Eiffel Tower appear in the image? | 20 | The assistant gives 7 instead of the correct answer 20. |
| mm_0966 | How many different Japanese characters are shown in slide? | Not answerable | The assistant provides an answer instead of declining, so it is incorrect. |

