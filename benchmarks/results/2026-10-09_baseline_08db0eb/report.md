# Benchmark run 2026-10-09_baseline_08db0eb

Commit `08db0eb`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

## MMLongBench-Doc (53 questions)

| Metric | Value |
|---|---|
| Accuracy | **35.8%** (95% CI 24.3%–49.3%) |
| Wrong answers | 30.2% |
| Declined to answer | 34.0% |
| Accuracy on answerable questions | 23.3% |
| Unanswerable questions correctly declined (10) | 90.0% |
| F1 (MMLongBench-Doc definition) | 29.0% |
| Gold page among the sources | 57.1% |
| Gold page among the cited sources | 45.2% |
| First word, median / p90 | 2.0s / 4.6s |
| Full answer, median / p90 | 3.8s / 6.8s |
| Model calls per question | 2.2 |
| Tokens per question | 4241 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 4 |
| Ingestion | 7 documents, 596 chunks; upload 61.3s, background 1471.8s (index built at `fb1d133`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 0.0% |
| Chart | 5 | 20.0% |
| Figure | 22 | 4.5% |
| Generalized-text | 4 | 25.0% |
| Multi-page | 13 | 15.4% |
| Not answerable | 10 | 90.0% |
| Pure-text | 11 | 45.5% |
| Single-page | 30 | 26.7% |
| Table | 6 | 50.0% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 9 | 44.4% |
| Administration/Industry file | 7 | 42.9% |
| Brochure | 7 | 42.9% |
| Financial report | 8 | 37.5% |
| Guidebook | 9 | 33.3% |
| Research report / Introduction | 7 | 42.9% |
| Tutorial/Workshop | 6 | 0.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0020 | What does the map in the report shows? | The centres of Indian Space Programme | The response declines to answer, but the reference provides a specific answer |
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | The assistant declined to provide the answer, while the reference gives a specific mission. |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | Provided answer 3 does not match reference answer 19 |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | Provided answer 2 does not match reference answer 10 |
| mm_0027 | What is the title of module 1? | Basic flat & layered maps | The provided title does not match the reference answer |
| mm_0028 | What is the web address in the orange box in page 47 that gives the Wiki Query Service code? | https://w.wiki/6gb | The response declines to provide the URL, which does not match the reference answer. |
| mm_0029 | What is the sum of the files size of the 2 files with the smallest file size in the table on page 98? | 9259 | Provided answer 2022 KB does not match reference 9259 |
| mm_0030 | What is the color of the zone Mali in the map used to demonstrate GeoShapes using SPARQL and OSM? | purple | The assistant declined to provide the color, but the reference answer is 'purple'. |
| mm_0031 | Which example notebook does module 3 use to show how to create an interactive map? | WikidataMapMakingWorkshop.ipynb | Response does not provide the notebook name required. |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | Provided answer 0 does not match reference answer 3 |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | The assistant answered 7 connectors, which does not match the reference answer of 5. |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Provided answer of six gestures does not match reference answer of 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | Assistant declined to answer while reference provides a specific answer |
| mm_0464 | How many switches do you need to flip to remove the battery? | 2 | The response answers 0 switches, which does not match the reference answer of 2. |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | The response provides an answer despite reference being not answerable |
| mm_0467 | Which chemical element in the hard disk exceeds the limit requirements stipulated in the GB/T 26572 standard? | Pb | The response declines to answer, but the reference answer is 'Pb'. |
| mm_0490 | What percentage of users are under 35? | 86% | Assistant declined to provide the percentage, while reference gives 86% |
| mm_0492 | How many triangles appear on the eighth side? | 4 | Response declines to answer, but reference provides a specific answer (4). |
| mm_0493 | What animals appear on page nine? Enumerate them in a list. | ['dog', 'cat'] | The assistant declined to provide the listed animals, which does not match the reference answer |
| mm_0494 | Compared with 22Q1, in 23Q1, how much higher is the increase rate of number of daily average active content c… | 5% | The response gives a different value (-13.81%) instead of the expected 5%. |
| mm_0495 | How many times does mobile phone appear on pages 16 and 18? | 6 | The assistant did not provide the numeric answer 6, instead claimed no information available. |
| mm_0578 | What date is mentioned at the beginning of page(1)? Format the date as YYYY-MM-DD | 2003-10-07 | The response does not provide the required date, contrary to the reference answer |
| mm_0579 | Is there a signature present on the last page? Directly answer 'yes' or 'no'. | no | The response does not provide a yes/no answer, it declines to answer. |
| mm_0580 | How many websites are present on the cover page? | 2 | The response declined to answer, but the reference answer provides a specific number (2). |
| mm_0581 | What page has an eight-pointed snowflake image? Give me an integer. | 1 | The assistant did not provide the integer answer required. |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | The response gives '1' (with extra text) which does not match the reference answer of 2. |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | The response states 1 strategy, which does not match the reference answer of 4. |
| mm_0765 | What querying criteria yields the worst label diversity generally on all the datasets? | VAAL | The response answers with BALD, which does not match the reference answer VAAL. |
| mm_0766 | How many line plots are in this paper? | 3 | Provided answer (4) does not match reference answer (3) |
| mm_0769 | On the dataset map of PathMNIST, does the map by ground truth or pseudo-labels have a larger confidence varia… | ground truth | Assistant declined to give the answer, but reference answer is 'ground truth' |
| mm_0916 | How many employees dose PWC Assurance have? | 1914 | The assistant declined to provide a number, while the reference answer gives 1914. |
| mm_0918 | How many employees dose PWC have including Assurance, Consulting, Deals and Tax & Legal Services? | 5100 | Provided number 284,000 does not match reference 5100 |
| mm_0919 | Who is Ibrahim? | Core Assurance | Response does not provide the answer "Core Assurance" and says information is unavailable. |
| mm_0921 | How many ways to connect with pwc people? | 6 | Provided answer of 4 methods does not match reference answer of 6 |

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **30.6%** (95% CI 18.0%–46.9%) |
| Wrong answers | 16.7% |
| Declined to answer | 52.8% |
| Gold page among the sources | 55.6% |
| Gold page among the cited sources | 30.6% |
| First word, median / p90 | 7.9s / 16.5s |
| Full answer, median / p90 | 11.1s / 20.4s |
| Model calls per question | 2.9 |
| Tokens per question | 6805 |
| Answers with errors | 1 |
| Answers that needed a retry (rate limit or model error) | 27 |
| Ingestion | 24 documents, 10575 chunks; upload 1104.5s, background 5124.3s (index built at `fb1d133`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 12 | 25.0% |
| metrics-generated | 12 | 16.7% |
| novel-generated | 12 | 50.0% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 12 | 50.0% |
| Information extraction | 5 | 40.0% |
| Logical reasoning (based on numerical reasoning) | 2 | 50.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 1 | 0.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 0.0% |
| Numerical reasoning | 11 | 18.2% |
| Numerical reasoning OR Logical reasoning | 3 | 0.0% |
| Numerical reasoning OR information extraction | 1 | 0.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_03856 | What is the FY2017 operating cash flow ratio for Adobe? Operating cash flow ratio is defined as: cash from op… | 0.83 | The response declines to provide the ratio, while the reference answer gives a specific value of 0.83. |
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Provided a non-zero ratio that contradicts the reference answer of zero |
| financebench_id_01163 | Among operations, investing, and financing activities, which brought in the most (or lost the least) cash flo… | Among the three, cash flow from operations was the highest … | Assistant claims investing activities had the highest cash flow, contradicting reference that operations were highest |
| financebench_id_00438 | Does Adobe have an improving operating margin profile as of FY2022? If operating margin is not a useful metri… | No the operating margins of Adobe have recently declined fr… | The assistant declined to answer, but the reference provides a specific decline in operating margin. |
| financebench_id_00591 | Does Adobe have an improving Free cashflow conversion as of FY2022? | Yes, the FCF conversion (using net income as the denominato… | The assistant says the information is unavailable, while the reference provides a clear yes answer with figures. |
| financebench_id_00651 | Is growth in JnJ's adjusted EPS expected to accelerate in FY2023? | No, rate of growth in adjusted EPS is expected to decelerat… | Assistant claims growth is comparable or marginally higher, contradicting reference that it will decelerate slightly |
| financebench_id_01484 | How did JnJ's US sales growth compare to international sales growth in FY2022? | US sales increased 3.0% vs international sales decline of 0… | Provided figures differ from reference values (2.9% vs 3.0% and -11.5% vs -0.6%). |
| financebench_id_03882 | What is Amcor's year end FY2020 net AR (in USD millions)? Address the question by adopting the perspective of… | $1616.00 | The response declines to provide the net AR value, while the reference gives a specific figure of $1616.00. |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | Assistant declined to provide the $8.4 billion total, contradicting the reference answer. |
| financebench_id_00206 | Are JPM's gross margins historically consistent (not fluctuating more than roughly 2% each year)? If gross ma… | Since JPM is a financial institution, gross margin is not a… | Response declines to answer, while reference states gross margin is not relevant |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | Assistant declined to answer, but reference provides a clear yes answer |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Assistant claims no other material legal battles, contradicting reference's Yes answer |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | Assistant did not provide the positive working capital answer given in the reference. |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | The assistant declined to answer, but the reference provides specific drivers of gross margin change. |
| financebench_id_00711 | Roughly how many times has JnJ sold its inventory in FY2022? Calculate inventory turnover ratio for FY2022; i… | JnJ sold its inventory 2.7 times in FY2022. | no answer (pipeline error: Error during synthesis: No language model could answer: NVIDIA NIM: cooling down for 29s; NV… |
| financebench_id_04080 | When primarily referencing the income statement and the statement of financial position, what is the FY2021 i… | 3.46 | The answer provided (1.15) does not match the reference value (3.46). |
| financebench_id_04700 | What is the FY2016 COGS for Microsoft? Please state answer in USD millions. Provide a response to the questio… | $32780.00 | The response declines to provide the FY2016 COGS, while the reference contains a specific value |
| financebench_id_10130 | Based on the information provided primarily in the balance sheet and the statement of income, what is FY2020 … | 63.86 | The assistant declined to provide a DPO value, while the reference answer gives 63.86. |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | The response says information is unavailable, whereas the reference provides a specific turnover of 9.5 times. |
| financebench_id_10420 | Based on the information provided primarily in the statement of financial position and the statement of incom… | -0.02 | Assistant declined to provide ROA, but reference gives -0.02 |
| financebench_id_00299 | Which of JPM's business segments had the lowest net revenue in 2021 Q1? | Corporate. Its net revenue was -$473 million. | The response declined to answer, but the reference provides a specific answer. |
| financebench_id_03718 | What is Lockheed Martin's 2 year total revenue CAGR from FY2020 to FY2022 (in units of percents and round to … | 0.4% | The assistant declined to provide the CAGR, while the reference answer gives 0.4%. |
| financebench_id_05915 | What is the FY2018 fixed asset turnover ratio for CVS Health? Fixed asset turnover ratio is defined as: FY201… | 17.98 | The response declined to provide the ratio, while the reference answer gives a specific value (17.98). |
| financebench_id_02987 | What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined … | 24.26 | The response declines to provide the ratio, while the reference gives a specific value of 24.26. |
| financebench_id_07966 | What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard? Answer in unit… | 1.9% | The response declines to provide the percentage, while the reference answer gives 1.9%. |

