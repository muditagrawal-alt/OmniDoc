"""
End-to-end evaluation on BEIR SciFact with RAGAS: OmniDoc answers every test claim from the
library of 5,183 abstracts, the way a user would ask it ("Is it true that ...?"), and the answers
are scored three ways:

* verdict accuracy: the answer's verdict (supported / refuted / not enough evidence), read by the
  judge, against SciFact's gold label (Wadden et al., EMNLP 2020; the 300 BEIR test claims are
  SciFact's labelled dev set: 124 supported, 64 refuted, 112 without evidence in the cited
  abstract). A rule-based reading (Yes / No / the app's refusal) is kept as a cross-check.
* RAGAS metrics (Es et al., EACL 2024), graded by a judge model of another family than the answer
  model: faithfulness (are the answer's statements backed by the evidence it was given?), answer
  relevancy, and factual-correctness recall (does the answer contain the gold rationale? Recall,
  because the gold rationale is a few sentences and a good answer says more).
* evidence recall: whether the gold evidence abstract was among the passages the answer was
  written from, and whether the answer cites it. Exact.

    .venv/bin/python -I benchmarks/ragas_eval.py fetch                    # SciFact labels and rationales
    .venv/bin/python -I benchmarks/ragas_eval.py answer --label baseline   # OmniDoc answers (no judge)
    benchmarks/work/ragas-venv/bin/python -I benchmarks/ragas_eval.py score benchmarks/results/ragas/<run>
    .venv/bin/python -I benchmarks/ragas_eval.py report                   # rebuild reports and HISTORY.md

The answers come from OmniDoc's pipeline run in-process on the index of the retrieval benchmark
(benchmarks/beir.py: the app's chunker, embeddings and LanceDB store), with the models of the QA
benchmarks pinned and web search off; the evidence each answer was written from is stored with
it, so the judge reads exactly what the writer read. RAGAS runs in its own environment, so its
LangChain pins never touch the app's:

    python3.12 -m venv benchmarks/work/ragas-venv
    benchmarks/work/ragas-venv/bin/pip install ragas==0.4.3 langchain-community==0.3.31 \\
        "langchain<1" "langchain-core<1" "langchain-openai<1"

Each run is stored in benchmarks/results/ragas/<date>_scifact_<label>_<commit>/: config.json,
answers.jsonl, scores.jsonl (one judge result per claim and metric), summary.json and report.md;
HISTORY.md there compares the runs. Development runs (--split train, other claims) go to dev/.
"""
import argparse
import asyncio
import datetime as dt
import json
import math
import os
import random
import re
import statistics
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.bench import (ATTEMPTS, DEFAULTS, PIPELINE_ERROR, RETRY_WAITS, append_jsonl,  # noqa: E402
                              download, git, latest_rows, log)

SCIFACT_URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
TARBALL = ROOT / "benchmarks" / "datasets" / "scifact-original" / "data.tar.gz"  # git-ignored; read, never extracted
WORK = ROOT / "benchmarks" / "work" / "ragas-scifact"
RESULTS = ROOT / "benchmarks" / "results" / "ragas"
# SciFact's labelled splits: BEIR's test claims are SciFact's dev set, BEIR's train claims its train set.
CLAIM_FILES = {"test": "claims_dev.jsonl", "train": "claims_train.jsonl"}
JUDGE = "nvidia:openai/gpt-oss-20b"      # another family than the answer model (NVIDIA Nemotron)
JUDGE_EMBED = "nomic-embed-text"         # answer relevancy compares questions by embedding (local Ollama)
JUDGE_CONCURRENCY = 3
JUDGE_MAX_TOKENS = 8192
JUDGE_ENDPOINTS = {"nvidia": ("https://integrate.api.nvidia.com/v1", ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY")),
                   "groq": ("https://api.groq.com/openai/v1", ("GROQ_API_KEY",))}
JUDGE_TIMEOUT_S = 600  # a congested free endpoint can take minutes; a timed-out call is retried from scratch
JUDGE_EFFORT = "low"   # gpt-oss reasoning effort: the same verdicts in half the time on the checks tried
PAUSE_S = 15
# As a user would ask; the writer answers yes / no questions with "Yes" or "No" first. (A format
# instruction such as "start with Supported or Refuted" is not followed and adds words to the search.)
QUESTION = "Is it true that {claim}?"
VERDICTS = ("supported", "refuted", "not enough evidence")
VERDICT_PROMPT = """A user asked whether a scientific claim is true, and an assistant answered from a library of research abstracts.

Claim: {claim}

Answer:
{answer}

Which verdict does the answer give about the claim? Reply with JSON only: {{"verdict": "supported"}}, {{"verdict": "refuted"}} or {{"verdict": "not enough evidence"}}.
- supported: the answer says the evidence shows the claim is true (fully or for the most part).
- refuted: the answer says the evidence shows the claim is false or contradicts it.
- not enough evidence: the answer says the documents do not contain, do not address or do not settle the claim."""
_LABELS = {"SUPPORT": "supported", "CONTRADICT": "refuted"}
METRICS = ("faithfulness", "answer_relevancy", "factual_correctness_recall")


# --------------------------------------------------------------------------- data
def fetch(args: argparse.Namespace) -> None:
    from benchmarks import beir
    download(SCIFACT_URL, TARBALL)
    download(beir.BEIR_URL.format(name="scifact"), beir.DATASETS / "scifact.zip")
    for split in CLAIM_FILES:
        claims = gold(split)
        counts = {v: sum(c["label"] == v for c in claims.values()) for v in VERDICTS}
        log(f"scifact {split}: {len(claims)} labelled claims {counts}")


def gold(split: str = "test") -> Dict[str, Dict[str, Any]]:
    """Claim id -> claim, gold verdict, evidence abstracts and a reference answer built from the rationales."""
    with tarfile.open(TARBALL) as t:
        def rows(name: str) -> List[Dict[str, Any]]:
            member = t.extractfile(f"data/{name}")
            return [json.loads(line) for line in member.read().decode("utf-8").splitlines() if line.strip()]
        abstracts = {str(d["doc_id"]): d for d in rows("corpus.jsonl")}
        out: Dict[str, Dict[str, Any]] = {}
        for c in rows(CLAIM_FILES[split]):
            labels = {_LABELS[s["label"]] for ev in c["evidence"].values() for s in ev}
            label = labels.pop() if len(labels) == 1 else ("not enough evidence" if not labels else "mixed")
            parts = []
            for doc, sets in sorted(c["evidence"].items()):
                sentences = sorted({i for s in sets for i in s["sentences"]})
                abstract = abstracts[str(doc)]
                parts.append(f"{abstract['title']}: " + " ".join(abstract["abstract"][i].strip() for i in sentences))
            out[str(c["id"])] = {
                "claim": c["claim"], "label": label, "evidence_docs": sorted(str(d) for d in c["evidence"]),
                "cited_docs": [str(d) for d in c.get("cited_doc_ids") or []],
                "reference": f"{label.capitalize()}. " + " ".join(parts) if parts else "",
            }
    return out


def rule_verdict(answer: str) -> Optional[str]:
    """The verdict an answer's opening states, read by rules (a cross-check of the judge's reading)."""
    a = re.sub(r"^[\W_]+", "", answer or "").lower()
    if re.match(r"(not enough|insufficient|unclear|the (current |provided |available )?(document|abstract|evidence|collection|library)s? "
                r"(do|does|did) not|there is no|no (evidence|information|data|study))", a) or "verifiable records" in a:
        return "not enough evidence"
    if re.match(r"(yes|supported|true|correct)\b", a):
        return "supported"
    if re.match(r"(no|refuted|false|incorrect|not true)\b", a):
        return "refuted"
    return None


def claim_text(claim: str) -> str:
    return claim.strip().rstrip(".").strip()


# --------------------------------------------------------------------------- answer (app environment)
def pin_models(settings: Dict[str, str], data_dir: Path) -> None:
    """The QA benchmarks' models, no local fallback, no web search; set before the app is imported."""
    for k in [k for k in os.environ if k.startswith("OMNIDOC_")]:
        del os.environ[k]
    os.environ.update({
        "OMNIDOC_DATA_DIR": str(data_dir),
        "OMNIDOC_LLM_PROVIDERS": settings["provider"],
        "OMNIDOC_LOCAL_FALLBACK": "0",
        "OMNIDOC_EMBED_MODEL": settings["embed"],
        "OMNIDOC_VISION_MODEL": settings["vision"],
        "OMNIDOC_WEB_SEARCH": "off",
    })


def open_pipeline(settings: Dict[str, str]):
    """OmniDoc's pipeline on the SciFact index (built by beir.py's code, reused while unchanged)."""
    from benchmarks import beir
    data = WORK / "data"
    pin_models(settings, data)
    corpus, _, _ = beir.load("scifact")
    shared = beir.WORK / "beir-scifact" / "embeddings"
    if shared.exists() and not (data / "embeddings").exists():
        import shutil
        shutil.copytree(shared, data / "embeddings")  # the passages' vectors, computed once
    index = beir.build_index("scifact", corpus, data)
    from core.pipeline import AgenticGraphRAGPipeline
    # The index was just built by the app's own code: no re-indexing at start.
    meta = {"embed_model": settings["embed"], "version": AgenticGraphRAGPipeline.INDEX_VERSION}
    (data / "index_meta.json").write_text(json.dumps(meta))
    pipeline = AgenticGraphRAGPipeline(data_dir=str(data), model_name=settings["model"])
    titles = {beir.doc_key(cid): doc["title"] for cid, doc in corpus.items()}
    pipeline.doc_title_provider = lambda: titles
    return pipeline, {beir.doc_key(cid): cid for cid in corpus}, index


def ask(pipeline: Any, question: str, keys: Dict[str, str]) -> Dict[str, Any]:
    from agents.citations import sources_from_state
    started = time.perf_counter()
    first_word, state = None, None
    try:
        for event, data in pipeline.query_stream(question, document_ids=[], web_mode="off"):
            if event == "delta" and first_word is None:
                first_word = time.perf_counter() - started
            elif event == "result":
                state = data
    except Exception as e:  # recorded and retried like a failed answer
        return {"error": f"{type(e).__name__}: {e}"[:300]}
    total = time.perf_counter() - started
    if not state:
        return {"error": "no result"}
    answer = (state.get("verified_response") or state.get("draft_response") or "").strip()
    contexts = [{"n": s["n"], "kind": s["kind"], "doc": keys.get(s.get("doc_id") or "", ""), "text": s.get("_text") or ""}
                for s in sources_from_state(state)]
    usage = state.get("usage") or {}
    return {
        "answer": answer,
        "contexts": contexts,
        "cited": sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)}),
        "usage": {k: usage[k] for k in ("calls", "prompt_tokens", "completion_tokens", "models") if k in usage},
        "first_word_s": round(first_word if first_word is not None else total, 2),
        "total_s": round(total, 2),
        "error": f"pipeline error: {answer[:200]}" if PIPELINE_ERROR.search(answer) or not answer else "",
    }


def run_dir_for(label: str, split: str, commit: str) -> Path:
    name = f"{dt.date.today():%Y-%m-%d}_scifact{'' if split == 'test' else '-' + split}_{label}_{commit}"
    return (RESULTS if split == "test" else RESULTS / "dev") / name


def answer(args: argparse.Namespace) -> None:
    if args.code:
        # Another copy of the app (a revision being tried) answers; the harness and the index stay.
        sys.path.insert(0, str(Path(args.code).resolve()))
    settings = dict(DEFAULTS)
    claims = gold(args.split)
    ids = sorted(claims, key=int)
    if args.sample:
        ids = sorted(random.Random(2026).sample(ids, args.sample), key=int)
    if args.limit:
        ids = ids[:args.limit]
    commit = git("rev-parse", "--short", "HEAD")
    run_dir = Path(args.resume) if args.resume else run_dir_for(args.label, args.split, commit)
    if args.limit and not args.resume:
        run_dir = WORK / "smoke" / run_dir.name  # smoke tests stay out of the results
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({
            "label": args.label, "split": args.split, "started": dt.datetime.now().isoformat(timespec="seconds"),
            "commit": commit, "uncommitted_changes": bool(git("status", "--porcelain", "--untracked-files=no")),
            "settings": settings, "question": QUESTION, "claims": len(ids), "sample": args.sample or None,
            **({"code": str(Path(args.code).resolve())} if args.code else {}),
            "scope": "the whole library of SciFact abstracts (no documents selected); web search off",
            "pacing": f"{args.pause}s between questions; failed answers asked again up to {ATTEMPTS} times",
            "notes": args.notes,
        }, indent=1) + "\n")
    answers_path = run_dir / "answers.jsonl"
    done = {r["id"] for r in latest_rows(answers_path) if not r.get("error")}
    todo = [i for i in ids if i not in done]
    log(f"scifact {args.split}: {len(todo)} of {len(ids)} claims to answer -> {run_dir}")
    if not todo:
        return
    pipeline, keys, index = open_pipeline(settings)
    for n, cid in enumerate(todo, 1):
        c = claims[cid]
        question = QUESTION.format(claim=claim_text(c["claim"]))
        for attempt in range(ATTEMPTS):
            result = ask(pipeline, question, keys)
            if not result.get("error") or attempt == ATTEMPTS - 1:
                break
            wait = RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)]
            log(f"  claim {cid}: {result['error'][:120]} (attempt {attempt + 1}; waiting {wait}s)")
            time.sleep(wait)
        row = {"id": cid, "claim": c["claim"], "label": c["label"], "question": question,
               "rule_verdict": rule_verdict(result.get("answer", "")), "attempts": attempt + 1, **result}
        append_jsonl(answers_path, row)
        mark = "ok" if row["rule_verdict"] == c["label"] else "x"
        log(f"  {n}/{len(todo)} claim {cid}: {row['rule_verdict'] or 'unread'} by rules (gold {c['label']}) {mark} "
            f"{result.get('total_s', 0):.0f}s")
        if n < len(todo):
            time.sleep(args.pause)
    log(f"answers written to {answers_path}")


# --------------------------------------------------------------------------- score (RAGAS environment)
def env_value(*names: str) -> str:
    """A key from the environment or the project's .env (never printed)."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() in names and value.strip():
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def score(args: argparse.Namespace) -> None:
    from openai import AsyncOpenAI
    from ragas.cache import DiskCacheBackend
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    import ragas.metrics.collections as C

    run_dir = Path(args.run)
    provider, model = args.judge.split(":", 1)
    if provider not in JUDGE_ENDPOINTS:
        raise SystemExit(f"Judges are wired up for {', '.join(JUDGE_ENDPOINTS)} (OpenAI-compatible endpoints).")
    url, key_names = JUDGE_ENDPOINTS[provider]
    client = AsyncOpenAI(base_url=url, api_key=env_value(*key_names), max_retries=4, timeout=JUDGE_TIMEOUT_S)
    cache = DiskCacheBackend(cache_dir=str(WORK / "judge-cache" / args.effort))  # one cache per judge setting
    # gpt-oss reasons before it answers: RAGAS's default of 1,024 output tokens cuts replies short.
    judge = llm_factory(model, client=client, cache=cache, max_tokens=JUDGE_MAX_TOKENS, reasoning_effort=args.effort)
    embeddings = OpenAIEmbeddings(client=AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama"), model=JUDGE_EMBED)
    metrics = {
        "faithfulness": C.Faithfulness(llm=judge),
        "answer_relevancy": C.AnswerRelevancy(llm=judge, embeddings=embeddings),
        "factual_correctness_recall": C.FactualCorrectness(llm=judge, mode="recall"),
    }
    config = json.loads((run_dir / "config.json").read_text())
    config["judge"] = {"model": args.judge, "embeddings": JUDGE_EMBED, "ragas": __import__("ragas").__version__,
                       "max_tokens": JUDGE_MAX_TOKENS, "reasoning_effort": args.effort,
                       "metrics": ["verdict", *METRICS], "factual_correctness": "recall mode, against the gold rationale",
                       "verdict_prompt": VERDICT_PROMPT}
    (run_dir / "config.json").write_text(json.dumps(config, indent=1) + "\n")
    claims = gold(config.get("split", "test"))
    answers = [r for r in latest_rows(run_dir / "answers.jsonl") if not r.get("error")]
    if args.sample:
        # The same claims in every run (fixed seed), for a matched comparison when judging is slow.
        chosen = set(random.Random(2026).sample(sorted(claims, key=int), args.sample))
        answers = [r for r in answers if r["id"] in chosen]
    wanted = set(args.metrics.split(",")) if args.metrics else {"verdict", *METRICS}
    scores_path = run_dir / "scores.jsonl"
    done = {(r["id"], r["metric"]) for r in latest_rows_by(scores_path, ("id", "metric")) if r.get("value") is not None}
    jobs = []
    for r in answers:
        g = claims[r["id"]]
        texts = [c["text"] for c in r.get("contexts") or [] if c.get("text")]
        inputs = {
            "verdict": dict(claim=r["claim"], answer=r["answer"]),
            "faithfulness": dict(user_input=r["question"], response=r["answer"], retrieved_contexts=texts) if texts else None,
            "answer_relevancy": dict(user_input=r["question"], response=r["answer"]),
            "factual_correctness_recall": dict(response=r["answer"], reference=g["reference"]) if g["reference"] else None,
        }
        jobs += [(r["id"], m, kw) for m, kw in inputs.items() if kw and m in wanted and (r["id"], m) not in done]
    log(f"{run_dir.name}: {len(jobs)} judge jobs ({len(answers)} answers, judge {args.judge})")
    sem = asyncio.Semaphore(args.concurrency)

    async def read_verdict(claim: str, answer: str) -> str:
        for _ in range(3):
            reply = await client.chat.completions.create(
                model=model, temperature=0, max_tokens=JUDGE_MAX_TOKENS, reasoning_effort=args.effort,
                messages=[{"role": "user", "content": VERDICT_PROMPT.format(claim=claim, answer=answer[:4000])}])
            text = reply.choices[0].message.content or ""
            m = re.search(r'"verdict"\s*:\s*"(supported|refuted|not enough evidence)"', text, re.I)
            if m:
                return m.group(1).lower()
        raise ValueError(f"no verdict in the judge's reply: {text[:120]!r}")

    async def one(cid: str, metric: str, kw: Dict[str, Any]) -> None:
        async with sem:
            started = time.perf_counter()
            extra: Dict[str, Any] = {}
            try:
                if metric == "verdict":
                    extra["verdict"] = await read_verdict(**kw)
                    value, error = float(extra["verdict"] == claims[cid]["label"]), ""
                else:
                    result = await metrics[metric].ascore(**kw)
                    value, error = float(result.value), ""
            except Exception as e:  # a judge reply that could not be parsed, a timeout: counted in the report
                value, error = None, f"{type(e).__name__}: {e}"[:300]
            append_jsonl(scores_path, {"id": cid, "metric": metric, "value": value, **extra, "error": error,
                                       "judge": args.judge, "seconds": round(time.perf_counter() - started, 1)})

    async def main() -> None:
        tasks = [asyncio.create_task(one(*job)) for job in jobs]
        for n, task in enumerate(asyncio.as_completed(tasks), 1):
            await task
            if n % 25 == 0 or n == len(tasks):
                log(f"  {n}/{len(tasks)} judged")
    asyncio.run(main())
    write_summary(run_dir)


def latest_rows_by(path: Path, key: tuple) -> List[Dict[str, Any]]:
    rows: Dict[tuple, Dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows[tuple(r[k] for k in key)] = r
    return list(rows.values())


# --------------------------------------------------------------------------- report
def mean_ci(values: List[float]) -> Dict[str, Any]:
    """Mean with a 95% interval (normal approximation; Wilson for proportions)."""
    if not values:
        return {"n": 0, "mean": None, "low": None, "high": None}
    n, m = len(values), sum(values) / len(values)
    if all(v in (0.0, 1.0) for v in values):
        z = 1.96
        centre = (m + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(m * (1 - m) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return {"n": n, "mean": round(m, 4), "low": round(centre - half, 4), "high": round(centre + half, 4)}
    half = 1.96 * (statistics.stdev(values) if n > 1 else 0.0) / math.sqrt(n)
    return {"n": n, "mean": round(m, 4), "low": round(max(0.0, m - half), 4), "high": round(min(1.0, m + half), 4)}


def write_summary(run_dir: Path) -> Dict[str, Any]:
    config = json.loads((run_dir / "config.json").read_text())
    claims = gold(config.get("split", "test"))
    answers = latest_rows(run_dir / "answers.jsonl")
    ok = [r for r in answers if not r.get("error")]
    scores = [r for r in latest_rows_by(run_dir / "scores.jsonl", ("id", "metric")) if r.get("value") is not None] \
        if (run_dir / "scores.jsonl").exists() else []
    # The judge's reading of each answer's verdict, else the rule-based one.
    judged = {r["id"]: r["verdict"] for r in scores if r["metric"] == "verdict" and r.get("verdict")}
    for r in ok:  # while judging is incomplete, the rules read the rest
        r["verdict"] = judged.get(r["id"]) or r.get("rule_verdict")
    labelled = [r for r in ok if claims[r["id"]]["label"] in VERDICTS]
    verdict = {"accuracy": mean_ci([float(r.get("verdict") == claims[r["id"]]["label"]) for r in labelled]),
               "no_verdict": sum(1 for r in labelled if not r.get("verdict"))}
    confusion = {g: {p: sum(1 for r in labelled if claims[r["id"]]["label"] == g and (r.get("verdict") or "none") == p)
                     for p in (*VERDICTS, "none")} for g in VERDICTS}
    f1s = []
    for v in VERDICTS:
        tp = confusion[v][v]
        predicted = sum(confusion[g][v] for g in VERDICTS)
        actual = sum(confusion[v].values())
        prec, rec = (tp / predicted if predicted else 0.0), (tp / actual if actual else 0.0)
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        verdict[f"accuracy_{v.replace(' ', '_')}"] = mean_ci([float(r.get("verdict") == v) for r in labelled
                                                              if claims[r["id"]]["label"] == v])
    verdict["macro_f1"] = round(sum(f1s) / len(f1s), 4)
    # Claims whose cited abstract holds the evidence: the labels that hold in an open library too.
    verdict["accuracy_with_evidence"] = mean_ci([float(r.get("verdict") == claims[r["id"]]["label"]) for r in labelled
                                                 if claims[r["id"]]["label"] in ("supported", "refuted")])
    n_judged = sum(1 for r in ok if r["id"] in judged)
    verdict["read_by"] = "judge" if n_judged == len(ok) else "rules" if not n_judged else \
        f"judge ({n_judged}) and rules ({len(ok) - n_judged})"
    both = [r for r in ok if r["id"] in judged and r.get("rule_verdict")]
    verdict["rules_agree_with_judge"] = round(sum(judged[r["id"]] == r["rule_verdict"] for r in both) / len(both), 4) if both else None
    # Evidence: the gold abstract among the passages the answer was written from, and cited.
    with_evidence = [r for r in ok if claims[r["id"]]["evidence_docs"]]

    def gold_in(r: Dict[str, Any], cited_only: bool) -> float:
        docs = set(claims[r["id"]]["evidence_docs"])
        return float(any(c["doc"] in docs and (not cited_only or c["n"] in r.get("cited", [])) for c in r.get("contexts") or []))
    evidence = {"in_context": mean_ci([gold_in(r, False) for r in with_evidence]),
                "cited": mean_ci([gold_in(r, True) for r in with_evidence])}
    ragas = {m: mean_ci([s["value"] for s in scores if s["metric"] == m]) for m in METRICS}
    judge_errors = sum(1 for r in latest_rows_by(run_dir / "scores.jsonl", ("id", "metric")) if r.get("value") is None) \
        if (run_dir / "scores.jsonl").exists() else 0
    times = [r["total_s"] for r in ok if r.get("total_s")]
    calls = [(r.get("usage") or {}).get("calls") for r in ok]
    tokens = [(r.get("usage") or {}).get("prompt_tokens", 0) + (r.get("usage") or {}).get("completion_tokens", 0) for r in ok]
    summary = {
        "answers": len(ok), "failed_answers": len(answers) - len(ok), "verdict": verdict, "confusion": confusion,
        "evidence": evidence, "ragas": ragas, "judge_errors": judge_errors,
        "speed": {"median_s": round(statistics.median(times), 1) if times else None,
                  "p90_s": round(sorted(times)[int(0.9 * (len(times) - 1))], 1) if times else None,
                  "first_word_median_s": round(statistics.median([r["first_word_s"] for r in ok]), 1) if ok else None},
        "model_calls_per_answer": round(statistics.mean([c for c in calls if isinstance(c, (int, float))]), 2)
        if any(isinstance(c, (int, float)) for c in calls) else None,
        "tokens_per_answer": round(statistics.mean(tokens)) if tokens else None,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    (run_dir / "report.md").write_text(render(run_dir.name, config, summary, ok, claims) + "\n")
    write_history()
    return summary


def pct(x: Optional[Dict[str, Any]]) -> str:
    if not x or x.get("mean") is None:
        return "-"
    return f"{x['mean'] * 100:.1f}% ({x['low'] * 100:.0f}-{x['high'] * 100:.0f}, n={x['n']})"


def render(run: str, config: Dict[str, Any], s: Dict[str, Any], ok: List[Dict[str, Any]], claims: Dict[str, Any]) -> str:
    v, ev, rg = s["verdict"], s["evidence"], s["ragas"]
    judge = config.get("judge") or {}
    out = [f"# RAGAS run {run}", "",
           f"BEIR SciFact {config.get('split', 'test')} claims answered by OmniDoc at commit `{config['commit']}`"
           + (" with uncommitted changes" if config.get("uncommitted_changes") else "")
           + f": {s['answers']} answers ({s['failed_answers']} failed). Answer model `{config['settings']['model']}`; "
           f"the question: \"{config['question']}\". Judge: `{judge.get('model', 'not scored yet')}`"
           + (f" (RAGAS {judge.get('ragas')}, embeddings `{judge.get('embeddings')}`)" if judge else "") + ".", "",
           "| Measure | Score (95% interval, n) | Graded by |", "|---|---|---|",
           f"| Verdict accuracy (supported / refuted / not enough evidence) | **{pct(v['accuracy'])}** | {v['read_by']} read the verdict; gold label |",
           f"| Verdict accuracy on the claims with gold evidence (supported or refuted) | {pct(v['accuracy_with_evidence'])} | "
           f"{v['read_by']} read the verdict; gold label |",
           f"| Verdict macro-F1 | {v['macro_f1'] * 100:.1f}% | {v['read_by']} read the verdict; gold label |",
           f"| Gold evidence among the passages the answer was written from | {pct(ev['in_context'])} | exact |",
           f"| Gold evidence cited in the answer | {pct(ev['cited'])} | exact |",
           f"| Faithfulness | {pct(rg['faithfulness'])} | judge |",
           f"| Answer relevancy | {pct(rg['answer_relevancy'])} | judge + embeddings |",
           f"| Factual correctness (recall of the gold rationale) | {pct(rg['factual_correctness_recall'])} | judge |",
           "", "## Verdicts", "",
           f"Read by the {v['read_by']}"
           + (f" (a rule-based reading agrees on {v['rules_agree_with_judge'] * 100:.0f}% of the answers it could read)"
              if v.get("rules_agree_with_judge") is not None else "")
           + f". Accuracy by gold label: supported {pct(v['accuracy_supported'])}, refuted {pct(v['accuracy_refuted'])}, "
           f"not enough evidence {pct(v['accuracy_not_enough_evidence'])}. Answers without a verdict: {v['no_verdict']}.", "",
           "| Gold \\ answer | supported | refuted | not enough evidence | none |", "|---|---|---|---|---|"]
    for g in VERDICTS:
        out.append(f"| {g} | " + " | ".join(str(s["confusion"][g][p]) for p in (*VERDICTS, "none")) + " |")
    out += ["", "## Speed and cost", "",
            f"- Time per answer: median {s['speed']['median_s']} s, 90th percentile {s['speed']['p90_s']} s; first word "
            f"after {s['speed']['first_word_median_s']} s (median).",
            f"- Model calls per answer: {s['model_calls_per_answer']} ({s.get('tokens_per_answer')} tokens). "
            f"Judge results that failed: {s['judge_errors']}.",
            "", "## Notes", "",
            "- SciFact's \"not enough evidence\" claims have no evidence in the abstract cited with them, but another "
            "abstract of the library may bear on them (OmniDoc then answers from it and is counted wrong); the accuracy on "
            "claims with gold evidence avoids this.",
            "- Faithfulness counts the verdict word as a statement the evidence must back; a judge may not credit it.",
            "- Factual correctness is in recall mode: the gold rationale is a few sentences and a good answer says more.",
            "", "## Missed verdicts", ""]
    missed = [r for r in ok if claims[r["id"]]["label"] in VERDICTS and r.get("verdict") != claims[r["id"]]["label"]]
    for r in missed[:40]:
        out.append(f"- **{r['id']}** ({claims[r['id']]['label']} → {r.get('verdict') or 'none'}): {r['claim']}")
    if config.get("notes"):
        out += ["", f"Notes: {config['notes']}"]
    return "\n".join(out)


def write_history() -> None:
    rows = []
    for p in sorted(RESULTS.glob("*/summary.json")):
        s = json.loads(p.read_text())
        c = json.loads((p.parent / "config.json").read_text())

        def m(x: Optional[Dict[str, Any]]) -> str:
            return "-" if not x or x.get("mean") is None else f"{x['mean'] * 100:.1f}%"
        rows.append(f"| [{p.parent.name}]({p.parent.name}/report.md) | `{c['commit']}` | {s['answers']} | "
                    f"**{m(s['verdict']['accuracy'])}** | {m(s['verdict'].get('accuracy_with_evidence'))} | "
                    f"{s['verdict']['macro_f1'] * 100:.1f}% | {m(s['evidence']['in_context'])} | "
                    f"{m(s['ragas']['faithfulness'])} | {m(s['ragas']['answer_relevancy'])} | "
                    f"{m(s['ragas']['factual_correctness_recall'])} | {(c.get('judge') or {}).get('model', '-')} |")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "HISTORY.md").write_text("\n".join([
        "# RAGAS history", "",
        "Every run of `benchmarks/ragas_eval.py` on the BEIR SciFact test claims: verdicts and evidence are scored "
        "exactly, the RAGAS metrics by a judge model of another family than the answer model.", "",
        "| Run | Commit | Answers | Verdict accuracy | On claims with evidence | Macro-F1 | Gold evidence in context | "
        "Faithfulness | Answer relevancy | Factual correctness (recall) | Judge |",
        "|---|---|---|---|---|---|---|---|---|---|---|", *rows]) + "\n")


def report(args: argparse.Namespace) -> None:
    runs = [Path(args.run)] if args.run else sorted(p.parent for p in RESULTS.glob("**/answers.jsonl"))
    for run_dir in runs:
        write_summary(run_dir)
        log(f"{run_dir.name}: report rebuilt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    a = sub.add_parser("answer")
    a.add_argument("--label", required=True)
    a.add_argument("--split", choices=tuple(CLAIM_FILES), default="test",
                   help="test: the measured claims; train: other claims, for trying changes out")
    a.add_argument("--sample", type=int, default=0, help="a fixed random sample of N claims (seed 2026)")
    a.add_argument("--limit", type=int, default=0, help="only the first N claims (a smoke test, kept out of the results)")
    a.add_argument("--pause", type=int, default=PAUSE_S)
    a.add_argument("--resume", default="", help="a run folder to continue")
    a.add_argument("--code", default="", help="answer with another copy of the app (e.g. benchmarks/work/code/revD)")
    a.add_argument("--notes", default="")
    s = sub.add_parser("score")
    s.add_argument("run")
    s.add_argument("--judge", default=JUDGE)
    s.add_argument("--concurrency", type=int, default=JUDGE_CONCURRENCY)
    s.add_argument("--metrics", default="", help="comma-separated subset: verdict," + ",".join(METRICS))
    s.add_argument("--effort", default=JUDGE_EFFORT, choices=("low", "medium", "high"), help="the judge's reasoning effort")
    s.add_argument("--sample", type=int, default=0, help="judge only a fixed random sample of N claims (seed 2026)")
    r = sub.add_parser("report")
    r.add_argument("run", nargs="?", default="")
    args = parser.parse_args()
    {"fetch": fetch, "answer": answer, "score": score, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
