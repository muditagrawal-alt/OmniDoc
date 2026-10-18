# Benchmark run 2026-10-18_revision-d_90a7efb

Commit `90a7efb`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

Notes: Revision D on the full MMLongBench-Doc, batch 1 of 10 (every 10th of the 135 documents with its questions; later batches add to this run with --resume). The 7 documents of the test split come from the test index (built at revision C, re-embedded at revision D); the others are ingested by the batches. Code: revision D plus changes that leave MMLongBench answers as they were (query/passage modes for NVIDIA and Jina embeddings, retries of hosted embedding batches, an optional vector weight left at 1, a FinanceBench note on registered securities).

## MMLongBench-Doc (136 questions)

| Metric | Value |
|---|---|
| Accuracy | **55.9%** (95% CI 47.5%–64.0%) |
| Wrong answers | 28.7% |
| Declined to answer | 15.4% |
| Accuracy on answerable questions | 52.9% |
| Unanswerable questions correctly declined (32) | 65.6% |
| F1 (MMLongBench-Doc definition) | 55.6% |
| Gold page among the sources | 88.3% |
| Gold page among the cited sources | 64.1% |
| First word, median / p90 | 9.4s / 20.2s |
| Full answer, median / p90 | 12.4s / 26.1s |
| Model calls per question | 3.5 |
| Tokens per question | 28694 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 11 (5) |
| Ingestion | 18 documents, 1575 chunks; upload 253.8s, background 3621.6s (index built at `991bbaa`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 100.0% |
| Chart | 24 | 50.0% |
| Figure | 26 | 50.0% |
| Generalized-text | 13 | 61.5% |
| Multi-page | 37 | 37.8% |
| Not answerable | 32 | 65.6% |
| Pure-text | 25 | 52.0% |
| Single-page | 67 | 61.2% |
| Table | 33 | 39.4% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 20 | 50.0% |
| Administration/Industry file | 18 | 55.6% |
| Brochure | 8 | 87.5% |
| Financial report | 34 | 50.0% |
| Guidebook | 25 | 36.0% |
| Research report / Introduction | 25 | 72.0% |
| Tutorial/Workshop | 6 | 83.3% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0004 | Among all charts in this report, how many compare between the general public with the Latinos/Hispanics? A fe… | 6 | Provided answer 2 does not match reference answer 6 |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | Provided answer 1 does not match reference answer 3 |
| mm_0125 | in which paragraph and page is the green italic numerals located? | Not answerable | Response provides a specific location, but reference says not answerable |
| mm_0130 | When was the last serious shock recorded in the table? The answer needs to be accurate to the year, month, da… | 1884 April 5, 10 45 a.m. | Provided a specific date/time that does not match the reference answer |
| mm_0199 | Tell me all the pages introducing how to reinstall the software. Your answer should be formatted as a list ab… | ['Page 45', 'Page 49', 'Page 50'] | Provided pages 45 and 47 do not match the reference list of pages 45, 49, and 50 |
| mm_0202 | List all the countries/regions mentioned in the "Regulatory Compliance Information" part of this guidebook (e… | ['Canada', 'Europe', 'Korea', 'Singapore', 'Taiwan', 'China… | The answer misses Canada and China and adds Russia, not matching the reference list. |
| mm_0203 | I'm a Macbook Air user in Mexico. According to this guidebook, which number shall I call for seeking Applecar… | 1-800-275-2273 | The assistant declined to provide the phone number, which does not match the reference answer. |
| mm_0204 | According to this guideline, what is on the left side of the MacBook Air's camera? | Ambient light sensor | Provided answer contradicts reference (says empty instead of ambient light sensor). |
| mm_0206 | Among the adults conducted the survey on April 25 - May 1 2018, how many adults rated Trump's government ethi… | 541 | Provided 872 adults, which does not match reference 541 |
| mm_0208 | According to the survey on April 25 - May 1, 2018, what are the domains with the highest percentage that adul… | ['Make good decisions about economic policy ', 'Make wise d… | Provided answer does not match the reference list |
| mm_0212 | What is the percentage of registered voters who support or lean toward the candidate from the party with the … | 92% | The response declines to provide the percentage, while the reference answer gives 92%. |
| mm_0216 | How many Demoncratic people in the survey of U.S. adults conducted April 25- May 1, 2019 said neither the Rep… | 128 | The response declines to provide a numeric answer, while the reference answer is 128. |
| mm_0366 | What was the value of absolute percentage shortfall in India's GDP growth from 2002 to 2003 compared to the f… | 2.4% | The assistant declined to provide a value, but the reference answer gives 2.4%. |
| mm_0370 | Which executive directors have attended Board Meetings more than 6 times? | Mr. S.V. Shanbhag | Response claims no director attended >6, contradicting reference answer |
| mm_0371 | How many companies do Mr. R.A. Shah, Mr. S.V. Shanbhag, and Mr. C.M. Maniar collectively hold directorships o… | 30 | Answer gave 23 companies, which does not match reference answer of 30 |
| mm_0372 | Who are the non-executive and independent directors of GODFREY PHILLIPS INDIA LIMITED? Enumerate all of them … | ['Mr.R.A.Shah', 'Mr.Lalit Bhasin', 'Mr.Anup N.Kothari', 'Mr… | The answer omitted Mr. R.A. Shah from the list of directors |
| mm_0373 | How much higher was the proposed dividend paid (Rupees in lacs) in 2002 compared to 2001? | 155.98 | Provides a numeric answer but states the dividend was lower, contradicting the reference that it was higher by 155.98 |
| mm_0374 | How much higher was the dividend paid in 2003 compared to 2002? | Not answerable | Response provides a specific dividend figure despite reference indicating not answerable |
| mm_0376 | What were the GDP growth amounts for the third and fourth quarters respectively? | Not answerable | Response provides a partial answer instead of indicating the information is not answerable. |
| mm_0378 | How many figures are there in total in the article? | 6 | Answer gives 2 figures, but reference states 6 |
| mm_0380 | For the year ended March 31,2003, how much less were the shareholders' funds compared to the income in rupees? | 83672770 | The answer provides a numeric value but it is off by a factor of 100 compared to the reference answer |
| mm_0385 | What are the words written in the first rectangle on the top of the page two? | ['strategic priority areas', 'strategies', 'objectives'] | Response gives no answer, only a document version string. |
| mm_0389 | How many people are there in the images on the cover? | 12 | The assistant answered 11 people, which does not match the reference answer of 12. |
| mm_0391 | What is the title of the diagram on page 9? | Leadership, Workforce and Infrastructure | The response declines to provide the title, while the reference answer gives a specific title. |
| mm_0392 | What is the title of the diagram on page 10? | Not answerable | Provided a title instead of declining, but reference indicates the information is not answerable |
| mm_0393 | What are the top2 texts of the red words in the document? | ['LONG,HEALTHY LIFE', 'READINESS FOR EMERGING HEALTH THREAT… | Assistant declined by claiming no red words, but reference provides two specific texts. |
| mm_0396 | How many strengths and weaknesses are metioned in Appendix C? Represent these two numbers as format of list. | ['23', '21'] | Answer numbers [21,13] do not match reference ['23','21] |
| mm_0399 | How many people are there in total in the MQA Executive Leadership and the Prosecution Services Staff? | 7 | Provided total 39, which does not match reference answer 7 |
| mm_0400 | How many people are there in total in the HAQ Executive Leadership? | Not answerable | The response provides an answer (seven people) instead of declining, but the reference says not answerable. |
| mm_0461 | How many connectors are there on the right side view of the computer? | 5 | The assistant answered 7 connectors, which does not match the reference answer of 5 |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Provided answer of 7 gestures does not match reference answer of 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | Response does not specify the side (right) as required |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | Response gives a specific answer while reference says not answerable |
| mm_0486 | What models of wheel are introduced on pages 10 and 11? | Not answerable | The response provides wheel models instead of declining as the reference indicates not answerable |
| mm_0496 | What's the value of the smallest bar in the graph about the percentage of U.S. adults with Hispanic ancestry … | 3 | Provided answer 11% does not match reference answer 3 |
| mm_0497 | What's the average value of all orange bars in the chart about the percentage of U.S. adults with Hispanic an… | 21 | Provided answer 79% does not match reference 21 |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | The response gives answer 4, which does not match reference answer 2 |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | The response does not provide the numeric answer (4) and claims the information is unavailable. |
| mm_0764 | How many strategies outperform the uniform sampling baseline on CIFAR-10-LT? | Not answerable | The assistant gave a numeric answer (6) while the reference indicates the question is not answerable. |
| mm_0766 | How many line plots are in this paper? | 3 | Provided answer 15 does not match reference answer 3 |
| mm_0769 | On the dataset map of PathMNIST, does the map by ground truth or pseudo-labels have a larger confidence varia… | ground truth | The response claims pseudo‑labels have larger variance, contradicting the reference answer 'ground truth'. |
| mm_0890 | How many applications are mentioned in Pages 3-6? | 22 | Answer given (1) does not match reference (22) |
| mm_0892 | According to the overview section, list the buttons of Mi phones | ['Power Button', 'Volume Buttons', 'Menu Buttons', 'Home Bu… | The response declines to provide the list, which does not match the reference answer. |
| mm_0893 | How many icons can be found in Status Bar? | 23 | The response does not provide the numeric answer 23 required. |
| mm_0894 | List all the different icons about networks that can be found in Status Bar | ['Cellular Data Network Connected', '4G Network', 'HSPA+ Ne… | The response does not provide any of the listed network icons. |
| mm_0895 | List all the icons about signals that can not be found in Status Bar | Not answerable | Response provides an answer while reference says not answerable |
| mm_0896 | How many interface layout examples of virtual keypads are shown in Chapter 3 for text input purpose? | 4 | Response does not provide the required numeric answer of 4. |
| mm_0897 | How many steps are needed for editing an SMS? | 4 | The response does not provide an answer, while the reference answer is 4. |
| mm_0898 | What are the last four example websites in the figure of Page 29 | ['Vimeo', 'Linkedin', 'Google+', 'Wikipedia'] | The response declines to provide the list, which does not match the reference answer. |
| mm_0971 | According to the paper, there are five different relation types between two events. | Not answerable | Provided an answer instead of declining, contradicting the 'Not answerable' reference |
| mm_0972 | The authors propose four different solutions for logical reasoning of LLMs. | Not answerable | The response provides an answer instead of indicating the information is not answerable. |
| mm_0973 | Which baseline did the pre-trained Vicuna-13B perform best on MAVEN-ERE? | CoT w. logical constraints | The response omits "CoT" and adds "all", not matching the reference answer |
| mm_1070 | what is the change of Best Buy's gross margins change from FY2022 to FY2021? Answer in percentage terms, roun… | 1.08% | The assistant gave -0.11% change, which does not match the reference answer of 1.08% |
| mm_1072 | what is Return on Capital Employed for the fiscal year ending January 28, 2023? round your answer to three de… | 0.263 | The assistant declined to provide the numeric ROCE value, which does not match the reference answer |
| mm_1073 | what is After-tax Return on Average Equity for the fiscal year ending January 28, 2023? round your answer to … | 0.488 | The response declines to provide the numeric answer, which does not match the reference value of 0.488. |
| mm_1074 | What is Interest to Average Total Debt for the fiscal year ending January 28, 2023? Answer in percentage term… | 2.91% | The assistant declined to provide the percentage, while the reference answer gives 2.91%. |
| mm_1075 | what is capitalization ratio for Best Buy for the fiscal year ending January 28, 2023? Answer in percentage t… | 29.6% | The response declines to provide the ratio, while the reference contains a specific answer (29.6%). |
| mm_1084 | what is interest coverage ratio for AMCOR'FY 2020? round your answer to three decimal? | 51.286 | The assistant did not provide the numeric answer 51.286, instead claimed the information was unavailable. |
| mm_1085 | What is effective tax ratio of Best Buy for for the fiscal year ending January 28, 2023?Answer in percentage … | 20.7% | Provided answer 11.5% does not match reference 20.7% |
| mm_1086 | what is invested capital of Best Buy for for the fiscal year ending January 28, 2023? Answer in million. | 13929 | Response declines to provide the numeric answer, which does not match the reference value of 13929. |

