# Benchmark run 2026-10-14_revision-d_6231730

Commit `6231730`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

Notes: Revision D: retrieval embeds with nomic task prefixes and orders passages by the cross-encoder fused with the hybrid order (the cross-encoder runs on the CPU: on Apple GPUs its memory grew past 30 GB); the sentence check accepts figures computed from figures the answer has just given, and a rewrite keeps such calculations with their inputs; yes/no questions are decided from what the evidence shows or implies (rounded figures match, negated questions are answered as asked). Revision C's test indexes (benchmarks/work/revC) kept; the server re-embedded them with the task prefixes. After the development run the yes/no rule lost a sentence that weakened declines on unanswerable questions and gained the negated-question rule.

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **77.8%** (95% CI 61.9%–88.3%) |
| Wrong answers | 19.4% |
| Declined to answer | 2.8% |
| Gold page among the sources | 91.7% |
| Gold page among the cited sources | 80.6% |
| First word, median / p90 | 13.5s / 20.4s |
| Full answer, median / p90 | 18.8s / 33.8s |
| Model calls per question | 4.3 |
| Tokens per question | 22034 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 4 (2) |
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
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant gave a positive ratio contradicting reference that states ratio is zero due to negative EBIT |
| financebench_id_00705 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? | $400,000,000 increase. | Provided $750M increase, which does not match the reference $400M increase |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | Assistant reports $4.2 billion (or $4.95 billion) instead of the reference $8.4 billion total. |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | Assistant declined to answer, but reference provides a clear yes answer |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Answer omits several legal battle categories mentioned in the reference (pricing and PBM litigation). |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | Provided a different working capital figure and did not match the reference answer. |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | Response gives a generic cost increase reason and omits the specific drivers listed in the reference answer. |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | The answer gives 12.14 times, which does not match the reference 9.5 times |

## MMLongBench-Doc (53 questions)

| Metric | Value |
|---|---|
| Accuracy | **71.7%** (95% CI 58.4%–82.0%) |
| Wrong answers | 24.5% |
| Declined to answer | 3.8% |
| Accuracy on answerable questions | 69.8% |
| Unanswerable questions correctly declined (10) | 80.0% |
| F1 (MMLongBench-Doc definition) | 69.8% |
| Gold page among the sources | 92.9% |
| Gold page among the cited sources | 76.2% |
| First word, median / p90 | 9.3s / 13.9s |
| Full answer, median / p90 | 11.9s / 21.4s |
| Model calls per question | 3.2 |
| Tokens per question | 28294 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 3 (2) |
| Ingestion | 7 documents, 694 chunks; upload 159.1s, background 1802.9s (index built at `991bbaa`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 0.0% |
| Chart | 5 | 80.0% |
| Figure | 22 | 59.1% |
| Generalized-text | 4 | 75.0% |
| Multi-page | 13 | 38.5% |
| Not answerable | 10 | 80.0% |
| Pure-text | 11 | 81.8% |
| Single-page | 30 | 83.3% |
| Table | 6 | 66.7% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 9 | 44.4% |
| Administration/Industry file | 7 | 71.4% |
| Brochure | 7 | 100.0% |
| Financial report | 8 | 87.5% |
| Guidebook | 9 | 55.6% |
| Research report / Introduction | 7 | 71.4% |
| Tutorial/Workshop | 6 | 83.3% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | The response answers with 'Technology Development mission' which does not match the reference answer 'Space Science & P… |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | The assistant answered 9, which does not match the reference answer of 10. |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | The response answers 1, which does not match the reference answer of 3 |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | The assistant answered 7 connectors, which does not match the reference answer of 5. |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Answer gives 7 gestures, does not match reference of 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | Response does not specify the side, failing to match 'on the right' |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | The response provides a specific license code instead of indicating the information is unavailable. |
| mm_0495 | How many times does mobile phone appear on pages 16 and 18? | 6 | Provided answer 0 does not match reference answer 6 |
| mm_0580 | How many websites are present on the cover page? | 2 | Answer given (3) does not match reference answer (2). |
| mm_0582 | How many committee members from Texas are presented in the conference of improving the quality and efficiency… | 1 | The assistant answered 3, which does not match the reference answer of 1 |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | The response does not provide the required answer of 2. |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | Provided answer 6 does not match reference answer 4 |
| mm_0764 | How many strategies outperform the uniform sampling baseline on CIFAR-10-LT? | Not answerable | Response provides an answer while reference indicates the question is not answerable |
| mm_0766 | How many line plots are in this paper? | 3 | Provided answer 15 does not match reference answer 3 |
| mm_0769 | On the dataset map of PathMNIST, does the map by ground truth or pseudo-labels have a larger confidence varia… | ground truth | The response states pseudo‑labels have larger variance, contradicting the reference answer 'ground truth'. |

