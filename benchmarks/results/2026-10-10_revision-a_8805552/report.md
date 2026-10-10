# Benchmark run 2026-10-10_revision-a_8805552

Commit `8805552`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

## MMLongBench-Doc (53 questions)

| Metric | Value |
|---|---|
| Accuracy | **47.2%** (95% CI 34.4%–60.3%) |
| Wrong answers | 37.7% |
| Declined to answer | 15.1% |
| Accuracy on answerable questions | 41.9% |
| Unanswerable questions correctly declined (10) | 70.0% |
| F1 (MMLongBench-Doc definition) | 44.4% |
| Gold page among the sources | 69.0% |
| Gold page among the cited sources | 52.4% |
| First word, median / p90 | 5.7s / 39.7s |
| Full answer, median / p90 | 7.8s / 64.2s |
| Model calls per question | 2.1 |
| Tokens per question | 4198 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 7 documents, 596 chunks; upload 61.3s, background 1471.8s (index built at `fb1d133`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 0.0% |
| Chart | 5 | 20.0% |
| Figure | 22 | 27.3% |
| Generalized-text | 4 | 50.0% |
| Multi-page | 13 | 15.4% |
| Not answerable | 10 | 70.0% |
| Pure-text | 11 | 72.7% |
| Single-page | 30 | 53.3% |
| Table | 6 | 66.7% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 9 | 44.4% |
| Administration/Industry file | 7 | 57.1% |
| Brochure | 7 | 71.4% |
| Financial report | 8 | 50.0% |
| Guidebook | 9 | 22.2% |
| Research report / Introduction | 7 | 57.1% |
| Tutorial/Workshop | 6 | 33.3% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | The answer given does not match the reference answer |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | Provided answer 4 does not match reference answer 19 |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | Response says zero photos, which does not match reference answer of 10 |
| mm_0027 | What is the title of module 1? | Basic flat & layered maps | Provides a different, overly detailed title not matching the reference |
| mm_0030 | What is the color of the zone Mali in the map used to demonstrate GeoShapes using SPARQL and OSM? | purple | Response declines to answer, but reference answer is 'purple'. |
| mm_0031 | Which example notebook does module 3 use to show how to create an interactive map? | WikidataMapMakingWorkshop.ipynb | The assistant declined to provide the notebook name, while the reference answer gives a specific notebook. |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | The assistant answered 0 images, which does not match the reference answer of 3 |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | Assistant states 7 connectors, which does not match reference answer of 5 |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Provided answer 6 does not match reference answer 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | The assistant declined to answer, but the reference answer provides 'on the right'. |
| mm_0464 | How many switches do you need to flip to remove the battery? | 2 | The assistant answered 0 switches, which does not match the reference answer of 2. |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | The response provides a specific answer instead of indicating the information is unavailable. |
| mm_0467 | Which chemical element in the hard disk exceeds the limit requirements stipulated in the GB/T 26572 standard? | Pb | The response declines to answer, but the reference answer is 'Pb'. |
| mm_0468 | Which chemical element in the earphone exceeds the limit requirements stipulated in the GB/T 26572 standard? | Not answerable | Response provides a definitive answer, not a decline, while reference is not answerable |
| mm_0490 | What percentage of users are under 35? | 86% | Assistant declined to provide the percentage, but reference answer gives 86% |
| mm_0492 | How many triangles appear on the eighth side? | 4 | The response does not provide the required numeric answer (4) and instead claims the information is unavailable. |
| mm_0494 | Compared with 22Q1, in 23Q1, how much higher is the increase rate of number of daily average active content c… | 5% | Provided answer does not match the reference value of 5% |
| mm_0495 | How many times does mobile phone appear on pages 16 and 18? | 6 | Provided answer 0 contradicts reference answer 6 |
| mm_0579 | Is there a signature present on the last page? Directly answer 'yes' or 'no'. | no | The response does not provide a yes/no answer, unlike the reference 'no' |
| mm_0580 | How many websites are present on the cover page? | 2 | Provided answer of three websites, which does not match reference answer of 2 |
| mm_0581 | What page has an eight-pointed snowflake image? Give me an integer. | 1 | The assistant answered 8, which does not match the reference answer of 1 |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | Provided answer 3 does not match reference answer 2 |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | Provided answer 2 does not match reference answer 4 |
| mm_0764 | How many strategies outperform the uniform sampling baseline on CIFAR-10-LT? | Not answerable | Response provides an answer (five strategies) while reference indicates the question is not answerable |
| mm_0765 | What querying criteria yields the worst label diversity generally on all the datasets? | VAAL | The response answers 'Random querying' instead of the reference answer 'VAAL' |
| mm_0766 | How many line plots are in this paper? | 3 | Answer 38 does not match reference answer 3 |
| mm_0916 | How many employees dose PWC Assurance have? | 1914 | The response does not provide the numeric answer 1914, instead claims the information is unavailable. |
| mm_0918 | How many employees dose PWC have including Assurance, Consulting, Deals and Tax & Legal Services? | 5100 | Provided a figure (284,000) that does not match the reference answer of 5,100 |

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **50.0%** (95% CI 34.5%–65.5%) |
| Wrong answers | 16.7% |
| Declined to answer | 33.3% |
| Gold page among the sources | 75.0% |
| Gold page among the cited sources | 47.2% |
| First word, median / p90 | 14.9s / 67.3s |
| Full answer, median / p90 | 37.3s / 99.4s |
| Model calls per question | 3.9 |
| Tokens per question | 9507 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 24 documents, 10575 chunks; upload 1104.5s, background 5124.3s (index built at `fb1d133`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 12 | 41.7% |
| metrics-generated | 12 | 50.0% |
| novel-generated | 12 | 58.3% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 12 | 58.3% |
| Information extraction | 5 | 60.0% |
| Logical reasoning (based on numerical reasoning) | 2 | 50.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 1 | 100.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 0.0% |
| Numerical reasoning | 11 | 54.5% |
| Numerical reasoning OR Logical reasoning | 3 | 0.0% |
| Numerical reasoning OR information extraction | 1 | 0.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant provided a non-zero ratio contradicting the reference that it should be zero |
| financebench_id_00438 | Does Adobe have an improving operating margin profile as of FY2022? If operating margin is not a useful metri… | No the operating margins of Adobe have recently declined fr… | Assistant did not state whether margin improved, so it declined, which does not match the reference answer. |
| financebench_id_00591 | Does Adobe have an improving Free cashflow conversion as of FY2022? | Yes, the FCF conversion (using net income as the denominato… | Assistant did not commit to the yes answer and provided no conversion figures |
| financebench_id_01487 | Did JnJ's net earnings as a percent of sales increase in Q2 of FY2023 compared to Q2 of FY2022? | Yes, net earnings as a percent of sales increased from 20% … | Assistant says information unavailable, but reference provides a specific yes answer with percentages. |
| financebench_id_01484 | How did JnJ's US sales growth compare to international sales growth in FY2022? | US sales increased 3.0% vs international sales decline of 0… | Provided figures (2.9% and -11.5%) do not match reference (3.0% and -0.6%). |
| financebench_id_03882 | What is Amcor's year end FY2020 net AR (in USD millions)? Address the question by adopting the perspective of… | $1616.00 | Assistant declined to provide the net AR figure, but reference answer gives $1616 million. |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | Assistant did not provide the combined total $8.4 billion, stating the documents lack a combined figure. |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | Assistant answered 'not capital‑intensive', contradicting the reference's 'yes' |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Answer omits key legal battle areas mentioned in reference |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | The response does not provide the required answer, while the reference gives a positive working capital figure. |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | The assistant declined to answer, but the reference provides specific drivers of gross margin change. |
| financebench_id_00711 | Roughly how many times has JnJ sold its inventory in FY2022? Calculate inventory turnover ratio for FY2022; i… | JnJ sold its inventory 2.7 times in FY2022. | The answer gives 2.49 times, which does not match the reference value of 2.7 times. |
| financebench_id_04080 | When primarily referencing the income statement and the statement of financial position, what is the FY2021 i… | 3.46 | The response declines to provide the ratio, while the reference gives a specific value of 3.46. |
| financebench_id_10130 | Based on the information provided primarily in the balance sheet and the statement of income, what is FY2020 … | 63.86 | Assistant declined to provide the DPO value, while reference gives 63.86 |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | Provided inventory turnover of 11.96 times, which does not match reference 9.5 times |
| financebench_id_05915 | What is the FY2018 fixed asset turnover ratio for CVS Health? Fixed asset turnover ratio is defined as: FY201… | 17.98 | Assistant declined to provide a numeric answer, but reference gives 17.98 |
| financebench_id_02987 | What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined … | 24.26 | The response declines to provide the ratio, while the reference gives a specific value of 24.26. |
| financebench_id_07966 | What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard? Answer in unit… | 1.9% | The assistant declined to provide the 1.9% answer, while the reference contains a specific value. |

