# Benchmark run 2026-10-17_revision-d_f115f41

Commit `f115f41`. Answer model `nvidia:nvidia/nemotron-3-super-120b-a12b` (provider `nvidia` only, no fallback), vision `gemini:gemini-3.5-flash-lite`, embeddings `nomic-embed-text`, judge `groq:openai/gpt-oss-120b`. Each question is asked about its own document, web search off.

Notes: Revision D on all 150 open-source FinanceBench questions (84 filings), each asked about its own filing, web search off. The 24 filings of the test split come from the test index (built at revision C, re-embedded at revision D); the other 60 were ingested in this run.

## FinanceBench (150 questions)

| Metric | Value |
|---|---|
| Accuracy | **70.7%** (95% CI 62.9%–77.4%) |
| Wrong answers | 22.0% |
| Declined to answer | 7.3% |
| Gold page among the sources | 85.3% |
| Gold page among the cited sources | 70.0% |
| First word, median / p90 | 14.6s / 29.6s |
| Full answer, median / p90 | 23.8s / 47.0s |
| Model calls per question | 4.0 |
| Tokens per question | 19201 |
| Answers with errors | 0 |
| Answers that needed a retry (rate limit or model error) | 0 |
| Answers rewritten after the sentence check (graded correct) | 23 (15) |
| Ingestion | 84 documents, 33352 chunks; upload 4669.9s, background 19436.9s (index built at `991bbaa`) |

**By question type**

| Group | Questions | Accuracy |
|---|---|---|
| domain-relevant | 50 | 56.0% |
| metrics-generated | 50 | 90.0% |
| novel-generated | 50 | 66.0% |

**By reasoning**

| Group | Questions | Accuracy |
|---|---|---|
| - | 50 | 66.0% |
| Information extraction | 31 | 71.0% |
| Information extraction OR Logical reasoning | 1 | 0.0% |
| Information extraction OR Logical reasoning OR | 1 | 100.0% |
| Logical reasoning (based on numerical reasoning) | 5 | 40.0% |
| Logical reasoning (based on numerical reasoning) OR Logical reasoning | 5 | 80.0% |
| Logical reasoning (based on numerical reasoning) OR Numerical reasoning OR Logical reasoning | 4 | 75.0% |
| Numerical reasoning | 43 | 88.4% |
| Numerical reasoning OR Logical reasoning | 6 | 16.7% |
| Numerical reasoning OR information extraction | 4 | 50.0% |

**Missed questions**

| Id | Question | Reference | Grader's reason |
|---|---|---|---|
| financebench_id_00005 | Does Corning have positive working capital based on FY2022 data? If working capital is not a useful or releva… | Yes. Corning had a positive working capital amount of $831 … | Provided a positive working capital but with an incorrect amount ($2,278 million vs reference $831 million) |
| financebench_id_00070 | Does American Water Works have positive working capital based on FY2022 data? If working capital is not a use… | No, American Water Works had negative working capital of -$… | Assistant says data missing and cannot determine, while reference provides a specific negative working capital value. |
| financebench_id_00080 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevan… | Yes. Paypal has a positive working capital of $ 1.6Bn as of… | Provided a positive working capital but with an incorrect amount ($12.4B vs $1.6B). |
| financebench_id_00215 | Is Verizon a capital intensive business based on FY 2022 data? | Yes. Verizon's capital intensity ratio was approximately 2.… | Assistant did not commit to a Yes answer and provided a different metric, contradicting the reference. |
| financebench_id_00283 | How much does Pfizer expect to pay to spin off Upjohn in the future in USD million? | 77.78 | Assistant answered $70 million, which does not match the reference value of 77.78 |
| financebench_id_00302 | Did Pfizer grow its PPNE between FY20 and FY21? | Yes, change in PPNE was positive year over year | The response declines to answer, while the reference provides a positive answer |
| financebench_id_00460 | Was there any change in the number of Best Buy stores between Q2 of FY2024 and FY2023? | Yes, there is decline in number stores by 1.32% from 982 st… | Provided numbers do not match the reference figures of 982 and 969 stores |
| financebench_id_00476 | Which debt securities are registered to trade on a national securities exchange under American Express' name … | There are none | Response declines to answer, but reference states there are none. |
| financebench_id_00499 | Is 3M a capital-intensive business based on FY2022 data? | No, the company is managing its CAPEX and Fixed Assets pret… | The assistant declined to answer, while the reference provides a definitive answer with metrics. |
| financebench_id_00540 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio f… | AES has converted inventory 9.5 times in FY 2022. | The answer gives 12.14 times, which does not match the reference figure of 9.5 times. |
| financebench_id_00566 | Has Verizon increased its debt on balance sheet between 2022 and the 2021 fiscal period? | No. Verizon's debt decreased by $229 million. | The answer provides a different debt change amount than the reference. |
| financebench_id_00585 | How does Boeing's effective tax rate in FY2022 compare to FY2021? | Effective tax rate in FY2022 was 0.62%, compared to -14.76%… | Provided rates are incorrect; FY2021 rate sign is wrong |
| financebench_id_00601 | What drove the reduction in SG&A expense as a percent of net sales in FY2023? | Lower marketing expenses and leverage of incentive compensa… | Provides extra incorrect reasons beyond the reference answer |
| financebench_id_00603 | What drove the increase in Ulta Beauty's merchandise inventories balance at end of FY2023? | Increase in Merchandise inventories balance was driven by t… | Response adds extra causes beyond the reference's sole reason of opening 47 new stores |
| financebench_id_00605 | What percent of Ulta Beauty's total spend on stock repurchases for FY 2023 occurred in Q4 of FY2023? | 36%. The answer here assumes FY2023 refers to the 12 months… | The response declines to provide the percentage, while the reference answer gives 36%. |
| financebench_id_00606 | Did Ulta Beauty's wages expense as a percent of net sales increase or decrease in FY2023? | Wages expense as a percent of net sales increased in FY2023… | Assistant says wages expense decreased, contradicting reference that it increased |
| financebench_id_00669 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company lik… | For FY22, JnJ had changes in gross margin due to: One-time … | The assistant says the information is not provided, whereas the reference lists specific drivers. |
| financebench_id_00678 | Does Boeing have an improving gross margin profile as of FY2022? If gross margin is not a useful metric for a… | Yes. Boeing has an improving gross margin profile as of FY2… | Assistant claims insufficient data and does not provide the correct yes answer with figures. |
| financebench_id_00705 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? | $400,000,000 increase. | Assistant gave $750M increase, which does not match reference $400M |
| financebench_id_00723 | Does AMEX have an improving operating margin profile as of 2022? If operating margin is not a useful metric f… | Performance is not measured through operating margin | Response provides an answer and claims operating margin is usable, contradicting reference that it is not a useful metr… |
| financebench_id_00746 | Which debt securities are registered to trade on a national securities exchange under Ulta Beauty's name as o… | There are none | Assistant declined to answer, but reference states there are none |
| financebench_id_00790 | Is CVS Health a capital-intensive business based on FY2022 data? | Yes, CVS Health requires an extensive asset base to operate… | Assistant says information insufficient, but reference provides a clear yes answer |
| financebench_id_00799 | Has AMCOR's quick ratio improved or declined between FY2023 and FY2022? If the quick ratio is not something t… | The quick ratio has slightly improved from 0.67 times to 0.… | Provided an answer but the quick ratio figures are incorrect, so it does not match the reference. |
| financebench_id_00807 | Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick r… | No. The quick ratio for 3M was 0.96 by Jun'23 close, which … | Provided quick ratio (0.8468) does not match reference value (0.96) |
| financebench_id_00839 | Does Foot Locker's new CEO have previous CEO experience in a similar company to Footlocker? | Yes. She was previous CEO of Ulta Beauty which means she ha… | Response answers No, contradicting reference Yes |
| financebench_id_00941 | Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2… | Following debt securities registered under 3M's name are li… | Assistant provides a generic Series F description instead of the specific three notes listed in the reference. |
| financebench_id_00995 | What are the major products and services that AMD sells as of FY22? | AMD sells server microprocessors (CPUs) and graphics proces… | The response provides an answer but includes inaccurate and extraneous details that do not match the reference list of … |
| financebench_id_01009 | What are the geographies that Pepsico primarily operates in as of FY2022? | As of FY2022, Pepsico primarily operates in the following g… | Assistant omitted several geographies listed in the reference answer. |
| financebench_id_01079 | What are major acquisitions that AMCOR has done in FY2023, FY2022 and FY2021? | Amcor completed these acquisitions during FY2023: -100% equ… | Provided monetary figures instead of the specific acquisitions listed in the reference answer |
| financebench_id_01107 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? | Yes, CVS Health has been involved in multiple ongoing legal… | Answer provides details but omits the reference's key legal battle categories (pricing and PBM litigation) and thus doe… |
| financebench_id_01198 | What drove revenue change as of the FY22 for AMD? | In 2022, AMD reported Higher sales of their EPYC server pro… | Response omits EPYC server processor sales as a revenue driver, missing a key item from the reference answer |
| financebench_id_01290 | Who are the primary customers of Boeing as of FY2022? | Boeing's primary customers as of FY2022 are a limited numbe… | Assistant added extra categories and omitted the specific focus on US government as primary customer, deviating from re… |
| financebench_id_01865 | If we exclude the impact of M&A, which segment has dragged down 3M's overall growth in 2022? | The consumer segment shrunk by 0.9% organically. | The answer gives a different segment (Transportation and Electronics) than the reference (consumer segment). |
| financebench_id_01902 | Which Best Buy product category performed the best (by top line) in the domestic (USA) Market during Q2 of FY… | The entertainment segment experienced the highest growth of… | Assistant's answer cites Computing and Mobile Phones, which does not match the reference answer's entertainment segment. |
| financebench_id_01911 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expens… | As adjusted EBIT is negative, coverage ratio is zero | Assistant provides a numeric ratio (2.42) contradicting reference answer of zero |
| financebench_id_01930 | How much was the Real change in Sales for AMCOR in FY 2023 vs FY 2022, if we exclude the impact of FX movemen… | The Real Growth was flat in FY 2023 vs FY 2022. | Assistant gave 1% growth, but reference says growth was flat (0%). |
| financebench_id_01936 | What is the nature & purpose of AMCOR's restructuring liability as oF Q2 of FY2023 close? | 87% of the total restructuring liability is related Employe… | Response does not provide the 87% employee liability figure required by the reference answer |
| financebench_id_01964 | What was the largest liability in American Express's Balance Sheet in 2022? | Customer deposits | Provided a different liability (Other liabilities) instead of the reference answer (Customer deposits) |
| financebench_id_02419 | As of Q2'2023, is Pfizer spinning off any large business segments? | Yes, it's spinning off Upjohn. | Answer mentions a different spin‑off (consumer health) and does not state Upjohn as in reference |
| financebench_id_03473 | What is the FY2017 return on assets (ROA) for Coca Cola? ROA is defined as: FY2017 net income / (average tota… | 0.01 | Assistant provided a numeric answer (1.46%) that does not match the reference answer of 0.01 |
| financebench_id_04412 | We need to calculate a reasonable approximation (or exact number if possible) of a financial metric. Basing y… | 1.33 | Assistant did not provide the asset turnover ratio answer. |
| financebench_id_05718 | How much (in USD billions) did American Water Works pay out in cash dividends for FY2020? Compute or extract … | $0.40 | The response gave $0.389 billion, which does not match the reference answer of $0.40 billion. |
| financebench_id_06655 | What is Amazon's FY2017 days payable outstanding (DPO)? DPO is defined as: 365 * (average accounts payable be… | 93.86 | Provided DPO value 112.88 does not match reference 93.86 |
| financebench_id_10420 | Based on the information provided primarily in the statement of financial position and the statement of incom… | -0.02 | Answer provided but ROA value -1.42% does not match reference -0.02 |

