# Benchmark run 2026-10-19_revision-e_8a1ff15

Commit `8a1ff15`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

**Caveat:** Stopped at the night's time limit (23:00) with mmlongbench: 19 of 53 questions: NVIDIA's free tier rate-limited the answers to about 90 s each after a long batch run. Compare only the questions both runs answered.

Notes: Revision E: a financial statement split over two pages (assets on one, liabilities on the next) is given whole; capital intensity, total debt, PPNE, return on average equity and gross profit without a gross profit line are defined, and capital-intensity, debt, interest and tax-rate questions get the statements they need; a ratio the question defines is given as the decimal its formula yields; fiscal years ending in January or February are named by the year they end; questions about registered securities get the filing's cover page; a page named by number is also read where that number is printed when a cover and contents come first (from the stored PDF's headers and footers); survey counts ("how many Democrats said ...") get the survey's sample sizes and are not scanned as pictures; the writer is told the look-alike name the evidence has when the question's name is not in the document; page reads list each instance before counting; instruction words and answer formats are no longer taken for names. Revision C's test indexes (benchmarks/work/revC) kept. Some of these fixes come from misses on the full FinanceBench and MMLongBench-Doc batch 1, which share questions with this test split.

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **77.8%** (95% CI 61.9%–88.3%) |
| Wrong answers | 16.7% |
| Declined to answer | 5.6% |
| Gold page among the sources | 91.7% |
| Gold page among the cited sources | 83.3% |
| First word, median / p90 | 42.2s / 93.7s |
| Full answer, median / p90 | 69.0s / 122.6s |
| Model calls per question | 4.4 |
| Tokens per question | 22965 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 1 |
| Answers rewritten after the sentence check (graded correct) | 6 (3) |
| Ingestion | 24 documents, 10574 chunks; upload 1517.4s, background 3427.5s (index built at `991bbaa`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 12 | 58.3% |
| metrics-generated | 12 | 100.0% |
| novel-generated | 12 | 75.0% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 12 | 75.0% |
| Information extraction | 5 | 80.0% |
| Logical reasoning (based on numerical reasoning) | 2 | 50.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 1 | 100.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 0.0% |
| Numerical reasoning | 11 | 100.0% |
| Numerical reasoning OR Logical reasoning | 3 | 33.3% |
| Numerical reasoning OR information extraction | 1 | 100.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant provided an incorrect ratio (3.65) whereas reference states the ratio is zero due to negative EBIT. |
| financebench_id_00705 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? | $400,000,000 increase. | Assistant gave $750M increase, which does not match the reference $400M increase |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | Answer gives $4.95 billion, which does not match the reference total of $8.4 billion |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | The response does not commit to a yes/no answer, unlike the reference which says Yes. |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | The response only mentions opioid litigation and says no charges in 2021/2020, missing the other ongoing legal battles … |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | The assistant gave a positive working capital but with an incorrect amount ($12.4B vs reference $1.6B). |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | The response says the documents don't provide the drivers, whereas the reference lists specific factors. |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | Answer gives 12.14 times, which does not match reference 9.5 times |

## MMLongBench-Doc (19 questions)

| Metric | Value |
|---|---|
| Accuracy | **57.9%** (95% CI 36.3%–76.9%) |
| Wrong answers | 36.8% |
| Declined to answer | 5.3% |
| Accuracy on answerable questions | 61.1% |
| Unanswerable questions correctly declined (1) | 0.0% |
| F1 (MMLongBench-Doc definition) | 61.1% |
| Gold page among the sources | 94.1% |
| Gold page among the cited sources | 76.5% |
| First word, median / p90 | 19.5s / 53.4s |
| Full answer, median / p90 | 34.9s / 84.4s |
| Model calls per question | 3.7 |
| Tokens per question | 24112 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 2 (1) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| Figure | 9 | 44.4% |
| Generalized-text | 3 | 100.0% |
| Multi-page | 5 | 0.0% |
| Not answerable | 1 | 0.0% |
| Pure-text | 3 | 66.7% |
| Single-page | 13 | 84.6% |
| Table | 3 | 66.7% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Guidebook | 6 | 33.3% |
| Research report / Introduction | 7 | 57.1% |
| Tutorial/Workshop | 6 | 83.3% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | Response adds an extra mission, not matching the reference answer |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | Provided answer 15 does not match reference answer 19 |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | Provided answer of six exterior photos, which does not match reference answer of 10 |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | Assistant answered 1 but reference answer is 3 |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | Provided answer 7 does not match reference answer 5 |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Assistant answered 7 gestures, which does not match the reference answer of 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | Response does not state the side (right) of the camera indicator |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | Response gives a specific answer while reference says not answerable |

