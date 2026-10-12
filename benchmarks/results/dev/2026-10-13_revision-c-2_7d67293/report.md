# Benchmark run 2026-10-13_revision-c-2_7d67293

Commit `7d67293`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `nvidia:openai/gpt-oss-20b`. Each question is asked about its own document, web search off.

Notes: Revision C (7d67293) on the development split: short PDFs read whole for every question, statement triggers for cash ratios.

## MMLongBench-Doc (31 questions)

| Metric | Value |
|---|---|
| Accuracy | **74.2%** (95% CI 56.8%–86.3%) |
| Wrong answers | 19.4% |
| Declined to answer | 6.5% |
| Accuracy on answerable questions | 76.9% |
| Unanswerable questions correctly declined (5) | 60.0% |
| F1 (MMLongBench-Doc definition) | 76.9% |
| Gold page among the sources | 100.0% |
| Gold page among the cited sources | 84.6% |
| First word, median / p90 | 9.4s / 14.1s |
| Full answer, median / p90 | 12.8s / 19.8s |
| Model calls per question | 4.0 |
| Tokens per question | 36838 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 4 documents, 580 chunks; upload 90.0s, background 901.3s (index built at `408ac1a`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 100.0% |
| Figure | 11 | 72.7% |
| Multi-page | 12 | 75.0% |
| Not answerable | 5 | 60.0% |
| Pure-text | 4 | 100.0% |
| Single-page | 14 | 78.6% |
| Table | 13 | 76.9% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 8 | 87.5% |
| Financial report | 10 | 80.0% |
| Guidebook | 6 | 50.0% |
| Tutorial/Workshop | 7 | 71.4% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0084 | What is the color on the watch that shows the aerobic zone? | yellow | The assistant incorrectly states the color as orange, while the reference answer is yellow. |
| mm_0086 | What is the color of the icons that the users touch to move the app down? | Not answerable | The assistant provided an answer instead of declining, but the reference answer states the question is not answerable. |
| mm_0087 | How many distinct button functions are there during a workout? | 5 | The assistant states 4 button functions, but the reference answer is 5. |
| mm_0441 | How many times do various sizes of the Eiffel Tower appear in the image? | 20 | The assistant gives a number (4) that does not match the reference answer (20). |
| mm_0962 | How many black arrows are part of the DISCIPLINED AGILE logo? | 2 | The assistant answered 1 black arrow, but the reference answer is 2. |
| mm_0966 | How many different Japanese characters are shown in slide? | Not answerable | The assistant gives a specific answer, but the reference answer states the question is not answerable. |
| mm_1042 | What is receive turnover in FY2021 for Nike? Round your answer to two decimal places. | 12.35 | The assistant states the information cannot be determined, not providing the required figure. |
| mm_1044 | What is cash_ratio in FY2021 for Nike? Round your answer to two decimal places. | 1.02 | The assistant declined to provide the cash ratio, whereas the reference answer gives a specific value. |

