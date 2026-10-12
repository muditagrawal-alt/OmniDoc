# Benchmark run 2026-10-13_revision-c_991bbaa

Commit `991bbaa`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

Notes: Revision C, on top of revision B with its indexing bug fixed (picture descriptions now join a document's text instead of replacing it). Evidence: retrieval hands on 10 passages (was 6); the financial statements a question needs and the pages it names are given whole and always kept by evidence selection (the reranker scores pages of numbers low); statements come from the page window where the three primary statements sit together, not from five-year summaries, and are also fetched for cash, leverage and return ratios; passages may be 2,400 characters (whole pages 7,000). Finance: a filing's names for the line items a question uses are searched too (net AR = trade receivables, COGS = cost of sales...), and the writer and the calculation step get the standard definitions of the metrics the question names. Writer: computes from the figures in the evidence instead of declining, answers yes/no and how-many questions first, says the documents lack a thing (not "none") when the evidence is silent, and is told which names in the question appear nowhere in the document. Vision: a hosted model reads the candidate pages together and answers from them; PDFs of up to 50 pages are read whole, at full resolution, for every question; questions about the whole document (how many photos, which page) scan every page. Robustness and speed: the graph database's cache is capped at 512 MB (it grew to 33 GB), the reranker moves to the CPU when the GPU runs out of memory, a per-minute quota no longer pauses a provider for an hour, page descriptions are paced, and a document's graph batches are asked three at a time. Index rebuilt in benchmarks/work/revC. During indexing one knowledge-graph batch of the MMLongBench-Doc report fdac8d1e... timed out on NVIDIA twice, so 4 of its 40 graph passages have no entities (its text was indexed in full).

## MMLongBench-Doc (53 questions)

| Metric | Value |
|---|---|
| Accuracy | **64.2%** (95% CI 50.7%–75.7%) |
| Wrong answers | 30.2% |
| Declined to answer | 5.7% |
| Accuracy on answerable questions | 62.8% |
| Unanswerable questions correctly declined (10) | 70.0% |
| F1 (MMLongBench-Doc definition) | 62.8% |
| Gold page among the sources | 95.2% |
| Gold page among the cited sources | 73.8% |
| First word, median / p90 | 9.7s / 15.3s |
| Full answer, median / p90 | 11.2s / 18.9s |
| Model calls per question | 3.2 |
| Tokens per question | 28559 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 7 documents, 694 chunks; upload 159.1s, background 1802.9s (index built at `991bbaa`) |

**By evidence**

| Group | Questions | Accuracy |
|---|---|---|
| (unspecified) | 1 | 0.0% |
| Chart | 5 | 60.0% |
| Figure | 22 | 59.1% |
| Generalized-text | 4 | 50.0% |
| Multi-page | 13 | 23.1% |
| Not answerable | 10 | 70.0% |
| Pure-text | 11 | 72.7% |
| Single-page | 30 | 80.0% |
| Table | 6 | 66.7% |

**By document type**

| Group | Questions | Accuracy |
|---|---|---|
| Academic paper | 9 | 33.3% |
| Administration/Industry file | 7 | 57.1% |
| Brochure | 7 | 100.0% |
| Financial report | 8 | 87.5% |
| Guidebook | 9 | 55.6% |
| Research report / Introduction | 7 | 57.1% |
| Tutorial/Workshop | 6 | 66.7% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| mm_0024 | Of the four missions of Indian Space Program's space mission from 2012 to 2017, which mission includes the la… | Space Science & Planetary Exploration Satellites. | Response adds an extra mission, not matching the reference answer |
| mm_0025 | How many organisations does this report introduce in detail (at least one paragraph) ? | 19 | The response does not provide the required numeric answer, while the reference answer is 19. |
| mm_0026 | How many exterior photos of organisations does this report provide? | 10 | The assistant answered 8, which does not match the reference answer of 10 |
| mm_0027 | What is the title of module 1? | Basic flat & layered maps | The answer omits the '&' and does not exactly match the reference title |
| mm_0032 | How many distinct Netherlands location images does this slide use as examples? | 3 | Provided answer 1 does not match reference answer 3 |
| mm_0462 | How many trackpad gestures does this computer have? | 9 | Provided answer of 7 gestures does not match reference answer of 9 |
| mm_0463 | Which side of the camera indicator is on the infrared camera lens? | on the right | The response does not provide the answer "on the right" and instead claims lack of information. |
| mm_0466 | Which license codes are needed to install Windows 10 in Mainland China? | Not answerable | Response provides an answer despite reference being not answerable |
| mm_0467 | Which chemical element in the hard disk exceeds the limit requirements stipulated in the GB/T 26572 standard? | Pb | The response states no element exceeds the limit, which does not match the reference answer 'Pb'. |
| mm_0495 | How many times does mobile phone appear on pages 16 and 18? | 6 | Provided answer 0 does not match reference answer 6 |
| mm_0577 | What is the yellow color italic texts in page 9? | Not answerable | The response asserts there are no yellow italic texts rather than declining or stating the info is unavailable |
| mm_0580 | How many websites are present on the cover page? | 2 | Provided answer 3 does not match reference answer 2 |
| mm_0582 | How many committee members from Texas are presented in the conference of improving the quality and efficiency… | 1 | Response does not provide a clear answer matching the reference integer |
| mm_0762 | How many figures convey similar messages as the first figure? | 2 | Provided answer 1 does not match reference answer 2 |
| mm_0763 | How many strategies outperform the random selection baseline on CIFAR-10-LT? | 4 | Provided answer 5 does not match reference answer 4 |
| mm_0764 | How many strategies outperform the uniform sampling baseline on CIFAR-10-LT? | Not answerable | The response provides an answer, but the reference indicates the question is not answerable |
| mm_0765 | What querying criteria yields the worst label diversity generally on all the datasets? | VAAL | The response gives 'Entropy' instead of the reference answer 'VAAL'. |
| mm_0766 | How many line plots are in this paper? | 3 | Answer gives 15 line plots, which does not match reference answer of 3 |
| mm_0769 | On the dataset map of PathMNIST, does the map by ground truth or pseudo-labels have a larger confidence varia… | ground truth | Assistant answered pseudo‑labels, contradicting reference 'ground truth' |

## FinanceBench (36 questions)

| Metric | Value |
|---|---|
| Accuracy | **69.4%** (95% CI 53.1%–82.0%) |
| Wrong answers | 22.2% |
| Declined to answer | 8.3% |
| Gold page among the sources | 91.7% |
| Gold page among the cited sources | 83.3% |
| First word, median / p90 | 10.4s / 20.1s |
| Full answer, median / p90 | 15.4s / 30.0s |
| Model calls per question | 4.9 |
| Tokens per question | 24385 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Ingestion | 24 documents, 10574 chunks; upload 1517.4s, background 3427.5s (index built at `991bbaa`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 12 | 50.0% |
| metrics-generated | 12 | 91.7% |
| novel-generated | 12 | 66.7% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 12 | 66.7% |
| Information extraction | 5 | 80.0% |
| Logical reasoning (based on numerical reasoning) | 2 | 50.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 1 | 100.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 1 | 0.0% |
| Numerical reasoning | 11 | 90.9% |
| Numerical reasoning OR Logical reasoning | 3 | 33.3% |
| Numerical reasoning OR information extraction | 1 | 0.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant provides an incorrect ratio (5.88) instead of the reference answer zero |
| financebench_id_00438 | Does Adobe have an improving operating margin profile as of FY2022? If operating margin is not a useful metri… | No the operating margins of Adobe have recently declined fr… | The assistant says the margin cannot be determined, while the reference states it declined. |
| financebench_id_00591 | Does Adobe have an improving Free cashflow conversion as of FY2022? | Yes, the FCF conversion (using net income as the denominato… | The response declines to answer, while the reference provides a definitive yes with specific conversion figures. |
| financebench_id_00705 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? | $400,000,000 increase. | Assistant's stated increase ($750M) does not match the reference increase ($400M) |
| financebench_id_00882 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreemen… | Total amount Pepsico may borrow under unsecured revolving c… | Assistant did not provide the combined total of $8.4 billion, thus declined and mismatched the reference answer. |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | Assistant concluded CVS is not capital‑intensive, contradicting the reference's Yes answer |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Answer provides different details and omits the referenced legal battle categories, not matching the reference answer |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | Provides a different working capital figure than the reference answer |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | Response gives a generic cost increase reason and omits the specific drivers listed in the reference answer. |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | The assistant gave an inventory turnover of 12.14 times, which does not match the reference value of 9.5 times. |
| financebench_id_10420 | Based on the information provided primarily in the statement of financial position and the statement of incom… | -0.02 | Assistant's ROA of 1.53% does not match reference -0.02 |

