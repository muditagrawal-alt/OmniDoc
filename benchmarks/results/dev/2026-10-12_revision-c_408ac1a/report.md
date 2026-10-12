# Benchmark run 2026-10-12_revision-c_408ac1a

Commit `408ac1a`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `nvidia:openai/gpt-oss-20b`. Each question is asked about its own document, web search off.

Notes: Revision C (408ac1a) on the development split.

## FinanceBench (18 questions)

| Metric | Value |
|---|---|
| Accuracy | **83.3%** (95% CI 60.8%–94.2%) |
| Wrong answers | 5.6% |
| Declined to answer | 11.1% |
| Gold page among the sources | 77.8% |
| Gold page among the cited sources | 66.7% |
| First word, median / p90 | 9.7s / 16.1s |
| Full answer, median / p90 | 18.2s / 27.6s |
| Model calls per question | 4.4 |
| Tokens per question | 17482 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
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
| financebench_id_00476 | Which debt securities are registered to trade on a national securities exchange under American Express' name … | There are none | Assistant declined to answer, whereas the reference answer states there are none. |
| financebench_id_00723 | Does AMEX have an improving operating margin profile as of 2022? If operating margin is not a useful metric f… | Performance is not measured through operating margin | Assistant provides specific operating‑margin figures and claims a trend, contradicting the reference that operating mar… |
| financebench_id_01981 | Was American Express able to retain card members during 2022? | Yes | The assistant declines to answer, whereas the reference answer is a definitive 'Yes'. |

## MMLongBench-Doc (31 questions)

| Metric | Value |
|---|---|
| Accuracy | **74.2%** (95% CI 56.8%–86.3%) |
| Wrong answers | 12.9% |
| Declined to answer | 12.9% |
| Accuracy on answerable questions | 73.1% |
| Unanswerable questions correctly declined (5) | 80.0% |
| F1 (MMLongBench-Doc definition) | 77.6% |
| Gold page among the sources | 84.6% |
| Gold page among the cited sources | 65.4% |
| First word, median / p90 | 9.8s / 18.3s |
| Full answer, median / p90 | 11.3s / 21.6s |
| Model calls per question | 4.0 |
| Tokens per question | 22451 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 4 documents, 580 chunks; upload 90.0s, background 901.3s (index built at `408ac1a`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 100.0% |
| Figure | 11 | 72.7% |
| Multi-page | 12 | 75.0% |
| Not answerable | 5 | 80.0% |
| Pure-text | 4 | 100.0% |
| Single-page | 14 | 71.4% |
| Table | 13 | 69.2% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 8 | 75.0% |
| Financial report | 10 | 70.0% |
| Guidebook | 6 | 100.0% |
| Tutorial/Workshop | 7 | 57.1% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0439 | In the 3rd Wiki filtering, how many more entities were filtered out compared to the 1st Wiki filtering? | 2885 | The assistant’s answer (1,923) does not match the reference answer (2885). |
| mm_0441 | How many times do various sizes of the Eiffel Tower appear in the image? | 20 | The assistant gives a numeric answer (10) that does not match the reference answer (20). |
| mm_0962 | How many black arrows are part of the DISCIPLINED AGILE logo? | 2 | The assistant declined to answer, not providing the required number. |
| mm_0966 | How many different Japanese characters are shown in slide? | Not answerable | The assistant provides a definitive answer, whereas the reference answer states the question is not answerable. |
| mm_0968 | What stages does high level lifecycle have more than basic lifecycle? | ['concept', 'production'] | The assistant lists many stages, but the reference answer only lists ['concept', 'production'], so the answer does not … |
| mm_1044 | What is cash_ratio in FY2021 for Nike? Round your answer to two decimal places. | 1.02 | The assistant declined to provide an answer. |
| mm_1045 | What is cash conversion cycle in FY2021 for Nike? Round your answer to two decimal places. | 97.40 | The assistant declined to provide an answer. |
| mm_1047 | What is cash ratio in FY2021 for Nike? Round your answer to two decimal places. | 1.02 | The assistant declined to provide an answer, whereas the reference answer gives a specific value. |

