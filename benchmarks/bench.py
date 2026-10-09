"""
Benchmarks OmniDoc on public document question-answering benchmarks and keeps every run.

    .venv/bin/python -I benchmarks/bench.py fetch                  # questions, sampled PDFs, manifests
    .venv/bin/python -I benchmarks/bench.py run --label baseline   # ingest, ask, grade, report
    .venv/bin/python -I benchmarks/bench.py judge <run dir>        # grade (again) with the judge model
    .venv/bin/python -I benchmarks/bench.py report [<run dir>]     # rebuild summaries and HISTORY.md

Benchmarks (public, with gold answers and evidence pages):

* FinanceBench (Patronus AI, CC BY-NC 4.0): questions on real 10-K / 10-Q / 8-K filings that
  need figures, tables and financial reasoning. 36 of the 150 open-source questions, 12 of each
  type (metrics-generated, domain-relevant, novel-generated).
* MMLongBench-Doc (NeurIPS 2024 Datasets & Benchmarks): long PDFs of seven kinds (reports,
  papers, brochures, guidebooks, financial reports, tutorials, administrative files) with
  evidence in text, layout, tables, charts and figures; about a fifth of the questions are
  unanswerable. All questions of one document per kind.

The samples are drawn once with a fixed seed and stored in benchmarks/manifests/, so every
run (the baseline and each revision) answers exactly the same questions.

A run starts its own OmniDoc server on a separate port with a separate data folder
(benchmarks/work/<benchmark>), uploads the documents through the API like a user would, waits
for the background summaries, extraction and graph, then asks every question through the
streaming endpoint, scoped to its document, with web search off. The answer model, the
embedding model and the vision model are pinned, and local fallback is off, so a run never
silently switches models. Answers are graded by a judge model from another family.

Each run is stored in benchmarks/results/<date>_<label>_<commit>/: config.json, results.jsonl
(every answer with its sources, timings and model usage), judgments.jsonl, summary.json and
report.md. benchmarks/results/HISTORY.md compares all runs.
"""
import argparse
import ast
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BENCH = ROOT / "benchmarks"
DATASETS = BENCH / "datasets"   # downloads (git-ignored)
WORK = BENCH / "work"           # server data folders and logs (git-ignored)
MANIFESTS = BENCH / "manifests"
RESULTS = BENCH / "results"
PYTHON = ROOT / ".venv" / "bin" / "python"

SEED = 2026
FB_PER_TYPE = 12
FB_TYPES = ("metrics-generated", "domain-relevant", "novel-generated")
FB_QUESTIONS = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl"
FB_PDF = "https://github.com/patronus-ai/financebench/raw/main/pdfs/{doc}.pdf"
# FinanceBench numbers evidence pages from 0; OmniDoc (and MMLongBench-Doc) from 1.
FB_PAGE_OFFSET = 1
MM_QUESTIONS = "https://huggingface.co/datasets/yubo2333/MMLongBench-Doc/resolve/main/data/train-00000-of-00001.parquet"
MM_PDF = "https://huggingface.co/datasets/yubo2333/MMLongBench-Doc/resolve/main/documents/{doc}"
MM_QUESTIONS_PER_DOC = (5, 12)  # documents with a typical number of questions

PORT = 8011
DEFAULTS = {
    "provider": "nvidia",
    "model": "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "vision": "gemini:gemini-3.5-flash-lite",
    "embed": "nomic-embed-text",
    "judge": "groq:openai/gpt-oss-120b",
}
# Files whose changes alter what ingestion stores: the index is rebuilt when they change.
INDEX_FILES = ("parsing/*.py", "retrieval/*.py", "core/pipeline.py", "agents/summary_agent.py",
               "graph/extractor.py", "agents/extraction_agent.py", "agents/doc_classifier.py")
DECLINE_HINT = "declined"


# --------------------------------------------------------------------------- utils
def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def download(url: str, dest: Path) -> Path:
    import httpx
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.rename(dest)
    return dest


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest_rows(path: Path) -> List[Dict[str, Any]]:
    """Rows by id, the last one winning (a resumed run appends a new answer after a failed one)."""
    return list({r["id"]: r for r in read_jsonl(path)}.values())


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", "gc.auto=0", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def literal(value: Any, default: Any) -> Any:
    try:
        return ast.literal_eval(value) if isinstance(value, str) else (value if value is not None else default)
    except (ValueError, SyntaxError):
        return default


# --------------------------------------------------------------------------- fetch
def download_questions(bench: str) -> Path:
    if bench == "financebench":
        return download(FB_QUESTIONS, DATASETS / "financebench" / "financebench_open_source.jsonl")
    return download(MM_QUESTIONS, DATASETS / "mmlongbench" / "train.parquet")


def sample_financebench() -> Dict[str, Any]:
    """12 questions of each type; documents taken in a seeded random order until the quotas are met."""
    questions = read_jsonl(download_questions("financebench"))
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for q in questions:
        by_doc.setdefault(q["doc_name"], []).append(q)
    docs = sorted(by_doc)
    random.Random(SEED).shuffle(docs)
    quota = {t: FB_PER_TYPE for t in FB_TYPES}
    chosen: List[Dict[str, Any]] = []
    for doc in docs:
        if not any(quota.values()):
            break
        for q in sorted(by_doc[doc], key=lambda q: q["financebench_id"]):
            if quota.get(q["question_type"], 0) > 0:
                quota[q["question_type"]] -= 1
                chosen.append(q)
    return {
        "benchmark": "financebench", "seed": SEED, "source": FB_QUESTIONS,
        "selection": f"{FB_PER_TYPE} questions per question type; documents in seeded random order",
        "documents": sorted({q["doc_name"] for q in chosen}),
        "questions": [{"id": q["financebench_id"], "doc": q["doc_name"], "type": q["question_type"]} for q in chosen],
    }


def sample_mmlongbench() -> Dict[str, Any]:
    """One document per document type (with a typical number of questions), all of its questions."""
    import pandas as pd
    df = pd.read_parquet(download_questions("mmlongbench"))
    rng = random.Random(SEED)
    lo, hi = MM_QUESTIONS_PER_DOC
    counts = df.groupby("doc_id").size()
    chosen_docs = []
    for doc_type in sorted(df.doc_type.unique()):
        docs = sorted(d for d in df[df.doc_type == doc_type].doc_id.unique() if lo <= counts[d] <= hi)
        chosen_docs.append(rng.choice(docs))
    rows = df[df.doc_id.isin(chosen_docs)].reset_index()
    return {
        "benchmark": "mmlongbench", "seed": SEED, "source": MM_QUESTIONS,
        "selection": f"one document per document type with {lo}-{hi} questions; all its questions",
        "documents": sorted(chosen_docs),
        "questions": [{"id": f"mm_{int(r['index']):04d}", "doc": r["doc_id"], "type": r["doc_type"]}
                      for _, r in rows.iterrows()],
    }


def load_questions(bench: str) -> Dict[str, Dict[str, Any]]:
    """Full question records of a benchmark, by id, in a common shape."""
    out: Dict[str, Dict[str, Any]] = {}
    if bench == "financebench":
        for q in read_jsonl(DATASETS / "financebench" / "financebench_open_source.jsonl"):
            pages = sorted({int(e["evidence_page_num"]) + FB_PAGE_OFFSET for e in q.get("evidence") or []
                            if e.get("evidence_page_num") is not None})
            out[q["financebench_id"]] = {
                "question": q["question"], "answer": q["answer"], "justification": q.get("justification") or "",
                "type": q["question_type"], "reasoning": q.get("question_reasoning") or "",
                "evidence_pages": pages, "answerable": True,
            }
    else:
        import pandas as pd
        df = pd.read_parquet(DATASETS / "mmlongbench" / "train.parquet").reset_index()
        for _, r in df.iterrows():
            out[f"mm_{int(r['index']):04d}"] = {
                "question": r["question"].strip(), "answer": r["answer"], "format": r["answer_format"],
                "type": r["doc_type"], "evidence_pages": [int(p) for p in literal(r["evidence_pages"], [])],
                "evidence_sources": list(literal(r["evidence_sources"], [])),
                "answerable": r["answer"] != "Not answerable",
            }
    return out


def pdf_path(bench: str, doc: str) -> Path:
    name = doc if doc.lower().endswith(".pdf") else f"{doc}.pdf"
    return DATASETS / bench / "pdfs" / name


def fetch(args: argparse.Namespace) -> None:
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    for bench, sampler, url in (("financebench", sample_financebench, FB_PDF), ("mmlongbench", sample_mmlongbench, MM_PDF)):
        manifest_path = MANIFESTS / f"{bench}.json"
        if manifest_path.exists() and not args.resample:
            manifest = json.loads(manifest_path.read_text())
            download_questions(bench)
        else:
            manifest = sampler()
            manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
        log(f"{bench}: {len(manifest['questions'])} questions over {len(manifest['documents'])} documents")
        for doc in manifest["documents"]:
            dest = pdf_path(bench, doc)
            download(url.format(doc=doc), dest)
            if not dest.read_bytes()[:5].startswith(b"%PDF"):
                raise SystemExit(f"{dest} is not a PDF (download failed?)")
        log(f"{bench}: documents ready in {DATASETS / bench / 'pdfs'}")


# --------------------------------------------------------------------------- server
class Server:
    """An OmniDoc server with its own data folder and pinned models."""

    def __init__(self, bench: str, settings: Dict[str, str], port: int = PORT):
        self.dir = WORK / bench
        self.settings = settings
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.proc: Optional[subprocess.Popen] = None

    def env(self) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("OMNIDOC_")}
        env.update({
            "OMNIDOC_DATA_DIR": str(self.dir / "data"),
            "OMNIDOC_PORT": str(self.port),
            "OMNIDOC_LLM_PROVIDERS": self.settings["provider"],
            "OMNIDOC_LOCAL_FALLBACK": "0",
            "OMNIDOC_EMBED_MODEL": self.settings["embed"],
            "OMNIDOC_VISION_MODEL": self.settings["vision"],
            "OMNIDOC_WEB_SEARCH": "off",
        })
        return env

    def start(self) -> None:
        import httpx
        self.dir.mkdir(parents=True, exist_ok=True)
        log_file = open(self.dir / "server.log", "a")
        self.proc = subprocess.Popen([str(PYTHON), "server.py"], cwd=ROOT, env=self.env(),
                                     stdout=log_file, stderr=subprocess.STDOUT)
        for _ in range(180):
            if self.proc.poll() is not None:
                raise SystemExit(f"The benchmark server exited; see {self.dir / 'server.log'}")
            try:
                if httpx.get(f"{self.url}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise SystemExit("The benchmark server did not start within 3 minutes")
        r = httpx.put(f"{self.url}/api/models/current", json={"model": self.settings["model"]}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"Could not select {self.settings['model']}: {r.text}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def index_fingerprint(embed: str) -> str:
    h = hashlib.sha1(embed.encode())
    for pattern in INDEX_FILES:
        for f in sorted(ROOT.glob(pattern)):
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def ensure_index(bench: str, manifest: Dict[str, Any], settings: Dict[str, str], reingest: bool,
                 wait: bool = False) -> Dict[str, Any]:
    """
    The documents of a benchmark indexed in its own data folder. Ingestion is reused while the
    parsing / indexing code and the embedding model are unchanged, and redone otherwise.
    ``wait`` waits for an index another process (``bench.py index``) is building instead.
    """
    state_path = WORK / bench / "index.json"
    fingerprint = index_fingerprint(settings["embed"])

    def current() -> Dict[str, Any]:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        ok = state.get("fingerprint") == fingerprint and set(state.get("docs", {})) >= set(manifest["documents"])
        return state if ok else {}

    if wait and not reingest and not current():
        log(f"{bench}: waiting for the index being built by another process ({fingerprint})")
        deadline = time.time() + 6 * 3600
        while not current() and time.time() < deadline:
            time.sleep(60)
    state = current()
    if state and not reingest:
        log(f"{bench}: reusing the index built by {state.get('commit')} ({fingerprint})")
        return state
    if wait:
        raise SystemExit(f"{bench}: no finished index with fingerprint {fingerprint} appeared")
    if (WORK / bench / "data").exists():
        log(f"{bench}: indexing code changed (or --reingest): rebuilding the index")
        shutil.rmtree(WORK / bench / "data")
    return {"fingerprint": fingerprint, "commit": git("rev-parse", "--short", "HEAD"), "docs": {}, "pending": True}


def ingest(server: Server, bench: str, manifest: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    if not state.get("pending"):
        return state
    docs: Dict[str, Any] = {}
    for doc in manifest["documents"]:
        path = pdf_path(bench, doc)
        started = time.perf_counter()
        with open(path, "rb") as f:
            r = httpx.post(f"{server.url}/api/documents/upload", files={"file": (path.name, f, "application/pdf")}, timeout=1800)
        if r.status_code != 200:
            raise SystemExit(f"Upload of {doc} failed: {r.status_code} {r.text[:300]}")
        info = r.json()
        docs[doc] = {"doc_id": info["doc_id"], "upload_s": round(time.perf_counter() - started, 1),
                     "chunks": info.get("chunk_count"), "tables": info.get("table_count"), "ocr_pages": info.get("ocr_pages")}
        log(f"{bench}: uploaded {doc} in {docs[doc]['upload_s']}s ({docs[doc]['chunks']} chunks)")
    # Summaries, contextual re-indexing, field extraction and the graph run in the background.
    started = time.perf_counter()
    ids = {v["doc_id"]: k for k, v in docs.items()}
    finished: Dict[str, float] = {}
    while len(finished) < len(ids):
        time.sleep(15)
        listed = httpx.get(f"{server.url}/api/documents", timeout=60).json()["documents"]
        for d in listed:
            status = (d.get("graph_status") or {}).get("status")
            if d["id"] in ids and d["id"] not in finished and status in (None, "done", "failed", "cancelled"):
                finished[d["id"]] = time.perf_counter() - started
                docs[ids[d["id"]]]["background_status"] = status or "none"
                docs[ids[d["id"]]]["has_summary"] = d.get("has_summary")
                docs[ids[d["id"]]]["pages"] = d.get("pages")
        if time.perf_counter() - started > 4 * 3600:
            raise SystemExit("Background processing did not finish within 4 hours")
    log(f"{bench}: background processing finished in {time.perf_counter() - started:.0f}s")
    state.update(docs=docs, pending=False, background_s=round(time.perf_counter() - started, 1),
                 built=dt.datetime.now().isoformat(timespec="seconds"))
    (WORK / bench / "index.json").write_text(json.dumps(state, indent=1) + "\n")
    return state


# --------------------------------------------------------------------------- ask
def sse_events(response: Any) -> Iterator[Tuple[str, Any]]:
    event, data = "message", []
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            yield event, json.loads("\n".join(data))
            event, data = "message", []


def ask(server: Server, doc_id: str, question: str) -> Dict[str, Any]:
    import httpx
    chat = httpx.post(f"{server.url}/api/chats", json={"title": "benchmark"}, timeout=30).json()["chat"]
    started = time.perf_counter()
    first_word = None
    result: Dict[str, Any] = {}
    error = ""
    with httpx.stream("POST", f"{server.url}/api/chats/{chat['id']}/query/stream",
                      json={"query": question, "document_ids": [doc_id], "web": "off"}, timeout=900) as r:
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        for event, data in sse_events(r):
            if event == "delta" and first_word is None:
                first_word = time.perf_counter() - started
            elif event == "result":
                result = data
            elif event == "error":
                error = data.get("message", "error")
    total = time.perf_counter() - started
    if not result:
        return {"error": error or "no result"}
    answer = result.get("answer") or ""
    return {
        "answer": answer,
        "sources": [{k: s.get(k) for k in ("n", "kind", "doc_id", "page", "section")} for s in result.get("sources") or []],
        "cited": sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)}),
        "verification": {k: (result.get("verification") or {}).get(k) for k in ("status", "score", "supported", "unsupported")},
        "usage": result.get("usage") or {},
        "steps": [{"node": s.get("node"), "ms": s.get("duration_ms")} for s in result.get("steps") or []],
        "model": result.get("model"),
        "first_word_s": round(first_word if first_word is not None else total, 2),
        "total_s": round(total, 2),
        "error": error,
    }


def run(args: argparse.Namespace) -> None:
    settings = {k: getattr(args, k) or v for k, v in DEFAULTS.items()}
    benches = [b.strip() for b in args.bench.split(",") if b.strip()]
    commit = git("rev-parse", "--short", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    # Smoke tests (--limit) stay out of the results history.
    base = WORK / "smoke" if args.limit else RESULTS
    run_dir = Path(args.resume) if args.resume else base / f"{dt.date.today():%Y-%m-%d}_{args.label}_{commit}"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({
            "label": args.label, "started": dt.datetime.now().isoformat(timespec="seconds"),
            "commit": commit, "uncommitted_changes": dirty, "benchmarks": benches, "settings": settings,
            "scope": "each question is asked about its own document (document_ids = [doc]); web search off",
            "notes": args.notes or "",
        }, indent=1) + "\n")
    results_path = run_dir / "results.jsonl"
    done = {r["id"] for r in read_jsonl(results_path) if not r.get("error")}
    for bench in benches:
        manifest = json.loads((MANIFESTS / f"{bench}.json").read_text())
        questions = load_questions(bench)
        server = Server(bench, settings, args.port)
        state = ensure_index(bench, manifest, settings, args.reingest, args.wait_index)
        server.start()
        try:
            state = ingest(server, bench, manifest, state)
            todo = [q for q in manifest["questions"] if q["id"] not in done][: args.limit or None]
            log(f"{bench}: asking {len(todo)} questions")
            for i, q in enumerate(todo, 1):
                gold = questions[q["id"]]
                doc = state["docs"][q["doc"]]
                out: Dict[str, Any] = {}
                for attempt in range(1, 4):
                    try:
                        out = ask(server, doc["doc_id"], gold["question"])
                    except Exception as e:  # network trouble: retry
                        out = {"error": f"{type(e).__name__}: {e}"}
                    if not out.get("error") and out.get("answer"):
                        break
                    log(f"  {q['id']}: {out.get('error') or 'empty answer'}; retrying in 30s")
                    time.sleep(30)
                reference = {("answer_gold" if k == "answer" else k): v for k, v in gold.items()}
                row = {"id": q["id"], "benchmark": bench, "doc": q["doc"], "doc_id": doc["doc_id"], **reference,
                       **out, "attempts": attempt}
                append_jsonl(results_path, row)
                log(f"  [{i}/{len(todo)}] {q['id']} {row.get('total_s', '-')}s {'ERROR ' + row['error'] if row.get('error') else ''}")
        finally:
            server.stop()
        index = {k: v for k, v in state.items() if k != "pending"}
        (run_dir / f"index_{bench}.json").write_text(json.dumps(index, indent=1) + "\n")
    if not args.no_judge:
        judge(argparse.Namespace(run_dir=str(run_dir), judge=settings["judge"], regrade=False))
    report(argparse.Namespace(run_dir=str(run_dir)))


def build_index(args: argparse.Namespace) -> None:
    """Ingests the documents of the benchmarks without asking anything (runs reuse the index)."""
    settings = {k: getattr(args, k) or v for k, v in DEFAULTS.items()}
    for bench in [b.strip() for b in args.bench.split(",") if b.strip()]:
        manifest = json.loads((MANIFESTS / f"{bench}.json").read_text())
        state = ensure_index(bench, manifest, settings, args.reingest)
        if not state.get("pending"):
            continue
        server = Server(bench, settings, args.port)
        server.start()
        try:
            ingest(server, bench, manifest, state)
        finally:
            server.stop()


# --------------------------------------------------------------------------- judge
JUDGE_PROMPT = """You grade answers from a document question-answering assistant against a reference answer.

QUESTION: {question}
REFERENCE ANSWER: {answer}
{extra}
ASSISTANT'S RESPONSE:
\"\"\"
{response}
\"\"\"

Decide two things.
1. declined: true when the response does not commit to an answer (it says the document does not
   contain the information, that it cannot be determined, or only asks for more information);
   false when it gives an answer, even a hedged or partial one.
2. correct:
   - If the reference answer is "Not answerable", correct is true only when the response declines
     or clearly says the document does not provide this information.
   - Otherwise correct is true when the response's answer matches the reference: the same figures
     allowing rounding and differences of unit or scale (1,577 million = $1.577 billion; 0.25 = 25%),
     the same entity or meaning for text, every item for lists (order only matters when the question
     asks for an order), and the same yes/no conclusion. Extra correct detail is fine; a wrong,
     contradicting or missing key figure is not. When the response gives several candidate answers,
     judge its final answer.
Return JSON only: {{"declined": true or false, "correct": true or false, "reason": "<one short sentence>"}}"""


def grade(judge_spec: str, row: Dict[str, Any]) -> Dict[str, Any]:
    from agents import llm_providers as P
    provider, model = P.parse_spec(judge_spec)
    p = P.REGISTRY[provider]
    if row["benchmark"] == "financebench":
        extra = f"REFERENCE JUSTIFICATION: {row.get('justification') or '-'}"
    else:
        extra = f"ANSWER FORMAT: {row.get('format')}"
    prompt = JUDGE_PROMPT.format(question=row["question"], answer=row["answer_gold"], extra=extra,
                                 response=(row.get("answer") or "(no answer)")[:12000])
    for attempt in range(6):
        try:
            text = P.openai_chat(p, model, [{"role": "user", "content": prompt}], temperature=0.0,
                                 max_tokens=300, json_mode=True)
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            return {"declined": bool(data.get("declined")), "correct": bool(data.get("correct")),
                    "reason": str(data.get("reason") or "")[:300]}
        except Exception as e:
            wait = 20 * (attempt + 1)
            log(f"  judge failed for {row['id']} ({type(e).__name__}: {str(e)[:120]}); retrying in {wait}s")
            time.sleep(wait)
    return {"declined": None, "correct": None, "reason": "judge failed"}


def judge(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    judge_spec = args.judge or json.loads((run_dir / "config.json").read_text())["settings"]["judge"]
    path = run_dir / "judgments.jsonl"
    if args.regrade and path.exists():
        path.unlink()
    graded = {j["id"]: j for j in read_jsonl(path) if j.get("correct") is not None}
    answers = latest_rows(run_dir / "results.jsonl")
    # Grade answers not graded yet, and answers that replaced a failed attempt.
    rows = [r for r in answers if r["id"] not in graded or (graded[r["id"]].get("reason", "").startswith("no answer")
                                                           and not r.get("error"))]
    log(f"grading {len(rows)} answers with {judge_spec}")
    for r in rows:
        if r.get("error") or not r.get("answer"):
            verdict = {"declined": True, "correct": False, "reason": f"no answer ({r.get('error') or 'empty'})"}
        else:
            verdict = grade(judge_spec, r)
        append_jsonl(path, {"id": r["id"], "judge": judge_spec, **verdict})


# --------------------------------------------------------------------------- report
def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def quantile(values: List[float], q: float) -> Optional[float]:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    correct = sum(1 for r in rows if r["j"].get("correct"))
    declined = sum(1 for r in rows if r["j"].get("declined") and not r["j"].get("correct"))
    wrong = n - correct - declined
    lo, hi = wilson(correct, n)
    answerable = [r for r in rows if r.get("answerable", True)]
    unanswerable = [r for r in rows if not r.get("answerable", True)]
    with_pages = [r for r in answerable if r.get("evidence_pages") and r.get("sources")]

    def page_hit(r: Dict[str, Any], cited_only: bool) -> bool:
        gold = set(r["evidence_pages"])
        cited = set(r.get("cited") or [])
        return any(s.get("page") in gold for s in r["sources"]
                   if s.get("doc_id") == r["doc_id"] and (not cited_only or s.get("n") in cited))

    ok = [r for r in rows if not r.get("error")]  # speed and cost of the answers that completed
    attempted = [r for r in rows if not r["j"].get("declined")]
    precision = (sum(1 for r in attempted if r["j"].get("correct") and r.get("answerable", True)) / len(attempted)) if attempted else None
    recall = (sum(1 for r in answerable if r["j"].get("correct")) / len(answerable)) if answerable else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    usage = [r.get("usage") or {} for r in ok]
    return {
        "n": n, "accuracy": correct / n if n else None, "accuracy_ci95": [lo, hi],
        "wrong": wrong / n if n else None, "declined": declined / n if n else None,
        "answerable_accuracy": recall,
        "unanswerable_n": len(unanswerable),
        "unanswerable_accuracy": (sum(1 for r in unanswerable if r["j"].get("correct")) / len(unanswerable)) if unanswerable else None,
        "f1": f1,
        "gold_page_retrieved": (sum(page_hit(r, False) for r in with_pages) / len(with_pages)) if with_pages else None,
        "gold_page_cited": (sum(page_hit(r, True) for r in with_pages) / len(with_pages)) if with_pages else None,
        "first_word_p50_s": quantile([r.get("first_word_s") for r in ok], 0.5),
        "first_word_p90_s": quantile([r.get("first_word_s") for r in ok], 0.9),
        "answer_p50_s": quantile([r.get("total_s") for r in ok], 0.5),
        "answer_p90_s": quantile([r.get("total_s") for r in ok], 0.9),
        "model_calls_mean": statistics.mean([u.get("calls", 0) for u in usage]) if usage else None,
        "tokens_mean": statistics.mean([u.get("prompt_tokens", 0) + u.get("completion_tokens", 0) for u in usage]) if usage else None,
        "errors": sum(1 for r in rows if r.get("error")),
        "verified_mean": statistics.mean([r["verification"]["score"] for r in ok
                                          if (r.get("verification") or {}).get("score") is not None] or [0]),
    }


def breakdown(rows: List[Dict[str, Any]], key) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        for k in key(r):
            groups.setdefault(k, []).append(r)
    return {k: {"n": len(v), "accuracy": sum(1 for r in v if r["j"].get("correct")) / len(v)} for k, v in sorted(groups.items())}


def evidence_kinds(r: Dict[str, Any]) -> List[str]:
    if not r.get("answerable", True):
        return ["Not answerable"]
    kinds = [re.sub(r"\s*\(.*\)", "", s) for s in r.get("evidence_sources") or []] or ["(unspecified)"]
    kinds = kinds + (["Multi-page"] if len(r.get("evidence_pages") or []) > 1 else ["Single-page"])
    return kinds


def report(args: argparse.Namespace) -> None:
    run_dirs = [Path(args.run_dir)] if getattr(args, "run_dir", None) else sorted(p for p in RESULTS.iterdir() if (p / "results.jsonl").exists())
    for run_dir in run_dirs:
        config = json.loads((run_dir / "config.json").read_text())
        verdicts = {j["id"]: j for j in read_jsonl(run_dir / "judgments.jsonl")}
        rows = []
        for r in latest_rows(run_dir / "results.jsonl"):
            r["j"] = verdicts.get(r["id"], {})
            rows.append(r)
        summary: Dict[str, Any] = {"run": run_dir.name, "label": config["label"], "commit": config["commit"],
                                   "uncommitted_changes": config.get("uncommitted_changes"), "settings": config["settings"],
                                   "graded": sum(1 for r in rows if r["j"].get("correct") is not None), "benchmarks": {}}
        for bench in config["benchmarks"]:
            br = [r for r in rows if r["benchmark"] == bench]
            if not br:
                continue
            s = summarize(br)
            if bench == "financebench":
                s["by_type"] = breakdown(br, lambda r: [r["type"]])
                s["by_reasoning"] = breakdown(br, lambda r: [r.get("reasoning") or "-"])
            else:
                s["by_evidence"] = breakdown(br, evidence_kinds)
                s["by_doc_type"] = breakdown(br, lambda r: [r["type"]])
            index_path = run_dir / f"index_{bench}.json"
            if index_path.exists():
                index = json.loads(index_path.read_text())
                docs = index.get("docs", {}).values()
                s["ingestion"] = {"documents": len(docs), "chunks": sum(d.get("chunks") or 0 for d in docs),
                                  "upload_s": round(sum(d.get("upload_s") or 0 for d in docs), 1),
                                  "background_s": index.get("background_s"), "index_commit": index.get("commit")}
            summary["benchmarks"][bench] = s
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
        (run_dir / "report.md").write_text(render_report(summary, rows) + "\n")
        log(f"report written to {run_dir / 'report.md'}")
    write_history()


NAMES = {"financebench": "FinanceBench", "mmlongbench": "MMLongBench-Doc"}


def render_report(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    st = summary["settings"]
    out = [f"# Benchmark run {summary['run']}", "",
           f"Commit `{summary['commit']}`{' (with uncommitted changes)' if summary.get('uncommitted_changes') else ''}. "
           f"Answer model `{st['model']}` (provider `{st['provider']}` only, no fallback), vision `{st['vision']}`, "
           f"embeddings `{st['embed']}`, judge `{st['judge']}`. Each question is asked about its own document, web search off.", ""]
    for bench, s in summary["benchmarks"].items():
        lo, hi = s["accuracy_ci95"]
        out += [f"## {NAMES.get(bench, bench)} ({s['n']} questions)", "",
                "| Metric | Value |", "|---|---|",
                f"| Accuracy | **{pct(s['accuracy'])}** (95% CI {pct(lo)}–{pct(hi)}) |",
                f"| Wrong answers | {pct(s['wrong'])} |",
                f"| Declined to answer | {pct(s['declined'])} |"]
        if s.get("unanswerable_n"):
            out += [f"| Accuracy on answerable questions | {pct(s['answerable_accuracy'])} |",
                    f"| Unanswerable questions correctly declined ({s['unanswerable_n']}) | {pct(s['unanswerable_accuracy'])} |",
                    f"| F1 (MMLongBench-Doc definition) | {pct(s['f1'])} |"]
        out += [f"| Gold page among the sources | {pct(s['gold_page_retrieved'])} |",
                f"| Gold page among the cited sources | {pct(s['gold_page_cited'])} |",
                f"| First word, median / p90 | {fmt_s(s['first_word_p50_s'])} / {fmt_s(s['first_word_p90_s'])} |",
                f"| Full answer, median / p90 | {fmt_s(s['answer_p50_s'])} / {fmt_s(s['answer_p90_s'])} |",
                f"| Model calls per question | {s['model_calls_mean']:.1f} |" if s.get("model_calls_mean") is not None else "| Model calls per question | - |",
                f"| Tokens per question | {s['tokens_mean']:.0f} |" if s.get("tokens_mean") is not None else "| Tokens per question | - |",
                f"| Answers with errors | {s['errors']} |"]
        if s.get("ingestion"):
            ing = s["ingestion"]
            out.append(f"| Ingestion | {ing['documents']} documents, {ing['chunks']} chunks; upload {ing['upload_s']}s, "
                       f"background {ing['background_s']}s (index built at `{ing['index_commit']}`) |")
        for title, key in (("By question type", "by_type"), ("By reasoning", "by_reasoning"),
                           ("By evidence", "by_evidence"), ("By document type", "by_doc_type")):
            if s.get(key):
                out += ["", f"**{title}**", "", "| Group | Questions | Accuracy |", "|---|---|---|"]
                out += [f"| {k} | {v['n']} | {pct(v['accuracy'])} |" for k, v in s[key].items()]
        misses = [r for r in rows if r["benchmark"] == bench and r["j"].get("correct") is False]
        if misses:
            out += ["", "**Missed questions**", "", "| Id | Question | Reference | Grader's reason |", "|---|---|---|---|"]
            for r in misses:
                out.append(f"| {r['id']} | {clip(r['question'], 110)} | {clip(str(r['answer_gold']), 60)} | {clip(r['j'].get('reason', ''), 120)} |")
        out.append("")
    return "\n".join(out)


def fmt_s(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.1f}s"


def clip(text: str, n: int) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= n else text[: n - 1] + "…"


def write_history() -> None:
    rows = []
    for p in sorted(RESULTS.glob("*/summary.json")):
        s = json.loads(p.read_text())
        fb = s["benchmarks"].get("financebench", {})
        mm = s["benchmarks"].get("mmlongbench", {})
        both = [b for b in (fb, mm) if b]
        rows.append("| " + " | ".join([
            f"[{s['run']}]({s['run']}/report.md)", f"`{s['commit']}`", s["settings"]["model"].split(":", 1)[-1],
            pct(fb.get("accuracy")), pct(mm.get("accuracy")), pct(mm.get("f1")), pct(mm.get("unanswerable_accuracy")),
            pct(statistics.mean([b["gold_page_cited"] for b in both if b.get("gold_page_cited") is not None])
                if any(b.get("gold_page_cited") is not None for b in both) else None),
            fmt_s(statistics.median([b["first_word_p50_s"] for b in both if b.get("first_word_p50_s") is not None])
                  if any(b.get("first_word_p50_s") is not None for b in both) else None),
            fmt_s(statistics.median([b["answer_p50_s"] for b in both if b.get("answer_p50_s") is not None])
                  if any(b.get("answer_p50_s") is not None for b in both) else None),
            f"{statistics.mean([b['model_calls_mean'] for b in both if b.get('model_calls_mean') is not None]):.1f}"
            if any(b.get("model_calls_mean") is not None for b in both) else "-",
        ]) + " |")
    text = ["# Benchmark history", "",
            "Every run of `benchmarks/bench.py` on the same fixed question sets (see `benchmarks/README.md`).",
            "Accuracy is graded by the judge model against the benchmark's reference answers.", "",
            "| Run | Commit | Answer model | FinanceBench | MMLongBench-Doc | MMLB F1 | Unanswerable declined | Gold page cited | First word (median) | Full answer (median) | Model calls / question |",
            "|---|---|---|---|---|---|---|---|---|---|---|", *rows]
    (RESULTS / "HISTORY.md").write_text("\n".join(text) + "\n")


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download the questions and sampled documents, write the manifests")
    f.add_argument("--resample", action="store_true", help="draw new samples (changes the question sets!)")
    r = sub.add_parser("run", help="ingest, ask, grade and report")
    r.add_argument("--label", required=True, help="name of the run, e.g. baseline or after-table-fix")
    r.add_argument("--bench", default="financebench,mmlongbench")
    r.add_argument("--notes", default="")
    r.add_argument("--limit", type=int, default=0, help="ask only the first N questions per benchmark (smoke test)")
    r.add_argument("--reingest", action="store_true", help="rebuild the index even if the indexing code is unchanged")
    r.add_argument("--resume", default="", help="continue an interrupted run in this run folder")
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--wait-index", action="store_true", help="wait for an index that `bench.py index` is building")
    ix = sub.add_parser("index", help="ingest the documents only (a later run reuses the index)")
    ix.add_argument("--bench", default="financebench,mmlongbench")
    ix.add_argument("--reingest", action="store_true")
    for cmd in (r, ix):
        cmd.add_argument("--port", type=int, default=PORT)
        for k in DEFAULTS:
            cmd.add_argument(f"--{k}", default="", help=f"default {DEFAULTS[k]}")
    j = sub.add_parser("judge", help="grade a run")
    j.add_argument("run_dir")
    j.add_argument("--judge", default="")
    j.add_argument("--regrade", action="store_true")
    rep = sub.add_parser("report", help="rebuild summaries and HISTORY.md")
    rep.add_argument("run_dir", nargs="?", default="")
    args = parser.parse_args()
    {"fetch": fetch, "run": run, "index": build_index, "judge": judge, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
