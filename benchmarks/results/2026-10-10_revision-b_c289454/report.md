# Benchmark run 2026-10-10_revision-b_c289454

Commit `c289454`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

**Caveat:** Revision B as committed dropped the text of every document it added picture descriptions to (fixed in a3ea0bb and 112af5d): 7 of the 24 FinanceBench filings and all 7 MMLongBench-Doc documents were answered from their picture descriptions alone, so this run measures that bug, not the intended revision.

Notes: Revision B (ingestion), on top of revision A: picture-only pages are read with OCR, pages that are mostly pictures or charts are described by the vision model at ingestion and indexed as passages of their page, and graph batches cut off mid-reply are asked again for the missing chunks. Code at c289454; index rebuilt in benchmarks/work/revB (the baseline/revision A index in benchmarks/work is kept). FinanceBench questions 21-36 were (re)asked on 2026-10-12: the first run of them stalled for two days while the computer slept, which used up each question's time budget (calculation steps skipped) and, with the server's growing graph cache, starved the reranker of memory; those answers were discarded (kept outside the results in benchmarks/work/revB_results_before_redo.jsonl). Same code (c289454) and index.

## MMLongBench-Doc (53 questions)

| Metric | Value |
|---|---|
| Accuracy | **49.1%** (95% CI 36.1%–62.1%) |
| Wrong answers | 30.2% |
| Declined to answer | 20.8% |
| Accuracy on answerable questions | 46.5% |
| Unanswerable questions correctly declined (10) | 60.0% |
| F1 (MMLongBench-Doc definition) | 50.6% |
| Gold page among the sources | 57.1% |
| Gold page among the cited sources | 45.2% |
| First word, median / p90 | 5.2s / 10.7s |
| Full answer, median / p90 | 6.6s / 14.1s |
| Model calls per question | 2.2 |
| Tokens per question | 5767 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 7 documents, 694 chunks; upload 158.7s, background 1772.3s (index built at `c289454`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 0.0% |
| Chart | 5 | 40.0% |
| Figure | 22 | 45.5% |
| Generalized-text | 4 | 50.0% |
| Multi-page | 13 | 7.7% |
| Not answerable | 10 | 60.0% |
| Pure-text | 11 | 45.5% |
| Single-page | 30 | 63.3% |
| Table | 6 | 50.0% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 9 | 22.2% |
| Administration/Industry file | 7 | 42.9% |
| Brochure | 7 | 85.7% |
| Financial report | 8 | 87.5% |
| Guidebook | 9 | 22.2% |
| Research report / Introduction | 7 | 42.9% |
| Tutorial/Workshop | 6 | 50.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0022 | What are the uses of Indian remote sensing satellite constellation? | ['Agricultural Drough', 'Forest Fire', 'Landslides and Eart… | Response does not provide the specific list of uses from the reference answer |
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | Provided extra mission and claimed a tie, not matching the reference answer |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | The response does not commit to the required integer answer |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | The response states zero photos, which does not match the reference answer of 10. |
| mm_0027 | What is the title of module 1? | Basic flat & layered maps | Provided an answer but it does not match the reference title exactly |
| mm_0031 | Which example notebook does module 3 use to show how to create an interactive map? | WikidataMapMakingWorkshop.ipynb | The assistant declined to provide the notebook name, while the reference answer gives a specific notebook. |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | Provided answer 0 contradicts reference answer 3 |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | The response does not provide the required numeric answer of 5. |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | The response does not provide the numeric answer 9, it declines to answer. |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | The response does not provide a definitive answer, while the reference answer is 'on the right'. |
| mm_0464 | How many switches do you need to flip to remove the battery? | 2 | The assistant answered zero switches, which does not match the reference answer of 2. |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | Response gives a specific answer while reference indicates the question is not answerable |
| mm_0468 | Which chemical element in the earphone exceeds the limit requirements stipulated in the GB/T 26572 standard? | Not answerable | The response provides a definitive answer rather than declining, but the reference says the question is not answerable. |
| mm_0469 | How many UltraConnect wireless antennas does this computer have? | 4 | The assistant did not provide the numeric answer 4, instead claimed the information was unavailable. |
| mm_0495 | How many times does mobile phone appear on pages 16 and 18? | 6 | The assistant answered 0 occurrences, which does not match the reference answer of 6 |
| mm_0576 | Since what year has Mr. Kildee been involved with child nutrition? | 1954 | The response declines to provide the year, while the reference answer is 1954. |
| mm_0579 | Is there a signature present on the last page? Directly answer 'yes' or 'no'. | no | The assistant did not provide a yes/no answer, but the reference answer is 'no'. |
| mm_0580 | How many websites are present on the cover page? | 2 | Assistant answered 3 websites, but reference answer is 2 |
| mm_0582 | How many committee members from Texas are presented in the conference of improving the quality and efficiency… | 1 | The assistant answered 0 Texas members, which does not match the reference answer of 1. |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | Response does not commit to a single answer, unlike the reference answer of 2. |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | Response states six strategies outperform, contradicting reference answer of 4 |
| mm_0764 | How many strategies outperform the uniform sampling baseline on CIFAR-10-LT? | Not answerable | The response provides an answer, but the reference indicates the question is not answerable. |
| mm_0765 | What querying criteria yields the worst label diversity generally on all the datasets? | VAAL | The assistant declined to answer, but the reference answer is 'VAAL'. |
| mm_0766 | How many line plots are in this paper? | 3 | Provided answer 22 does not match reference answer 3 |
| mm_0767 | What are the optimizers used in this research? | SGD | The assistant declined to provide an answer, but the reference answer is 'SGD'. |
| mm_0768 | What are the large language models used in this research? | Not answerable | The response provides an answer rather than indicating the information is not available, which does not match the 'Not … |
| mm_0918 | How many employees dose PWC have including Assurance, Consulting, Deals and Tax & Legal Services? | 5100 | Provided employee count (284,000) does not match reference (5,100) |

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **38.9%** (95% CI 24.8%–55.1%) |
| Wrong answers | 13.9% |
| Declined to answer | 47.2% |
| Gold page among the sources | 69.4% |
| Gold page among the cited sources | 50.0% |
| First word, median / p90 | 8.8s / 70.7s |
| Full answer, median / p90 | 11.7s / 97.5s |
| Model calls per question | 3.8 |
| Tokens per question | 8432 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 24 documents, 10574 chunks; upload 1247.6s, background 6942.5s (index built at `c289454`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 12 | 50.0% |
| metrics-generated | 12 | 25.0% |
| novel-generated | 12 | 41.7% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 12 | 41.7% |
| Information extraction | 5 | 60.0% |
| Logical reasoning (based on numerical reasoning) | 2 | 0.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 1 | 100.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 0.0% |
| Numerical reasoning | 11 | 27.3% |
| Numerical reasoning OR Logical reasoning | 3 | 33.3% |
| Numerical reasoning OR information extraction | 1 | 100.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant gave a numeric ratio (4.37) contradicting reference answer of zero |
| financebench_id_00591 | Does Adobe have an improving Free cashflow conversion as of FY2022? | Yes, the FCF conversion (using net income as the denominato… | Assistant says information is not provided, but reference gives a clear yes answer with figures. |
| financebench_id_01487 | Did JnJ's net earnings as a percent of sales increase in Q2 of FY2023 compared to Q2 of FY2022? | Yes, net earnings as a percent of sales increased from 20% … | Assistant declined to answer, but reference provides a specific yes answer with percentages |
| financebench_id_01484 | How did JnJ's US sales growth compare to international sales growth in FY2022? | US sales increased 3.0% vs international sales decline of 0… | Provided figures differ from reference values |
| financebench_id_03882 | What is Amcor's year end FY2020 net AR (in USD millions)? Address the question by adopting the perspective of… | $1616.00 | The assistant declined to provide the net AR figure, but the reference answer contains a specific value. |
| financebench_id_00705 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? | $400,000,000 increase. | Assistant gave $750M increase, which does not match the reference $400M increase |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | The answer gives $4.95 billion, which does not match the reference total of $8.4 billion. |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | The response declined to answer, while the reference provides a clear 'Yes' conclusion. |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Assistant provides a different set of legal matters than the reference answer, missing key areas like pricing and PBM l… |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | Assistant says data unavailable, contradicting reference's positive $1.6 bn answer |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | The assistant declined to provide the drivers, while the reference answer lists specific gross‑margin drivers for FY202… |
| financebench_id_00956 | Are JnJ's FY2022 financials that of a high growth company? | No, JnJ's FY2022 financials are not of a high growth compan… | Assistant declines to answer, but reference provides a definitive 'No'. |
| financebench_id_04080 | When primarily referencing the income statement and the statement of financial position, what is the FY2021 i… | 3.46 | The response declines to provide the ratio, while the reference gives a specific value of 3.46. |
| financebench_id_04660 | Considering the data in the balance sheet, what is Block's (formerly known as Square) FY2016 working capital … | 1.73 | The assistant declined to provide the ratio, while the reference answer gives a specific value of 1.73. |
| financebench_id_10130 | Based on the information provided primarily in the balance sheet and the statement of income, what is FY2020 … | 63.86 | Assistant did not provide the DPO value, while reference answer gives 63.86 |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | The response says inventory data is unavailable, contradicting the reference answer of 9.5 times. |
| financebench_id_10420 | Based on the information provided primarily in the statement of financial position and the statement of incom… | -0.02 | The assistant declined to provide the ROA value, while the reference answer gives -0.02 |
| financebench_id_00299 | Which of JPM's business segments had the lowest net revenue in 2021 Q1? | Corporate. Its net revenue was -$473 million. | Assistant declined to answer, missing the correct segment and figure. |
| financebench_id_03718 | What is Lockheed Martin's 2 year total revenue CAGR from FY2020 to FY2022 (in units of percents and round to … | 0.4% | Assistant declined to provide the CAGR, while reference gives 0.4% |
| financebench_id_05915 | What is the FY2018 fixed asset turnover ratio for CVS Health? Fixed asset turnover ratio is defined as: FY201… | 17.98 | Assistant declined to provide the ratio, while reference gives a numeric answer |
| financebench_id_02987 | What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined … | 24.26 | The response declines to provide the ratio, while the reference gives a specific value |
| financebench_id_07966 | What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard? Answer in unit… | 1.9% | Assistant declined to provide the percentage, but reference answer gives 1.9% |

