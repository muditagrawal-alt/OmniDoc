"""
Financial vocabulary shared by retrieval, calculations and the answer writer.

Filings and analysts name the same line items differently ("net AR" is "Trade receivables,
net"; COGS is "Cost of sales"), and ratio questions assume the standard definitions. This
module gives the search the names a filing uses for the items a question mentions, and the
writers the definitions of the metrics it names (only those: a long glossary distracts a
small model).
"""
import re
from typing import List

# (what a question says, the words a filing uses for it): searched together with the question.
SYNONYMS = (
    (r"\bAR\b|accounts? receivables?|\breceivables?", "accounts receivable trade receivables net"),
    (r"\bAP\b|accounts? payables?|\bpayables?", "accounts payable trade payables"),
    (r"\bCOGS\b|cost of goods sold", "cost of sales cost of revenue cost of products sold"),
    (r"\bcapex\b|capital expenditures?", "capital expenditures purchases of property plant and equipment"),
    (r"\bPP&E\b|fixed assets?", "property plant and equipment net"),
    (r"\bD&A\b|depreciation", "depreciation and amortization"),
    (r"\bEBITDA\b", "operating income depreciation and amortization"),
    (r"\bEBIT\b|operating (income|profit)", "operating income income from operations"),
    (r"\bEPS\b|per share", "earnings per share diluted"),
    (r"\bFCF\b|free cash ?flow", "net cash provided by operating activities purchases of property and equipment"),
    (r"\bSG&A\b", "selling general and administrative expenses"),
    (r"\bR&D\b", "research and development expenses"),
    (r"working capital|current ratio|quick ratio|cash ratio|liquidity", "total current assets total current liabilities"),
    (r"inventor(y|ies)", "inventories cost of sales"),
    (r"dividend", "dividends paid cash dividends declared per share"),
    (r"effective tax rate|tax rate", "provision for income taxes income before income taxes effective tax rate"),
    (r"interest coverage|interest expense", "interest expense operating income"),
    (r"\bROA\b|return on assets", "net income total assets"),
    (r"\bROE\b|return on equity", "net income total shareholders equity"),
    (r"gross (margin|profit)", "gross profit gross margin cost of sales cost of products sold"),
    (r"operating margin", "operating income operating margin"),
    (r"share repurchases?|buybacks?", "repurchases of common stock"),
    # The sections of a filing that hold what a question asks about in everyday words.
    (r"legal|lawsuits?|litigation|court", "legal proceedings litigation contingencies"),
    (r"\brisks?\b", "risk factors"),
    (r"acquisitions?|acquired|mergers?", "business combinations acquisitions"),
    (r"segments?|business lines?|divisions?", "segment information reportable segments"),
    (r"employees|headcount|workforce|staff", "human capital employees"),
    (r"geograph\w*|regions?|countries", "geographic information revenues by geographic area"),
    (r"restructuring", "restructuring charges"),
    (r"guidance|outlook", "outlook guidance expects"),
    (r"securities exchange|securities (are |were )?registered|trading symbol|section 12\(b\)",
     "securities registered pursuant to section 12(b) title of each class "
                                                       "trading symbol name of each exchange on which registered"),
)

# Standard definitions, given to the writers only for the metrics a question names.
DEFINITIONS = (
    (r"gross margin", "gross margin = gross profit / revenue"),
    (r"operating margin", "operating margin = operating income / revenue"),
    (r"net (profit |income )?margin|profit margin", "net margin = net income / revenue"),
    (r"\bEBITDA\b", "EBITDA = operating income + depreciation and amortization (D&A, from the cash flow statement)"),
    (r"\bEBIT\b", "EBIT = operating income"),
    (r"free cash ?flow|\bFCF\b", "free cash flow = cash from operations - capex; FCF conversion = free cash flow / net income"),
    (r"current ratio", "current ratio = current assets / current liabilities"),
    (r"quick ratio", "quick ratio = (cash and equivalents + short-term investments + receivables) / current liabilities"),
    (r"cash ratio", "cash ratio = cash and cash equivalents / current liabilities"),
    (r"working capital", "working capital = current assets - current liabilities"),
    (r"inventory turnover|times .{0,40}(sold|turned|converted) .{0,20}inventory", "inventory turnover = COGS / average inventory"),
    (r"days (of )?inventory|\bDIO\b", "days inventory outstanding = 365 / inventory turnover"),
    (r"receivables? turnover", "receivables turnover = revenue / average accounts receivable"),
    (r"days sales outstanding|\bDSO\b", "days sales outstanding = 365 / receivables turnover"),
    (r"payables? turnover", "payables turnover = COGS / average accounts payable"),
    (r"days payables? outstanding|\bDPO\b", "days payable outstanding = 365 / payables turnover"),
    (r"cash conversion cycle", "cash conversion cycle = DIO + DSO - DPO (days inventory, sales and payables outstanding)"),
    (r"fixed asset turnover", "fixed asset turnover = revenue / average net PP&E"),
    (r"(?<!fixed )asset turnover", "asset turnover = revenue / average total assets"),
    (r"\bROA\b|return on (total )?assets", "ROA = net income / average total assets"),
    (r"\bROE\b|return on (shareholders'? |stockholders'? )?equity", "ROE = net income / average shareholders' equity"),
    (r"interest coverage", "interest coverage = EBIT / interest expense"),
    (r"debt[- ]to[- ]equity", "debt-to-equity = total debt / total shareholders' equity"),
    (r"effective tax rate", "effective tax rate = income tax expense / income before income taxes"),
    (r"payout ratio", "dividend payout ratio = dividends / net income"),
    (r"capex|capital expenditures?", "capex = purchases of property, plant and equipment (cash flow statement, investing activities); "
                                     "capex as % of revenue = capex / revenue"),
)
# The names a filing gives the items a question uses.
NAMES = (
    (r"\bAR\b|accounts? receivables?|\breceivables?", "accounts receivable (AR) = trade receivables, net"),
    (r"\bAP\b|accounts? payables?|\bpayables?", "accounts payable (AP) = trade payables"),
    (r"\bCOGS\b|cost of goods|inventory turnover|payables? turnover|days (of )?inventory|days payables?",
     "COGS = cost of sales = cost of revenue(s) = cost of products sold"),
    (r"\bPP&E\b|fixed assets?|property,? plant", "PP&E = property, plant and equipment, net"),
    (r"\bD&A\b|depreciation|EBITDA", "D&A = depreciation and amortization, from the cash flow statement"),
    (r"operating (income|profit)|\bEBIT", "operating income = operating profit = income from operations"),
    (r"unadjusted", "unadjusted = as reported (GAAP)"),
)
AVERAGE = re.compile(r"\baverage\b|turnover|\bROA\b|\bROE\b|return on|days (sales|payables?|inventory)|\bD[SPI]O\b|cash conversion", re.I)
# FinanceBench-style invitation: "If inventory turnover is not a useful metric for a company like this, then state that..."
NOT_MEANINGFUL = re.compile(r"not (a )?(useful|meaningful|relevant)", re.I)
# Questions about the classes of securities listed on an exchange (not "registered users" or trademarks).
REGISTERED = re.compile(r"securities exchange|securities (are |were )?registered|trading symbol|section 12\(b\)", re.I)


def notes_for(question: str) -> str:
    """Definitions and line-item names for the financial metrics the question names ("" when none)."""
    q = (question or "").replace("_", " ")  # "cash_ratio"
    lines = [d for pattern, d in DEFINITIONS if re.search(pattern, q, re.I)]
    lines += [n for pattern, n in NAMES if re.search(pattern, q, re.I)]
    if REGISTERED.search(q):
        lines.append("A filing's cover page lists every class of securities registered on a national securities exchange "
                     "(Section 12(b) of the Act): a kind of security missing from that list (debt securities when only "
                     "common shares are listed) is not registered, so the answer is that there are none.")
    if not lines:
        return ""
    lines.insert(0, "When the question defines the metric or names the statements to use, follow that exactly; "
                    "otherwise use these standard definitions.")
    if AVERAGE.search(q):
        lines.append("An average balance for a year = (balance at the end of the prior year + balance at the end of the year) / 2; "
                     "a balance sheet shows both year-ends.")
    lines.append("Statement amounts are usually in millions or thousands (see the statement heading); keep the unit and say it.")
    if NOT_MEANINGFUL.search(q):
        lines.append("Some metrics do not apply to some businesses: banks, card issuers and insurers report no COGS and no "
                     "operating income line, so gross margin, operating margin and inventory turnover mean little for them "
                     "(their performance is measured by net interest income, provisions for credit losses and pretax income). "
                     "If the evidence shows the metric does not apply, say so and explain why; otherwise compute it.")
    return "FINANCIAL DEFINITIONS (the figures still come only from the evidence):\n- " + "\n- ".join(lines)


def search_terms(question: str) -> str:
    """The words a filing uses for the items the question names, as one extra search query ("" if none)."""
    words: List[str] = []
    question = (question or "").replace("_", " ")
    for pattern, terms in SYNONYMS:
        if re.search(pattern, question, re.I):
            words += [w for w in terms.split() if w not in words]
    return " ".join(words)
