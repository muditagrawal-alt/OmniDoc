# Benchmark run 2026-10-14_revision-d_c797a99

Commit `c797a99`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `nvidia:openai/gpt-oss-20b`. Each question is asked about its own document, web search off.

Notes: Revision D on the development split: retrieval embeds with nomic task prefixes and orders passages by the cross-encoder fused with the hybrid order (cross-encoder on the CPU); the sentence check accepts figures computed from figures the answer has just given, and a rewrite keeps such calculations with their inputs; yes/no questions are decided from what the evidence shows or implies. Development indexes of revision C kept; the server re-embedded them with the task prefixes (index version 3).

## FinanceBench (18 questions)

| Metric | Value |
|---|---|
| Accuracy | **88.9%** (95% CI 67.2%–96.9%) |
| Wrong answers | 0.0% |
| Declined to answer | 11.1% |
| Gold page among the sources | 83.3% |
| Gold page among the cited sources | 83.3% |
| First word, median / p90 | 12.3s / 23.9s |
| Full answer, median / p90 | 15.3s / 32.5s |
| Model calls per question | 4.2 |
| Tokens per question | 20256 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 4 (2) |
| Ingestion | 10 documents, 3778 chunks; upload 345.6s, background 1577.6s (index built at `fd4356a`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 6 | 83.3% |
| metrics-generated | 6 | 100.0% |
| novel-generated | 6 | 83.3% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 6 | 83.3% |
| Information extraction | 4 | 75.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 100.0% |
| Numerical reasoning | 6 | 100.0% |
| Numerical reasoning OR information extraction | 1 | 100.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_00476 | Which debt securities are registered to trade on a national securities exchange under American Express' name … | There are none | The assistant declined to answer, but the correct answer is that there are none. |
| financebench_id_01981 | Was American Express able to retain card members during 2022? | Yes | The assistant declined to answer, whereas the reference answer is affirmative. |

## MMLongBench-Doc (31 questions)

| Metric | Value |
|---|---|
| Accuracy | **77.4%** (95% CI 60.2%–88.6%) |
| Wrong answers | 19.4% |
| Declined to answer | 3.2% |
| Accuracy on answerable questions | 84.6% |
| Unanswerable questions correctly declined (5) | 40.0% |
| F1 (MMLongBench-Doc definition) | 81.5% |
| Gold page among the sources | 100.0% |
| Gold page among the cited sources | 92.3% |
| First word, median / p90 | 12.7s / 19.2s |
| Full answer, median / p90 | 17.8s / 24.8s |
| Model calls per question | 3.6 |
| Tokens per question | 35333 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 4 (3) |
| Ingestion | 4 documents, 580 chunks; upload 90.0s, background 901.3s (index built at `408ac1a`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 100.0% |
| Figure | 11 | 72.7% |
| Multi-page | 12 | 83.3% |
| Not answerable | 5 | 40.0% |
| Pure-text | 4 | 100.0% |
| Single-page | 14 | 85.7% |
| Table | 13 | 92.3% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 8 | 75.0% |
| Financial report | 10 | 100.0% |
| Guidebook | 6 | 66.7% |
| Tutorial/Workshop | 7 | 57.1% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0084 | What is the color on the watch that shows the aerobic zone? | yellow | The assistant answered green, which does not match the reference answer yellow. |
| mm_0087 | How many distinct button functions are there during a workout? | 5 | The assistant states 6 functions, but the reference answer is 5. |
| mm_0440 | In the 4rd Wiki filtering, how many more entities were filtered out compared to the 1st Wiki filtering? | Not answerable | The assistant provides a specific answer, but the reference answer indicates the question is not answerable. |
| mm_0441 | How many times do various sizes of the Eiffel Tower appear in the image? | 20 | The assistant gives 11 instead of the correct 20. |
| mm_0962 | How many black arrows are part of the DISCIPLINED AGILE logo? | 2 | Assistant declined to answer the question. |
| mm_0963 | How many blue arrows are part of the DISCIPLINED AGILE logo? | Not answerable | The assistant provides an answer instead of declining, so it is not correct given the reference answer. |
| mm_0966 | How many different Japanese characters are shown in slide? | Not answerable | The assistant provided an answer instead of declining, so it is not correct. |

