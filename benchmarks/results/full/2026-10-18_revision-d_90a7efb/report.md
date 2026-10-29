# Benchmark run 2026-10-18_revision-d_90a7efb

Commit `90a7efb`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

Notes: Revision D on the full MMLongBench-Doc, batch 1 of 10 (every 10th of the 135 documents with its questions; later batches add to this run with --resume). The 7 documents of the test split come from the test index (built at revision C, re-embedded at revision D); the others are ingested by the batches. Code: revision D plus changes that leave MMLongBench answers as they were (query/passage modes for NVIDIA and Jina embeddings, retries of hosted embedding batches, an optional vector weight left at 1, a FinanceBench note on registered securities).

## MMLongBench-Doc (255 questions)

| Metric | Value |
|---|---|
| Accuracy | **57.3%** (95% CI 51.1%–63.2%) |
| Wrong answers | 31.0% |
| Declined to answer | 11.8% |
| Accuracy on answerable questions | 56.1% |
| Unanswerable questions correctly declined (57) | 61.4% |
| F1 (MMLongBench-Doc definition) | 57.2% |
| Gold page among the sources | 90.8% |
| Gold page among the cited sources | 68.4% |
| First word, median / p90 | 11.1s / 32.3s |
| Full answer, median / p90 | 15.4s / 40.5s |
| Model calls per question | 3.5 |
| Tokens per question | 29781 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 23 (8) |
| Left out | 9 questions on mi_phone.pdf: the downloaded file is another document (NYU_graduate.pdf) |
| Ingestion | 31 documents, 3190 chunks; upload 525.1s, background 4478.8s (index built at `991bbaa`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 4 | 100.0% |
| Chart | 34 | 52.9% |
| Figure | 63 | 52.4% |
| Generalized-text | 20 | 55.0% |
| Multi-page | 78 | 38.5% |
| Not answerable | 57 | 61.4% |
| Pure-text | 54 | 59.3% |
| Single-page | 120 | 67.5% |
| Table | 67 | 52.2% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 61 | 54.1% |
| Administration/Industry file | 25 | 56.0% |
| Brochure | 14 | 64.3% |
| Financial report | 46 | 54.3% |
| Guidebook | 21 | 52.4% |
| Research report / Introduction | 62 | 62.9% |
| Tutorial/Workshop | 26 | 57.7% |

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
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | Response gives a different answer than the reference mission |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | The response answers 15, which does not match the reference answer of 19 |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | Provided answer 8 does not match reference answer 10 |
| mm_0035 | How many pages include charts whose horizontal-axis are set as year (like 2024)? | 13 | Provided answer 5 pages, which does not match reference answer 13 |
| mm_0039 | In the slides, how many charts compare between ONLY US and Europe? | 10 | Provided answer 8 does not match reference answer 10 |
| mm_0041 | On the chart showing average exit cap, there is one point that US, Europe, and China have the same average ex… | 300 million | The response does not provide the required numeric answer, thus it declines and does not match the reference answer. |
| mm_0179 | How many samples in MMMU belong to sociology subject? | 287 | Response declines to provide the number, while reference answer is 287 |
| mm_0180 | Among all samples belonging to 'Public Health' subject, how many percentage samples showcased in this paper? … | 0.55% | Answer provided but value 0.5894% does not match reference 0.55% |
| mm_0183 | According to this paper, What's the GPT-4V's performance difference between CS subject and math subject on MM… | 12.1% | Assistant declined to provide the 12.1% figure required |
| mm_0219 | How many people who do not go online or only use SNS in the Older Adults and Technology by Princeton Survey R… | 4087 | Provided number 1,038 does not match reference answer 4087 |
| mm_0220 | How many people who do not go online or only use SNS in the Older Adults and Technology by Princeton Survey R… | Not answerable | Response provides a specific number instead of indicating the information is not answerable, contradicting the referenc… |
| mm_0224 | Among the Higher-income seniors, what are the percentage of them go online, has smartphone phone, and own a t… | Not answerable | The assistant provided specific percentages instead of indicating the information is not answerable. |
| mm_0225 | How many 65+ age group people go online 3-5 times per week or Every day in the Pew Research Center’s Internet… | 1251 | Response declines to provide a numeric answer, but reference answer gives 1251. |
| mm_0227 | What is the gap of 65+ people with College graduate contain a cell phone and a tablet computer in the Pew Res… | 301 | The assistant gave 56 percentage points, which does not match the reference answer of 301 |
| mm_0228 | What is the gap of infants with College graduate contain a cell phone and a tablet computer in the Pew Resear… | Not answerable | The response provides a specific answer instead of indicating the information is not answerable. |
| mm_0229 | What is the gap between male 65+ age group who use internet and broadband at home in the Pew Research Center’… | 73.0 | Provided answer 12.0 does not match reference 73.0 |
| mm_0233 | Who Visited the U.S. Naval Medical Research centre on November 29, 2020? | Not answerable | The response provides a specific visitor despite the reference indicating the question is not answerable. |
| mm_0235 | Among all the pictures, how many of them contain only one person? | 6 | Provided answer 3 does not match reference 6 |
| mm_0236 | Among all the pictures, in which page the picture contains the most number of people? Give me the page no. as… | 9 | The assistant answered 4, which does not match the reference answer 9. |
| mm_0237 | What date is mentioned on the second page? Format the date as YYYY-MM | 2009-07 | The response does not provide the required date answer. |
| mm_0241 | How many pages does websites address appeared? List all the pages in list format, for example ["p1","p2"] | ['p4', 'p7', 'p9'] | Provided list of pages does not match the reference list ['p4','p7','p9] |
| mm_0294 | What are the personality scores of the data sample with extreme personality cases, in which the personality v… | ['71.02', '75.38'] | Provided extra values beyond the reference list, not matching the expected answer |
| mm_0295 | What is the highest hit rate number in the dataset for the personality located furthest to the left in the di… | 0.833 | Provided answer 0.977 does not match reference 0.833 |
| mm_0296 | What is the evaluation metric that has highest number for the method located at the bottom of the model struc… | H@10 | Response gave '# of ratings [11]' which does not match the reference answer 'H@10'. |
| mm_0424 | What is in the overlap area between Danger Zone and Machine Learning? | Not answerable | The assistant provided an answer (Data Science) while the reference indicates the question is not answerable. |
| mm_0426 | What types of animals appear in the PPT? | ['Dog', 'Cat', 'Bear'] | Missing Bear from the list of animals |
| mm_0428 | Which three deep learning conspirators appear in the PPT? | ['Bengio', 'Hinton', 'LeCun'] | The response does not provide the three names, it claims the information is unavailable. |
| mm_0430 | How many times does the image of a tiger appear in the PPT? | 0 | Response declines without providing the answer |
| mm_0431 | How many layers does the neural network mentioned in the PPT for distinguishing faces have? | 5 | The response does not provide the answer (5) required by the reference. |
| mm_0433 | Which animal did the detector ultimately recognize the person as? | Dog | Response does not provide the answer 'Dog' required by the reference. |
| mm_0434 | Which dataset was introduced in the 'coding time' section of the PPT for training? | Cat vs Dog dataset | The response does not provide the required answer 'Cat vs Dog dataset'. |
| mm_0435 | How many libraries were imported in the code section of the PPT? | 9 | The response does not provide the number of imported libraries, contrary to the reference answer of 9. |
| mm_0450 | How many GPT-4o examples are listed in the paper? | Not answerable | Response provides an answer (zero) instead of declining, but reference says not answerable |
| mm_0451 | In the 4-shot classification task, how much higher is the top-5 average accuracy of RAR (LLaVA1.5) compared t… | 18.9% | Provided answer 12.3% does not match reference 18.9% |
| mm_0452 | In the visualization of the ranking examples and ranking prompt examples, how many images appear in total? | 8 | The assistant answered 7 images, which does not match the reference answer of 8 |
| mm_0534 | Which of the following company logos do not appear in the slides? Facebook, AWS, Cargo and Manta. | AWS | Assistant says no logos are absent, contradicting reference answer that AWS does not appear |
| mm_0538 | What is the Top-Level Page name of the page with the slowest page processing time? | /video/videocat/video9201 | Provided answer " / " does not match reference "/video/videocat/video9201" |
| mm_0558 | If I want to use the detector in the paper `SOLO: Segmenting Objects by Locations`, what is the implemented c… | DecoupledSOLOHead | Provided answer SOLOHead does not match reference DecoupledSOLOHead |
| mm_0560 | How many data preparation operators in the classical pipeline? | 8 | Provided answer of 7 operators does not match reference answer of 8 |
| mm_0644 | Among the three generation strategies: training-time generation, generation-time generation, and post-hoc gen… | Not answerable | The reference says not answerable, but the response provides a specific answer |
| mm_0646 | How many strategies are plotted for training-time generation, generation-time generation, and post-hoc genera… | Not answerable | The assistant provided specific numbers instead of indicating the information is not answerable. |
| mm_0649 | For all the papers that are listed in Table 1 and Table 2, how many of them are proposed in 2021? | 1 | Provided answer 4 does not match reference answer 1 |
| mm_0650 | Does Section 3.3 cite more papers than Section 3.1? Directly answer 'yes' or 'no'. | Yes | The assistant answered 'No' while the reference answer is 'Yes'. |
| mm_0795 | What is the Account No. of Account 7 in the portfolio overview example? | ILF0000808 | Response declines to provide the account number, which does not match the reference answer. |
| mm_0796 | What is the Account No. of Account 6 in the portfolio overview example? | Not answerable | The assistant provided a specific account number despite the reference indicating the question is not answerable |
| mm_0797 | What are the currencies shown in Multiple settlement options? | ['US Dollar', 'Euro', 'Pound'] | Missing US Dollar from the list of currencies |
| mm_0798 | How many images are shown in the section of trading capabilities? | 6 | Assistant answered 3 images, which does not match the reference answer of 6 |
| mm_0822 | What are the counties mentioned in the document? | ['Hamilton', 'Lucas', 'Murphy', 'York', 'Aurora'] | Response lists only Hamilton, York, and Lucas, missing Murphy and Aurora |
| mm_0865 | How many different icon are shown as different image types in Figure 1? | 17 | Provided answer (30) does not match reference answer (17) |
| mm_0866 | How many different icon are shown as different Disciplines in Figure 10 ? | Not answerable | The response provides an answer (2) while the reference says the question is not answerable. |
| mm_0867 | How many charts are included in Pages 5-10? | 4 | Provided answer 3 does not match reference answer 4 |
| mm_0868 | How many tables are included in Pages 105-110? | Not answerable | Provided an answer (0 tables) instead of declining as required by the reference. |
| mm_0870 | According to this paper, among nice different datasets in Fig 4, which one can reflect the highest efficiency? | Not answerable | The response provides a specific dataset answer, but the reference indicates the question is not answerable. |
| mm_1029 | what is the FY2015 unadjusted EBITDA % margin for Netflix?Answer in percentage term, round to one decimal pla… | 5.4% | The assistant declined to provide the required percentage, which does not match the reference answer of 5.4%. |
| mm_1031 | What is sales to working capital ratio of Neflix in FY 2015?Round your answer to two decimal places. | 3.56 | The assistant declined to provide a numeric answer, but the reference answer gives 3.56. |
| mm_1032 | What amount did personnel-related costs increase for Netfilx in 2015? Answer in millions. | 253.3 | Answer given (133.2) does not match reference (253.3) |
| mm_1036 | what is sales to stockholder equity ratio of Neflix in FY 2015? Round your answer to three decimal places. | 3.049 | The assistant declined to provide the numeric ratio, which does not match the reference answer of 3.049. |

