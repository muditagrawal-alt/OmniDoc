"""
Consistency checks on extracted fields, without model calls.

Each document type has rules that its fields must satisfy: an invoice's subtotal plus tax
equals its total, its due date is not before its date, a contract's end follows its start,
a bank statement's opening balance plus credits minus debits equals its closing balance.
A rule reports "ok", "fail" (with the reason) or "skip" (fields missing), so the library can
flag documents that need a human look.
"""
from typing import Any, Callable, Dict, List, Optional

from agents.llm_utils import to_number
from agents.extraction_agent import dates_in

TOLERANCE = 0.01  # 1% for rounding


def _num(fields: Dict[str, Any], name: str) -> Optional[float]:
    f = fields.get(name) or {}
    return to_number(f.get("value")) if f.get("status") in ("found", "check") else None


def _date(fields: Dict[str, Any], name: str) -> Optional[str]:
    f = fields.get(name) or {}
    if f.get("value") in (None, "") or f.get("status") not in ("found", "check"):
        return None
    found = sorted(dates_in(str(f["value"])))
    return f"{found[0][0]:04d}-{found[0][1]:02d}-{found[0][2]:02d}" if found else None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, TOLERANCE * max(abs(a), abs(b)))


def _sum_rule(total: str, parts: List[str], label: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def rule(fields: Dict[str, Any]) -> Dict[str, Any]:
        values = [_num(fields, p) for p in parts]
        t = _num(fields, total)
        if t is None or any(v is None for v in values):
            return {"rule": label, "status": "skip", "message": "Fields missing.", "fields": parts + [total]}
        expected = sum(values)  # type: ignore[arg-type]
        if _close(expected, t):
            return {"rule": label, "status": "ok", "message": f"{' + '.join(f'{v:,.2f}' for v in values)} = {t:,.2f}",
                    "fields": parts + [total]}
        return {"rule": label, "status": "fail",
                "message": f"{' + '.join(f'{v:,.2f}' for v in values)} = {expected:,.2f}, but the document says {t:,.2f}",
                "fields": parts + [total]}
    return rule


def _order_rule(first: str, second: str, label: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def rule(fields: Dict[str, Any]) -> Dict[str, Any]:
        a, b = _date(fields, first), _date(fields, second)
        if not a or not b:
            return {"rule": label, "status": "skip", "message": "Dates missing.", "fields": [first, second]}
        if a <= b:
            return {"rule": label, "status": "ok", "message": f"{a} ≤ {b}", "fields": [first, second]}
        return {"rule": label, "status": "fail", "message": f"{second.replace('_', ' ')} {b} is before {first.replace('_', ' ')} {a}",
                "fields": [first, second]}
    return rule


def _positive_rule(name: str, label: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def rule(fields: Dict[str, Any]) -> Dict[str, Any]:
        v = _num(fields, name)
        if v is None:
            return {"rule": label, "status": "skip", "message": "Field missing.", "fields": [name]}
        return {"rule": label, "status": "ok" if v > 0 else "fail",
                "message": f"{v:,.2f}" if v > 0 else f"{v:,.2f} is not a positive amount", "fields": [name]}
    return rule


def _balance_rule(fields: Dict[str, Any]) -> Dict[str, Any]:
    o, c = _num(fields, "opening_balance"), _num(fields, "closing_balance")
    cr, dr = _num(fields, "total_credits"), _num(fields, "total_debits")
    names = ["opening_balance", "total_credits", "total_debits", "closing_balance"]
    if None in (o, c, cr, dr):
        return {"rule": "Opening + credits − debits = closing", "status": "skip", "message": "Fields missing.", "fields": names}
    expected = o + cr - dr  # type: ignore[operator]
    ok = _close(expected, c)  # type: ignore[arg-type]
    return {"rule": "Opening + credits − debits = closing", "status": "ok" if ok else "fail",
            "message": f"{o:,.2f} + {cr:,.2f} − {dr:,.2f} = {expected:,.2f}" + ("" if ok else f", but closing balance is {c:,.2f}"),
            "fields": names}


RULES: Dict[str, List[Callable[[Dict[str, Any]], Dict[str, Any]]]] = {
    "invoice": [_sum_rule("total", ["subtotal", "tax"], "Subtotal + tax = total"),
                _order_rule("invoice_date", "due_date", "Due date on or after invoice date"),
                _positive_rule("total", "Total is positive")],
    "receipt": [_sum_rule("total", ["subtotal", "tax"], "Subtotal + tax = total"), _positive_rule("total", "Total is positive")],
    "purchase_order": [_order_rule("order_date", "delivery_date", "Delivery on or after order date"),
                       _positive_rule("total", "Total is positive")],
    "contract": [_order_rule("effective_date", "end_date", "Ends after it takes effect")],
    "bank_statement": [_balance_rule, _order_rule("period_start", "period_end", "Period start before end")],
}


def validate(doc_type: str, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Runs the rules of a document type over extracted fields (list of field results)."""
    by_name = {f["name"]: f for f in fields}
    return [rule(by_name) for rule in RULES.get(doc_type, [])]
