"""
OmniDoc as an MCP server (Model Context Protocol, stdio transport).

Lets Claude Desktop, Claude Code, Cursor and other MCP clients use your OmniDoc library as
a tool: search it, ask cited questions, read documents, fill extraction templates, find
sensitive data and compare documents. It talks to a running OmniDoc server over its REST API
(OMNIDOC_API_URL, default http://127.0.0.1:8000; OMNIDOC_API_AUTH="user:password" when the
server is protected with basic auth). Pure Python, no extra packages.

Claude Code:     claude mcp add omnidoc -- python /path/to/OmniDoc/mcp_server.py
Claude Desktop:  {"mcpServers": {"omnidoc": {"command": "python", "args": ["/path/to/OmniDoc/mcp_server.py"]}}}
"""
import os
import sys
import json
import base64
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

API = os.environ.get("OMNIDOC_API_URL", "http://127.0.0.1:8000").rstrip("/")
AUTH = os.environ.get("OMNIDOC_API_AUTH", "")
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
TIMEOUT_S = float(os.environ.get("OMNIDOC_MCP_TIMEOUT", "600"))


def log(message: str) -> None:
    print(f"[omnidoc-mcp] {message}", file=sys.stderr, flush=True)


def call_api(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    if AUTH:
        req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"OmniDoc API {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach OmniDoc at {API} ({e.reason}). Is `python server.py` running?")


def _ids(args: Dict[str, Any]) -> List[str]:
    ids = args.get("document_ids") or []
    return [str(i) for i in ids] if isinstance(ids, list) else [str(ids)]


def tool_list_documents(args: Dict[str, Any]) -> str:
    docs = call_api("GET", "/api/documents")["documents"]
    if not docs:
        return "The library is empty."
    lines = []
    for d in docs:
        facts = [d.get("doc_type_label") or d.get("file_type", ""), f"{d.get('pages')} pages" if d.get("pages") else "",
                 f"{d.get('table_count')} tables" if d.get("table_count") else ""]
        lines.append(f"- {d['filename']} (id: {d['id']}; {', '.join(f for f in facts if f)})")
    return "\n".join(lines)


def tool_search(args: Dict[str, Any]) -> str:
    r = call_api("POST", "/api/search", {"query": args["query"], "document_ids": _ids(args) or None,
                                          "top_k": int(args.get("top_k") or 6)})
    if not r["results"]:
        return "No passages matched."
    return "\n\n".join(f"[{i}] {h['title']}, p. {h['page']} (relevance {h['score']:.2f}):\n{h['text']}"
                       for i, h in enumerate(r["results"], 1))


def tool_ask(args: Dict[str, Any]) -> str:
    r = call_api("POST", "/api/query", {"query": args["question"], "document_ids": _ids(args) or None,
                                         "web": args.get("web") or "auto"})
    lines = [r.get("answer", "")]
    sources = r.get("sources") or []
    if sources:
        lines.append("\nSources:")
        for s in sources:
            where = s.get("url") or f"{s.get('doc_title') or s.get('doc_id', '')}" + (f", p. {s['page']}" if s.get("page") else "")
            lines.append(f"[{s['n']}] {where} — {s.get('snippet', '')[:200]}")
    v = r.get("verification") or {}
    if v.get("feedback"):
        lines.append(f"\nVerification: {v['feedback']}")
    return "\n".join(lines)


def tool_read_document(args: Dict[str, Any]) -> str:
    r = call_api("GET", f"/api/documents/{args['document_id']}/text")
    text, page = [], None
    for c in r["chunks"]:
        if c["page"] != page:
            page = c["page"]
            text.append(f"\n--- page {page} ---")
        text.append(c["text"])
    out = "\n".join(text).strip()
    limit = int(args.get("max_chars") or 30000)
    return out[:limit] + ("\n[truncated]" if len(out) > limit else "")


def tool_extract(args: Dict[str, Any]) -> str:
    fields = args.get("fields") or []
    body: Dict[str, Any] = {"document_ids": _ids(args)}
    if fields:
        body["fields"] = [{"label": f, "type": "text"} if isinstance(f, str) else f for f in fields]
    else:
        body["preset"] = args.get("template") or "invoice"
    # The extraction endpoint streams events; read the whole stream and keep the results.
    req = urllib.request.Request(f"{API}/api/extract/stream", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
    if AUTH:
        req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    results, event = [], ""
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "doc_result":
                results.append(json.loads(line[6:]))
    out = []
    for r in results:
        out.append(f"## {r['title']}")
        for f in r["fields"]:
            value = "; ".join(map(str, f["value"])) if isinstance(f["value"], list) else f["value"]
            cite = f" (p. {f['page']}: \"{f['quote']}\")" if f.get("quote") else ""
            out.append(f"- {f['label']}: {value if value is not None else 'not found'} [{f['status']}]{cite}")
    return "\n".join(out) or "Nothing was extracted."


def tool_sensitive(args: Dict[str, Any]) -> str:
    r = call_api("GET", f"/api/documents/{args['document_id']}/sensitive")
    if not r["findings"]:
        return "No sensitive identifiers found."
    return "\n".join(f"- {f['label']}: {f['masked']} (page {f['page']})" for f in r["findings"])


def tool_compare(args: Dict[str, Any]) -> str:
    r = call_api("POST", "/api/compare", {"a": args["document_a"], "b": args["document_b"], "summarize": bool(args.get("summarize"))})
    st = r["stats"]
    lines = [f"{r['a']['title']} vs {r['b']['title']}: {st['modified']} modified, {st['added']} added, "
             f"{st['removed']} removed sentences; {st['figures']} with changed figures."]
    if r.get("summary"):
        lines += ["", r["summary"]]
    for c in r["changes"][:int(args.get("max_changes") or 30)]:
        if c["kind"] == "modified":
            lines.append(f"- {c['id']} changed (p. {c['a']['page']} -> p. {c['b']['page']}): \"{c['a']['text']}\" -> \"{c['b']['text']}\"")
        elif c["kind"] == "added":
            lines.append(f"- {c['id']} added (p. {c['b']['page']}): \"{c['b']['text']}\"")
        else:
            lines.append(f"- {c['id']} removed (p. {c['a']['page']}): \"{c['a']['text']}\"")
    return "\n".join(lines)


IDS = {"type": "array", "items": {"type": "string"}, "description": "Document ids to limit to (from list_documents); all when omitted"}
TOOLS: Dict[str, Dict[str, Any]] = {
    "list_documents": {"fn": tool_list_documents, "description": "List the documents in the OmniDoc library with their ids and types.",
                       "schema": {"type": "object", "properties": {}}},
    "search_documents": {"fn": tool_search, "description": "Hybrid search (meaning + keywords) over the library; returns the best passages with document and page.",
                         "schema": {"type": "object", "properties": {"query": {"type": "string"}, "document_ids": IDS,
                                                                       "top_k": {"type": "integer", "minimum": 1, "maximum": 30}},
                                    "required": ["query"]}},
    "ask": {"fn": tool_ask, "description": "Ask a question; OmniDoc's agents answer from the documents (and the web when needed) with numbered, checked citations.",
            "schema": {"type": "object", "properties": {"question": {"type": "string"}, "document_ids": IDS,
                                                          "web": {"type": "string", "enum": ["auto", "on", "off"]}},
                       "required": ["question"]}},
    "read_document": {"fn": tool_read_document, "description": "The text of one document, page by page.",
                      "schema": {"type": "object", "properties": {"document_id": {"type": "string"}, "max_chars": {"type": "integer"}},
                                 "required": ["document_id"]}},
    "extract_fields": {"fn": tool_extract, "description": "Fill fields from documents with a verbatim quote and page per value. Use a template (invoice, receipt, purchase_order, contract, resume, paper, report, bank_statement) or your own field names.",
                       "schema": {"type": "object", "properties": {"document_ids": IDS, "template": {"type": "string"},
                                                                     "fields": {"type": "array", "items": {"type": "string"}}},
                                  "required": ["document_ids"]}},
    "find_sensitive_data": {"fn": tool_sensitive, "description": "Personal and financial identifiers in a document (Aadhaar, PAN, card and account numbers, phones, e-mails, ...), masked.",
                            "schema": {"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"]}},
    "compare_documents": {"fn": tool_compare, "description": "What changed between two documents: modified, added and removed sentences and changed figures.",
                          "schema": {"type": "object", "properties": {"document_a": {"type": "string"}, "document_b": {"type": "string"},
                                                                        "summarize": {"type": "boolean"}, "max_changes": {"type": "integer"}},
                                     "required": ["document_a", "document_b"]}},
}


def handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "omnidoc", "version": "2.2.0"},
                  "instructions": "OmniDoc is the user's local document library. Use list_documents to see what is there, "
                                  "search_documents for passages, and ask for cited answers."}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        tools = [{"name": n, "description": t["description"], "inputSchema": t["schema"]} for n, t in TOOLS.items()]
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
    if method == "tools/call":
        params = msg.get("params") or {}
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {params.get('name')}"}}
        try:
            text = tool["fn"](params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:  # reported to the model as a tool error
            log(f"{params.get('name')} failed: {e}")
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    log(f"ready (OmniDoc API: {API})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
