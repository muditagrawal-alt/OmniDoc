"""
Memory of the slim server (requirements-slim.txt) through a realistic session, measured on Linux in
CI: start-up, uploading a PDF with scanned pages (OCR), and a run of questions. Answers come from a
fake OpenAI-compatible model, so no API quota is used and timing reflects OmniDoc itself.

    python benchmarks/memory_check.py --budget 900

Prints a table (and appends it to $GITHUB_STEP_SUMMARY) and exits non-zero when the server's
resident memory goes over the budget: the free 1 GB plan the slim image is sized for.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

QUESTIONS = [
    "How did revenue change and why?",
    "What are the main risks the report mentions?",
    "Which region grew fastest?",
    "What was the operating margin?",
    "Summarize the outlook for next year.",
]


def make_pdf(path: str) -> None:
    """Ten text pages and two scanned (image-only) pages, so parsing exercises OCR."""
    import fitz
    paragraph = ("Revenue grew 12% to $4.2 billion in fiscal 2023, driven by services in Asia and Europe. "
                 "Operating margin improved to 18.4% as costs fell. Risks include currency swings, supply "
                 "constraints and new regulation. The outlook for next year assumes steady demand. ")
    doc = fitz.open()
    for n in range(10):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(56, 56, 540, 790), f"Section {n + 1}\n\n" + paragraph * 6, fontsize=10)
    for n in range(2):
        text_page = fitz.open()
        tp = text_page.new_page()
        tp.insert_textbox(fitz.Rect(56, 56, 540, 790), f"Scanned annex {n + 1}\n\n" + paragraph * 4, fontsize=11)
        pix = tp.get_pixmap(dpi=200)
        page = doc.new_page()
        page.insert_image(page.rect, pixmap=pix)
    doc.save(path)


def rss_mb(pid: int) -> float:
    import psutil
    proc = psutil.Process(pid)
    return sum(p.memory_info().rss for p in [proc] + proc.children(recursive=True)) / 2**20


def call(port: int, path: str, data=None, upload=None, timeout=600):
    if upload:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"report.pdf\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + open(upload, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    else:
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=900, help="MB the server may use at most")
    ap.add_argument("--port", type=int, default=8077)
    args = ap.parse_args()

    from fake_llm_server import FakeLLM
    llm = FakeLLM(reply="Revenue grew 12% to $4.2 billion [1].")
    work = tempfile.mkdtemp(prefix="omnidoc-memory-")
    pdf = os.path.join(work, "report.pdf")
    make_pdf(pdf)
    env = dict(os.environ, OMNIDOC_DATA_DIR=os.path.join(work, "data"), OMNIDOC_PORT=str(args.port),
               OMNIDOC_LLM_BASE_URL=llm.url, OMNIDOC_LLM_API_KEY="test", OMNIDOC_LLM_MODEL="fake",
               OMNIDOC_MODEL="custom:fake", OMNIDOC_LLM_PROVIDERS="custom", OMNIDOC_LOCAL_FALLBACK="0",
               OMNIDOC_WEB_SEARCH="off", OLLAMA_HOST="http://127.0.0.1:9",
               OMNIDOC_EMBED_MODEL=os.environ.get("OMNIDOC_EMBED_MODEL", "onnx:Xenova/bge-small-en-v1.5"),
               OMNIDOC_RERANKER_MODEL=os.environ.get("OMNIDOC_RERANKER_MODEL", "onnx:Xenova/ms-marco-MiniLM-L-6-v2"),
               OMNIDOC_ONNX_THREADS="1", OMNIDOC_GRAPH_MEMORY_MB="96",
               MALLOC_ARENA_MAX="2", MALLOC_TRIM_THRESHOLD_="131072", MALLOC_MMAP_THRESHOLD_="131072")
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "MISTRAL_API_KEY",
                "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "GITHUB_MODELS_TOKEN", "JINA_API_KEY"):
        env[key] = ""
    server = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                              stdout=open(os.path.join(work, "server.log"), "w"), stderr=subprocess.STDOUT)
    rows, peak = [], 0.0

    def record(label: str, seconds: float = 0.0) -> None:
        nonlocal peak
        now = rss_mb(server.pid)
        peak = max(peak, now)
        rows.append((label, now, seconds))
        print(f"{label:<34} {now:7.0f} MB  {seconds:6.1f} s", flush=True)

    try:
        for _ in range(180):
            try:
                call(args.port, "/api/health", timeout=5)
                break
            except Exception:
                time.sleep(1)
        time.sleep(20)  # the pipeline and both models load in the background at start
        record("started and warmed up")
        t = time.time()
        up = call(args.port, "/api/documents/upload", upload=pdf)
        record(f"uploaded 12 pages ({up.get('ocr_pages', 0)} by OCR)", time.time() - t)
        chat = call(args.port, "/api/chats", {"title": "memory check"})["chat"]
        for n, question in enumerate(QUESTIONS, 1):
            t = time.time()
            call(args.port, f"/api/chats/{chat['id']}/query", {"query": question})
            record(f"question {n}", time.time() - t)
        time.sleep(15)
        record("after background work")
    finally:
        server.terminate()
        llm.close()

    table = ["| Step | Memory | Time |", "|---|---:|---:|"]
    table += [f"| {label} | {mb:.0f} MB | {seconds:.1f} s |" for label, mb, seconds in rows]
    verdict = f"Peak {peak:.0f} MB against a budget of {args.budget:.0f} MB: {'within' if peak <= args.budget else 'OVER'}."
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("### Slim server memory\n\n" + "\n".join(table) + f"\n\n{verdict}\n")
    print(verdict)
    return 0 if peak <= args.budget else 1


if __name__ == "__main__":
    sys.exit(main())
