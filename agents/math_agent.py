"""
Mathematical & Statistical Reasoning Agent for OmniDoc.

The LLM only *plans* a calculation: named numeric inputs copied from the evidence plus a
formula over those names. The formula is never exec'd or eval'd. It is parsed with Python's
``ast`` module, checked against a whitelist (numbers, input names, + - * / ^ %, unary minus
and a few math functions; no attributes, subscripts, strings, lambdas or other names, so
``__import__``, ``__class__``, ``open``, ``os``, ``sys`` cannot even be expressed), size-
and exponent-bounded, converted node by node into a SymPy expression and evaluated with
SymPy ``evalf`` under a wall-clock timeout. Inputs that do not appear in the evidence are
flagged; a calculation whose inputs are all absent from the evidence is discarded.
"""
import re
import ast
import math
import time
import logging
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple

import sympy as sp

from core.state import AgentWorkflowState, MathExecutionResult
from agents.llm_utils import chat_json, to_number, extract_numbers, number_in_text, as_list, as_str_list, trace
from agents.citations import build_sources, format_evidence_block, is_real_chunk

logger = logging.getLogger("OmniDoc.MathAgent")

MAX_EXPR_CHARS = 400
MAX_AST_NODES = 150
MAX_ABS_EXPONENT = 1000
MAX_CALCULATIONS = 3
EVAL_TIMEOUT_S = 5.0

MATH_PLANNER_PROMPT = """You are the calculation planner of OmniDoc. Decide whether answering the QUESTION requires arithmetic on numbers that appear in the EVIDENCE or in the QUESTION itself. You do NOT compute results; you only define the formula.

Rules:
1. Every input value must be copied exactly from the evidence or the question. A count derived directly from them (e.g. number of years between 2020 and 2024 = 4) is allowed but must be explained in "assumptions". Never invent or estimate numbers.
2. Input names are short snake_case identifiers that start with a letter (e.g. revenue_2020, years).
3. "expression" may use only the input names, numbers, + - * / ^ ( ) and the functions sqrt, log, ln, log10, exp, abs, min, max, round.
4. If the result is a percentage, multiply by 100 inside the expression and set units to "%".
5. At most {max_calcs} calculations. If no arithmetic is needed or the needed numbers are not available, return {{"calculations": []}}.

Return JSON only:
{{"calculations": [{{"task": "short description", "inputs": {{"name": 123.4}}, "expression": "formula using the input names", "units": "unit or null", "assumptions": ["..."]}}]}}

EVIDENCE:
{evidence}

QUESTION:
{query}
"""


class UnsafeExpressionError(ValueError):
    """Raised when a formula contains anything outside the arithmetic whitelist."""


class UngroundedInputError(ValueError):
    """Raised when a calculation uses numbers that are neither in the sources nor explained."""


def _quoted_with_unit(value: float, units: Optional[str], text: str) -> Optional[float]:
    """
    Undoes a unit-scale slip: if ``value`` is a number quoted in ``text`` times a power of
    1000 and that quoted number is written right before ``units`` (e.g. "11.5 TW" when the
    calculation is in TW), returns the quoted number.
    """
    unit = (units or "").strip()
    if not unit or not re.match(r"^[A-Za-z%][\w%/^.-]{0,15}$", unit):
        return None
    pattern = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*" + re.escape(unit) + r"(?![A-Za-z])")
    for m in pattern.finditer(text):
        quoted = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        for k in (1, 2, 3, 4):
            for scaled in (quoted * 1000.0 ** k, quoted / 1000.0 ** k):
                if abs(value - scaled) <= 1e-9 * max(1.0, abs(value), abs(scaled)):
                    return quoted
    return None


RETRY_NOTE = """

A previous attempt was rejected because these inputs do not appear in the EVIDENCE or the QUESTION: {problems}.
Copy every number exactly as written there, keeping its original unit (for example 11.5 with units "TW", not 11500). Convert units only inside "expression", and explain any conversion in "assumptions"."""


_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
_UNARY_OPS = (ast.UAdd, ast.USub)
_FUNCS_NUMERIC = {
    "sqrt": math.sqrt, "log": math.log, "ln": math.log, "log10": math.log10, "exp": math.exp,
    "abs": abs, "min": min, "max": max, "round": round,
}
_CONSTANTS = {"pi": (math.pi, sp.pi), "e": (math.e, sp.E)}


def _sympy_func(name: str, args: List[sp.Expr]) -> sp.Expr:
    if name == "sqrt":
        return sp.sqrt(args[0])
    if name in ("log", "ln"):
        return sp.log(*args[:2])
    if name == "log10":
        return sp.log(args[0], 10)
    if name == "exp":
        return sp.exp(args[0])
    if name == "abs":
        return sp.Abs(args[0])
    if name == "min":
        return sp.Min(*args)
    if name == "max":
        return sp.Max(*args)
    if name == "round":
        return sp.Function("round")(*args)
    raise UnsafeExpressionError(f"function {name!r} not allowed")


def parse_formula(expression: str, input_names: List[str]) -> ast.Expression:
    """Parses and validates a formula; raises UnsafeExpressionError for anything non-arithmetic."""
    if not isinstance(expression, str) or not expression.strip():
        raise UnsafeExpressionError("empty expression")
    if len(expression) > MAX_EXPR_CHARS:
        raise UnsafeExpressionError("expression too long")
    if "__" in expression:
        raise UnsafeExpressionError("dunder names are not allowed")
    expr = (expression.replace("^", "**").replace("×", "*").replace("÷", "/")
            .replace("−", "-").strip())
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpressionError(f"syntax error: {e.msg}")
    allowed_names = set(input_names) | set(_CONSTANTS)
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_AST_NODES:
            raise UnsafeExpressionError("expression too large")
        if isinstance(node, (ast.Expression, ast.Load)) or isinstance(node, _BIN_OPS + _UNARY_OPS):
            continue
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _BIN_OPS):
                raise UnsafeExpressionError(f"operator {type(node.op).__name__} not allowed")
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _UNARY_OPS):
                raise UnsafeExpressionError(f"operator {type(node.op).__name__} not allowed")
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise UnsafeExpressionError("only numeric literals are allowed")
            if abs(node.value) > 1e15:
                raise UnsafeExpressionError("numeric literal too large")
            continue
        if isinstance(node, ast.Name):
            if node.id not in allowed_names and node.id not in _FUNCS_NUMERIC:
                raise UnsafeExpressionError(f"unknown name {node.id!r}")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS_NUMERIC:
                raise UnsafeExpressionError("only whitelisted math functions may be called")
            if node.keywords or not node.args or len(node.args) > 20:
                raise UnsafeExpressionError("bad function call")
            continue
        raise UnsafeExpressionError(f"{type(node).__name__} is not allowed")
    # Function names may only appear as call targets.
    call_targets = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in _FUNCS_NUMERIC and id(n) not in call_targets and n.id not in allowed_names:
            raise UnsafeExpressionError(f"{n.id!r} must be called")
    return tree


def _numeric(node: ast.AST, env: Dict[str, float]) -> float:
    """Float evaluation used as a bounded pre-flight (overflow, division by zero, complex)."""
    if isinstance(node, ast.Expression):
        return _numeric(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        return _CONSTANTS[node.id][0]
    if isinstance(node, ast.UnaryOp):
        v = _numeric(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _numeric(node.left, env), _numeric(node.right, env)
        op = node.op
        if isinstance(op, ast.Add):
            return a + b
        if isinstance(op, ast.Sub):
            return a - b
        if isinstance(op, ast.Mult):
            return a * b
        if isinstance(op, (ast.Div, ast.Mod)) and b == 0:
            raise ZeroDivisionError("division by zero")
        if isinstance(op, ast.Div):
            return a / b
        if isinstance(op, ast.Mod):
            return a % b
        if abs(b) > MAX_ABS_EXPONENT:
            raise UnsafeExpressionError("exponent too large")
        r = a ** b
        if isinstance(r, complex):
            raise ValueError("result is not a real number")
        return float(r)
    if isinstance(node, ast.Call):
        args = [_numeric(a, env) for a in node.args]
        return float(_FUNCS_NUMERIC[node.func.id](*args))
    raise UnsafeExpressionError(f"{type(node).__name__} is not allowed")


def _to_sympy(node: ast.AST, symbols: Dict[str, sp.Symbol]) -> sp.Expr:
    if isinstance(node, ast.Expression):
        return _to_sympy(node.body, symbols)
    if isinstance(node, ast.Constant):
        v = node.value
        return sp.Integer(v) if isinstance(v, int) else sp.Float(repr(v))
    if isinstance(node, ast.Name):
        if node.id in symbols:
            return symbols[node.id]
        return _CONSTANTS[node.id][1]
    if isinstance(node, ast.UnaryOp):
        v = _to_sympy(node.operand, symbols)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _to_sympy(node.left, symbols), _to_sympy(node.right, symbols)
        op = node.op
        if isinstance(op, ast.Add):
            return sp.Add(a, b, evaluate=False)
        if isinstance(op, ast.Sub):
            return sp.Add(a, sp.Mul(-1, b, evaluate=False), evaluate=False)
        if isinstance(op, ast.Mult):
            return sp.Mul(a, b, evaluate=False)
        if isinstance(op, ast.Div):
            return sp.Mul(a, sp.Pow(b, -1, evaluate=False), evaluate=False)
        if isinstance(op, ast.Mod):
            return sp.Mod(a, b, evaluate=False)
        return sp.Pow(a, b, evaluate=False)
    if isinstance(node, ast.Call):
        return _sympy_func(node.func.id, [_to_sympy(a, symbols) for a in node.args])
    raise UnsafeExpressionError(f"{type(node).__name__} is not allowed")


def _clean_result(value: float) -> Any:
    if not math.isfinite(value):
        raise ValueError("result is not finite")
    if abs(value - round(value)) < 1e-9 and abs(value) < 1e15:
        return int(round(value))
    return float(f"{value:.10g}")


def _evaluate(expression: str, inputs: Dict[str, float]) -> Tuple[Any, str]:
    """Returns (result, latex). Raises on unsafe/invalid formulas."""
    tree = parse_formula(expression, list(inputs))
    preflight = _numeric(tree, inputs)
    if not math.isfinite(preflight):
        raise ValueError("result is not finite")
    symbols = {name: sp.Symbol(name) for name in inputs}
    expr = _to_sympy(tree, symbols)
    latex = sp.latex(expr)
    subs = {symbols[k]: sp.Float(repr(float(v)), 30) for k, v in inputs.items()}
    try:
        value = complex(expr.evalf(30, subs=subs))
        if abs(value.imag) > 1e-12 * max(1.0, abs(value.real)):
            raise ValueError("result is not a real number")
        result = float(value.real)
    except (TypeError, ValueError):
        result = preflight  # e.g. round(): SymPy keeps it symbolic; the bounded float pass is exact enough
    return _clean_result(result), latex


def safe_evaluate(expression: str, inputs: Dict[str, float], timeout_s: float = EVAL_TIMEOUT_S) -> Tuple[Any, str]:
    """Evaluates a validated formula with a wall-clock timeout."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_evaluate, expression, inputs)
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"evaluation exceeded {timeout_s}s")
    finally:
        pool.shutdown(wait=False)


def _sanitize_name(name: str, used: set) -> str:
    base = "".join(ch if (ch.isalnum() or ch == "_") and ch.isascii() else "_" for ch in str(name)).strip("_") or "x"
    if not base[0].isalpha():
        base = "v_" + base
    if base in _FUNCS_NUMERIC or base in _CONSTANTS:
        base = base + "_value"
    cand, i = base, 2
    while cand in used:
        cand, i = f"{base}_{i}", i + 1
    used.add(cand)
    return cand


def _rename_in_expression(expression: str, mapping: Dict[str, str]) -> str:
    for old in sorted(mapping, key=len, reverse=True):
        new = mapping[old]
        if old != new:
            expression = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, expression)
    return expression


class MathematicsAgent:
    """Solves mathematical and statistical queries via a whitelisted SymPy evaluator."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def _evidence(self, state: AgentWorkflowState) -> Tuple[str, List[Dict[str, Any]]]:
        sources = build_sources(
            evidence_package=state.get("evidence_package"),
            chunk_context=state.get("chunk_context", []),
            graph_context=state.get("graph_context", []),
            max_evidence=8,
            table_results=state.get("table_results", []),
        )
        return format_evidence_block(sources), sources

    def _build_result(self, calc: Dict[str, Any], query: str, evidence_text: str,
                      sources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        raw_inputs = calc.get("inputs") if isinstance(calc.get("inputs"), dict) else {}
        expression = str(calc.get("expression") or calc.get("formula") or "").strip()
        if not raw_inputs and not expression:
            return None
        used: set = set()
        mapping, inputs = {}, {}
        for name, val in raw_inputs.items():
            num = to_number(val)
            if num is None:
                logger.info(f"MathAgent: dropping non-numeric input {name!r}={val!r}")
                return None
            safe = _sanitize_name(name, used)
            mapping[str(name)] = safe
            inputs[safe] = num
        expression = _rename_in_expression(expression, mapping)

        # Grounding: inputs must come from the evidence or the question. A derived input
        # (e.g. years between two dates) is allowed only when the model explained it.
        grounded_text = evidence_text + "\n" + query
        grounded_numbers = extract_numbers(grounded_text)
        assumptions = as_str_list(calc.get("assumptions"), max_items=8)
        explained = " ".join(assumptions).lower().replace("_", " ")
        original = {safe: raw for raw, safe in mapping.items()}
        units = calc.get("units")
        units = str(units).strip() if units not in (None, "", "null", "None") else None
        ungrounded = [k for k, v in inputs.items() if not number_in_text(v, grounded_text, grounded_numbers)]
        for k in list(ungrounded):
            quoted = _quoted_with_unit(inputs[k], units, grounded_text)
            if quoted is not None:
                assumptions.append(f"Used {original.get(k, k)} = {quoted:g} {units} as written in the sources "
                                   f"(the planner had rescaled it to {inputs[k]:g}).")
                inputs[k] = quoted
                ungrounded.remove(k)
        unexplained = [
            k for k in ungrounded
            if k.replace("_", " ").lower() not in explained and original.get(k, k).replace("_", " ").lower() not in explained
        ]
        if unexplained:
            raise UngroundedInputError(
                ", ".join(f"{original.get(k, k)} = {inputs[k]:g}" for k in unexplained)
            )
        for k in ungrounded:
            assumptions.append(f"Input {k} = {inputs[k]:g} is derived, not quoted verbatim in the sources.")

        result, latex = safe_evaluate(expression, inputs)
        source_ids = []
        for s in sources:
            nums = extract_numbers(s.get("_text", ""))
            if s.get("chunk_id") and any(number_in_text(v, s["_text"], nums) for v in inputs.values()):
                source_ids.append(s["chunk_id"])
        task = str(calc.get("task") or "Calculation").strip()[:200]
        bindings = ", ".join(f"{k} = {v:g}" for k, v in inputs.items())
        code = f"result = {expression}" + (f"\n# with {bindings}" if bindings else "") + f"\n# result -> {result}"
        artifact = MathExecutionResult(
            task=task,
            inputs=inputs,
            formula=latex,
            code_executed=code,
            exact_result=result,
            units=units,
            assumptions=assumptions,
            source_evidence_ids=list(dict.fromkeys(source_ids)),
        )
        return artifact.model_dump()

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes mathematical reasoning step in LangGraph.
        """
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        query = getattr(semantic_q, "resolved_query", None) or state.get("user_query", "")
        evidence_text, sources = self._evidence(state)
        if not evidence_text:
            # Calculations on numbers given in the question itself are still allowed.
            chunks = [c for c in state.get("chunk_context", []) if is_real_chunk(c)]
            evidence_text = "\n".join(c["text"] for c in chunks[:5])

        if not extract_numbers(evidence_text + " " + query):
            return {"math_results": [], "agent_traces": [trace("math_agent", "skipped", "No numbers in evidence.", started)]}

        logger.info(f"MathAgent activated for query: '{query[:60]}'")
        prompt = MATH_PLANNER_PROMPT.format(evidence=evidence_text[:9000] or "(none)", query=query,
                                            max_calcs=MAX_CALCULATIONS)
        results, problems = [], []
        # One corrective retry when the model copies numbers that are not in the sources.
        for attempt in range(2):
            try:
                parsed = chat_json(self.model_name, prompt, num_predict=700)
            except Exception as e:
                logger.error(f"MathAgent planning error: {e}")
                return {
                    "math_results": [],
                    "errors": [f"MathAgent planning error: {e}"],
                    "agent_traces": [trace("math_agent", "failed", str(e)[:200], started)],
                }
            calcs = parsed.get("calculations") if isinstance(parsed, dict) else parsed
            if isinstance(parsed, dict) and not calcs and parsed.get("expression"):
                calcs = [parsed]  # model returned a single calculation object
            results, problems, ungrounded = [], [], []
            for calc in as_list(calcs)[:MAX_CALCULATIONS]:
                if not isinstance(calc, dict):
                    continue
                try:
                    res = self._build_result(calc, query, evidence_text, sources)
                    if res:
                        results.append(res)
                except UngroundedInputError as e:
                    ungrounded.append(str(e))
                    problems.append(f"{calc.get('task', 'calculation')}: inputs not in the sources ({e})")
                    logger.info(f"MathAgent rejected calculation {calc.get('expression')!r}: ungrounded inputs {e}")
                except Exception as e:
                    problems.append(f"{calc.get('task', 'calculation')}: {e}")
                    logger.warning(f"MathAgent rejected calculation {calc.get('expression')!r}: {e}")
            if results or not ungrounded or attempt == 1:
                break
            prompt += RETRY_NOTE.format(problems="; ".join(ungrounded))

        detail = f"{len(results)} calculation(s)" + (f"; rejected: {problems}" if problems else "")
        logger.info(f"MathAgent: {detail}")
        out: Dict[str, Any] = {
            "math_results": results,
            "agent_traces": [trace("math_agent", "completed", detail[:300], started)],
        }
        if problems and not results:
            out["errors"] = [f"MathAgent: {p}" for p in problems]
        return out
