"""
Retrieval benchmark on BEIR (Thakur et al., NeurIPS 2021 Datasets & Benchmarks): does OmniDoc's
search find the documents that answer a question? Scored with the standard formulas (nDCG@10,
MRR@10, Recall@k) against the benchmark's relevance judgements; no model grades anything, so the
numbers compare directly with published retrievers.

    .venv/bin/python -I benchmarks/beir.py fetch                  # SciFact: 5,183 abstracts, 300 test claims
    .venv/bin/python -I benchmarks/beir.py run --label baseline   # index (once), search, score, report
    .venv/bin/python -I benchmarks/beir.py run --label try-x --split train   # try a change on 809 other claims

The corpus is indexed with OmniDoc's own code in one batch: the chunker used for uploads, the
passage context the app embeds and keyword-indexes (document title, then the passage), the
embedding model and the LanceDB store with its BM25 index. Every mode searches that index:

* bm25: keyword search alone; dense: embeddings alone (exact cosine search);
* hybrid: both fused with RRF, as the store's hybrid search does;
* omnidoc: the search a question gets in the app: the queries the app derives without a model
  (the question, plus the names filings use when it names financial terms), CANDIDATES_PER_QUERY
  hybrid candidates per query fused, up to POOL_SIZE of them reranked by the cross-encoder, and
  the top FINAL_TOP_K passages handed to the writer. Its documents are those of these passages,
  so it has no Recall@100;
* rerank-100: the cross-encoder reranks the passages of the 100 best hybrid documents (the usual
  BEIR reranking setup), to show what a larger pool would give.

The app may add rephrasings from its understanding step, which needs a model; questions are
searched as written here. A document ranks by its best passage. Each run is stored in
benchmarks/results/retrieval/<date>_<dataset>_<label>_<commit>/ with config.json, metrics.json,
rankings.jsonl (the relevant and top 10 documents per question and mode) and report.md;
HISTORY.md there compares the runs. Changes are tried out on the train questions first
(``--split train``; stored under results/retrieval/dev/, out of the history), so the test
questions only measure a finished change.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import shutil
import statistics
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.bench import download, git, log  # noqa: E402

BEIR_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{name}.zip"
DATASETS = ROOT / "benchmarks" / "datasets" / "beir"   # git-ignored; read from the zip, never extracted
WORK = ROOT / "benchmarks" / "work"                    # indexes (git-ignored)
RESULTS = ROOT / "benchmarks" / "results" / "retrieval"
EMBED_MODEL = "nomic-embed-text"
SPLITS = ("test", "train")
MODES = ("bm25", "dense", "hybrid", "omnidoc", "rerank-100")
SHALLOW = ("omnidoc", "rerank-100")  # rank only their pool: Recall@100 is not theirs to report
DEPTH = 100         # documents ranked per question
CHUNK_DEPTH = 250   # passages fetched to fill DEPTH documents (a long abstract has two or three)
# Published nDCG@10 on the same test questions, for orientation (setups differ).
REFERENCES = {
    "scifact": [("BM25, Elasticsearch [1]", 0.665), ("BM25, Pyserini [2]", 0.679), ("ColBERT [1]", 0.671),
                ("BM25 top 100 reranked by MiniLM-L6, the cross-encoder OmniDoc uses [1]", 0.688),
                ("BM25 top 100 reranked by monoT5-220M [2]", 0.734), ("BM25 top 100 reranked by Cohere Rerank v2 [2]", 0.744),
                ("BM25 top 100 reranked by GPT-4 [2]", 0.750), ("BM25 top 100 reranked by monoT5-3B [2]", 0.766)],
}
REFERENCE_SOURCES = ["[1] Thakur et al. 2021, BEIR, table 2, https://arxiv.org/abs/2104.08663",
                     "[2] Sun et al. 2023, Is ChatGPT Good at Search?, table 1, https://arxiv.org/abs/2304.09542"]


# --------------------------------------------------------------------------- data
def fetch(args: argparse.Namespace) -> None:
    path = download(BEIR_URL.format(name=args.dataset), DATASETS / f"{args.dataset}.zip")
    corpus, _, qrels = load(args.dataset)
    train = load(args.dataset, "train")[2]
    log(f"{args.dataset}: {len(corpus)} documents, {len(qrels)} test and {len(train)} train questions with judgements ({path})")


def load(name: str, split: str = "test") -> Tuple[Dict[str, Dict[str, str]], Dict[str, str], Dict[str, Dict[str, int]]]:
    """Corpus id -> {title, text}; question id -> text; judged question id of the split -> {relevant corpus id: grade}."""
    with zipfile.ZipFile(DATASETS / f"{name}.zip") as zf:
        def rows(member: str):
            with zf.open(f"{name}/{member}") as f:
                for line in io.TextIOWrapper(f, encoding="utf-8"):
                    if line.strip():
                        yield json.loads(line)
        corpus = {str(d["_id"]): {"title": str(d.get("title") or ""), "text": str(d.get("text") or "")}
                  for d in rows("corpus.jsonl")}
        queries = {str(q["_id"]): str(q["text"]) for q in rows("queries.jsonl")}
        qrels: Dict[str, Dict[str, int]] = {}
        with zf.open(f"{name}/qrels/{split}.tsv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t"):
                if int(row["score"]) > 0:
                    qrels.setdefault(str(row["query-id"]), {})[str(row["corpus-id"])] = int(row["score"])
    return corpus, queries, qrels


# --------------------------------------------------------------------------- index
def fingerprint() -> str:
    """The indexing code and the embedding model: the index is rebuilt when either changes."""
    h = hashlib.sha1(EMBED_MODEL.encode())
    for rel in ("parsing/docling_parser.py", "retrieval/embeddings.py", "retrieval/lancedb_store.py", "core/pipeline.py"):
        h.update((ROOT / rel).read_bytes())
    return h.hexdigest()[:12]


def doc_key(corpus_id: str) -> str:
    """A document id the store accepts (letters, digits and underscores)."""
    return "doc_" + "".join(ch if ch.isalnum() else "_" for ch in corpus_id)


def build_index(name: str, corpus: Dict[str, Dict[str, str]], work: Path) -> Dict[str, Any]:
    """Chunks, embeds and stores the corpus with OmniDoc's own code (once per fingerprint)."""
    from core.pipeline import contextual_text
    from parsing.docling_parser import chunk_blocks
    from retrieval.embeddings import EmbeddingService
    from retrieval.lancedb_store import LanceDBStore
    state_path = work / "index.json"
    fp = fingerprint()
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get("fingerprint") == fp and state.get("documents") == len(corpus):
            log(f"{name}: reusing the index built at {state.get('commit')} ({fp})")
            return state
    if (work / "lancedb").exists():
        shutil.rmtree(work / "lancedb")
    started = time.perf_counter()
    chunks, texts = [], []
    for cid, doc in corpus.items():
        for ch in chunk_blocks(doc_key(cid), [(1, "", doc["text"])], paged=False):
            chunks.append(ch)
            texts.append(contextual_text(doc["title"], ch.section_title, ch.text))
    log(f"{name}: {len(corpus)} documents -> {len(chunks)} passages; embedding them with {EMBED_MODEL}")
    vectors = EmbeddingService(model_name=EMBED_MODEL, cache_dir=str(work / "embeddings")).embed_texts(texts)
    failed = sum(1 for v in vectors if not any(v))
    LanceDBStore(db_dir=str(work / "lancedb")).add_chunks(chunks, vectors, search_texts=texts)
    state = {"fingerprint": fp, "commit": git("rev-parse", "--short", "HEAD"), "documents": len(corpus),
             "passages": len(chunks), "failed_embeddings": failed, "seconds": round(time.perf_counter() - started, 1),
             "built": dt.datetime.now().isoformat(timespec="seconds")}
    state_path.write_text(json.dumps(state, indent=1) + "\n")
    log(f"{name}: indexed in {state['seconds']}s ({failed} passages could not be embedded)")
    return state


# --------------------------------------------------------------------------- search
def documents(doc_keys: List[str], keys: Dict[str, str]) -> List[str]:
    """Corpus ids in the order of their best passage."""
    out: List[str] = []
    for k in doc_keys:
        cid = keys.get(k)
        if cid is not None and cid not in out:
            out.append(cid)
    return out


def search_all(queries: Dict[str, str], ids: List[str], keys: Dict[str, str], work: Path) -> Tuple[Dict[str, Dict[str, List[str]]], Dict[str, Any]]:
    """Question id -> mode -> ranked corpus ids, and timings of the app's search."""
    from agents.hybrid_agent import HybridRetrievalAgent
    from retrieval.embeddings import EmbeddingService
    from retrieval.lancedb_store import LanceDBStore
    from retrieval.reranker import ChunkReranker
    embed = EmbeddingService(model_name=EMBED_MODEL, cache_dir=str(work / "embeddings"))
    store = LanceDBStore(db_dir=str(work / "lancedb"))
    reranker = ChunkReranker()
    agent = HybridRetrievalAgent(embed, store, reranker)
    out: Dict[str, Dict[str, List[str]]] = {}
    seconds: List[float] = []
    extra_queries = 0
    for i, qid in enumerate(ids, 1):
        q = queries[qid]
        started = time.perf_counter()
        app_queries = agent._queries({"user_query": q})
        top, _ = agent.search(app_queries)
        seconds.append(time.perf_counter() - started)
        extra_queries += len(app_queries) > 1
        vec = embed.embed_queries([q])[0]
        hybrid = store.hybrid_search(query=q, query_vector=vec, top_k=CHUNK_DEPTH)
        ranked = documents([h.doc_id for h in hybrid], keys)[:DEPTH]
        pool = [h for h in hybrid if keys.get(h.doc_id) in set(ranked)]
        scores = reranker.score_pairs(q, [h.text for h in pool])
        reranked = [pool[j] for j in sorted(range(len(pool)), key=lambda j: (-scores[j], j))]
        out[qid] = {
            "bm25": documents([str(r["doc_id"]) for r in store._fts_search(q, CHUNK_DEPTH, None)], keys)[:DEPTH],
            "dense": documents([str(r["doc_id"]) for r in store._vector_search(vec, CHUNK_DEPTH, None)], keys)[:DEPTH],
            "hybrid": ranked,
            "omnidoc": documents([c.doc_id for c in top], keys),
            "rerank-100": documents([h.doc_id for h in reranked], keys),
        }
        if i % 50 == 0:
            log(f"  {i}/{len(ids)} questions searched")
    timing = {"omnidoc_search_median_s": round(statistics.median(seconds), 3),
              "omnidoc_search_p90_s": round(sorted(seconds)[int(0.9 * (len(seconds) - 1))], 3),
              "questions_with_finance_terms_query": extra_queries}
    return out, timing


# --------------------------------------------------------------------------- metrics
def metrics(rankings: Dict[str, Dict[str, List[str]]], qrels: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
    """
    Means over the judged questions: nDCG@10 (graded gains, log2 discount, as trec_eval), MRR@10,
    Recall@10, Recall@100 and hit@10 (at least one relevant document in the top 10).
    """
    out: Dict[str, Dict[str, Any]] = {}
    for mode in MODES:
        per: Dict[str, List[float]] = {"ndcg@10": [], "mrr@10": [], "recall@10": [], "recall@100": [], "hit@10": []}
        for qid, rel in qrels.items():
            ranked = rankings[qid][mode]
            top = ranked[:10]
            dcg = sum(rel.get(d, 0) / math.log2(i + 2) for i, d in enumerate(top))
            ideal = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(rel.values(), reverse=True)[:10]))
            per["ndcg@10"].append(dcg / ideal)
            per["mrr@10"].append(next((1.0 / (i + 1) for i, d in enumerate(top) if d in rel), 0.0))
            per["recall@10"].append(len(set(top) & set(rel)) / len(rel))
            per["recall@100"].append(len(set(ranked[:100]) & set(rel)) / len(rel))
            per["hit@10"].append(float(bool(set(top) & set(rel))))
        out[mode] = {m: round(sum(v) / len(v), 4) for m, v in per.items()}
        if mode in SHALLOW:
            out[mode]["recall@100"] = None
    return out


# --------------------------------------------------------------------------- run
def run(args: argparse.Namespace) -> None:
    name = args.dataset
    corpus, queries, qrels = load(name, args.split)
    work = WORK / f"beir-{name}"
    work.mkdir(parents=True, exist_ok=True)
    index = build_index(name, corpus, work)
    ids = [q for q in qrels if q in queries]
    if args.limit:
        ids = ids[:args.limit]
    log(f"{name}: searching {len(ids)} {args.split} questions in {len(MODES)} modes")
    started = time.perf_counter()
    rankings, timing = search_all(queries, ids, {doc_key(c): c for c in corpus}, work)
    scores = metrics(rankings, {q: qrels[q] for q in ids})
    from agents.hybrid_agent import CANDIDATES_PER_QUERY, FINAL_TOP_K, POOL_SIZE
    from retrieval.reranker import DEFAULT_RERANKER_MODEL
    commit = git("rev-parse", "--short", "HEAD")
    config = {"label": args.label, "dataset": name, "split": args.split, "commit": commit,
              "uncommitted_changes": bool(git("status", "--porcelain", "--untracked-files=no")),
              "documents": len(corpus), "questions": len(ids), "relevant_pairs": sum(len(qrels[q]) for q in ids),
              "index": index, "embedding_model": EMBED_MODEL, "reranker": DEFAULT_RERANKER_MODEL,
              "omnidoc_search": {"candidates_per_query": CANDIDATES_PER_QUERY, "reranked_pool": POOL_SIZE, "top_k": FINAL_TOP_K},
              "search_seconds": round(time.perf_counter() - started, 1), **timing, "notes": args.notes}
    for mode in MODES:
        log(f"  {mode:<11} nDCG@10 {scores[mode]['ndcg@10']:.3f}  MRR@10 {scores[mode]['mrr@10']:.3f}  "
            f"Recall@10 {scores[mode]['recall@10']:.3f}")
    if args.limit:
        log("a --limit run is not stored")
        return
    # Development runs (the train questions) are kept apart, out of the history.
    run_dir = (RESULTS / f"{dt.date.today():%Y-%m-%d}_{name}_{args.label}_{commit}" if args.split == "test" else
               RESULTS / "dev" / f"{dt.date.today():%Y-%m-%d}_{name}-{args.split}_{args.label}_{commit}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(config, indent=1) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(scores, indent=1) + "\n")
    with open(run_dir / "rankings.jsonl", "w") as f:
        for qid in ids:
            f.write(json.dumps({"id": qid, "question": queries[qid], "relevant": sorted(qrels[qid]),
                                **{m: rankings[qid][m][:10] for m in MODES}}) + "\n")
    (run_dir / "report.md").write_text(render(run_dir.name, config, scores) + "\n")
    write_history()
    log(f"report written to {run_dir / 'report.md'}")


def num(x: Any) -> str:
    return "-" if x is None else f"{x:.3f}"


def render(run: str, config: Dict[str, Any], scores: Dict[str, Dict[str, Any]]) -> str:
    s, ix = config["omnidoc_search"], config["index"]
    out = [f"# Retrieval run {run}", "",
           f"BEIR {config['dataset']}: {config['documents']:,} documents ({ix['passages']:,} passages), "
           f"{config['questions']} {config.get('split', 'test')} questions with {config['relevant_pairs']} relevant documents. Commit `{config['commit']}`"
           + (" with uncommitted changes" if config["uncommitted_changes"] else "") + ".", "",
           f"Embeddings `{config['embedding_model']}`, reranker `{config['reranker']}`. OmniDoc's search takes "
           f"{s['candidates_per_query']} hybrid candidates per query, reranks up to {s['reranked_pool']} and hands the "
           f"top {s['top_k']} passages to the writer. Exact metrics against the benchmark's judgements; no model grades anything.", "",
           "| Mode | nDCG@10 | MRR@10 | Recall@10 | Hit@10 | Recall@100 |", "|---|---|---|---|---|---|"]
    for mode in MODES:
        m = scores[mode]
        out.append(f"| {mode} | **{num(m['ndcg@10'])}** | {num(m['mrr@10'])} | {num(m['recall@10'])} | "
                   f"{num(m['hit@10'])} | {num(m['recall@100'])} |")
    out += ["", "- **omnidoc** is what the app's answer writer receives; its documents come from 10 passages, so it can "
                "list fewer than 10 documents when an abstract was split in two.",
            "- **rerank-100** reranks the passages of the 100 best hybrid documents: the same documents as hybrid, in a "
            "better order.",
            "- Hit@10: questions with at least one relevant document in the top 10.",
            "", "## Cost and speed", "",
            f"- Index: {ix['passages']:,} passages embedded and stored in {ix['seconds']:.0f} s (built at `{ix['commit']}`; "
            f"{ix.get('failed_embeddings', 0)} could not be embedded). Local models only, no API calls.",
            f"- OmniDoc's search per question: median {config['omnidoc_search_median_s'] * 1000:.0f} ms, 90th percentile "
            f"{config['omnidoc_search_p90_s'] * 1000:.0f} ms (embedding the question, hybrid search, reranking).",
            f"- Questions that also searched financial names: {config['questions_with_finance_terms_query']}."]
    if config["dataset"] in REFERENCES:
        out += ["", "## Published results", "", "nDCG@10 on the same questions; setups differ.", ""]
        out += [f"- {label}: {value:.3f}" for label, value in REFERENCES[config["dataset"]]]
        out += ["", *REFERENCE_SOURCES]
    if config.get("notes"):
        out += ["", f"Notes: {config['notes']}"]
    return "\n".join(out)


def write_history() -> None:
    rows = []
    for p in sorted(RESULTS.glob("*/metrics.json")):
        config = json.loads((p.parent / "config.json").read_text())
        m = json.loads(p.read_text())
        rows.append(f"| [{p.parent.name}]({p.parent.name}/report.md) | {config['dataset']} | `{config['commit']}` | "
                    f"{num(m['bm25']['ndcg@10'])} | {num(m['dense']['ndcg@10'])} | {num(m['hybrid']['ndcg@10'])} | "
                    f"**{num(m['omnidoc']['ndcg@10'])}** | {num(m['omnidoc']['hit@10'])} | {num(m['rerank-100']['ndcg@10'])} | "
                    f"{num(m['hybrid']['recall@100'])} |")
    text = ["# Retrieval history", "",
            "Every run of `benchmarks/beir.py`: nDCG@10 per search mode on the BEIR test questions (exact metrics, no judge). "
            "OmniDoc's search is the column that matters: it is what the answer writer receives.", "",
            "| Run | Dataset | Commit | BM25 | Dense | Hybrid | OmniDoc search | Hit@10 | Rerank 100 | Recall@100 (hybrid) |",
            "|---|---|---|---|---|---|---|---|---|---|", *rows]
    (RESULTS / "HISTORY.md").write_text("\n".join(text) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("fetch", "run"):
        p = sub.add_parser(cmd)
        p.add_argument("--dataset", default="scifact")
        if cmd == "run":
            p.add_argument("--label", required=True)
            p.add_argument("--split", choices=SPLITS, default="test",
                           help="test: the measured questions; train: other questions, for trying changes out")
            p.add_argument("--notes", default="")
            p.add_argument("--limit", type=int, default=0, help="search only the first N questions (not stored)")
    args = parser.parse_args()
    # Anything the imported app code writes stays in the benchmark's own folder.
    os.environ.setdefault("OMNIDOC_DATA_DIR", str(WORK / f"beir-{args.dataset}" / "data"))
    {"fetch": fetch, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
