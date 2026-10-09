"""
Tests for the model-provider layer, question understanding, the deterministic agents
(document intelligence, temporal reasoning, structured data, conflict pre-check), document
type detection and validation, sensitive data, comparison, web reading safety and the MCP
server. Hosted APIs are replaced by local fake servers; no real model calls.
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from fake_llm_server import FakeLLM  # noqa: E402
from agents import llm_providers as P  # noqa: E402
from agents import llm_utils as U  # noqa: E402
from core.state import EvidenceItem, RetrievedChunk  # noqa: E402


# ------------------------------------------------------------------ providers
@pytest.fixture(autouse=True)
def fresh_provider_state(monkeypatch):
    """Each test starts with no cooldowns or pacing left over from real calls in other tests."""
    monkeypatch.setattr(P, "_cooldown", {})
    monkeypatch.setattr(P, "_recent", {})
    monkeypatch.setattr(P, "_no_extras", {})


@pytest.fixture()
def providers(monkeypatch):
    """Groq always rate-limited, NVIDIA answering (and rejecting optional fields), no local fallback."""
    limited, good = FakeLLM(rate_limited=True), FakeLLM(reply='{"answer": 42}', reject_extras=True, think=True)
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("NVIDIA_API_KEY", "k2")
    monkeypatch.setenv("OMNIDOC_LLM_PROVIDERS", "groq,nvidia")
    monkeypatch.setenv("OMNIDOC_LOCAL_FALLBACK", "0")
    monkeypatch.setattr(P.REGISTRY["groq"], "base_url", limited.url)
    monkeypatch.setattr(P.REGISTRY["nvidia"], "base_url", good.url)
    monkeypatch.setattr(P, "_cooldown", {})
    monkeypatch.setattr(P, "_recent", {})
    monkeypatch.setattr(P, "_no_extras", {})
    yield limited, good
    limited.close()
    good.close()


def test_falls_back_on_rate_limits_and_retries_without_optional_fields(providers):
    limited, good = providers
    P.set_current_run("t1")
    assert U.chat_json("groq:openai/gpt-oss-120b", "json please", schema={"type": "object"}) == {"answer": 42}
    assert P._cooldown.get("groq", 0) > 0  # the rate-limited provider is skipped for a while
    formats = [r["body"].get("response_format", {}).get("type") for r in good.requests]
    assert formats == ["json_schema", "json_object"]  # schema rejected -> plain JSON mode
    stats = P.run_stats("t1", pop=True)
    assert stats["calls"] == 1 and stats["models"] == {"nvidia:nvidia/nemotron-3-super-120b-a12b": 1}
    P.set_current_run(None)


def test_streaming_hides_thinking_and_reports_every_piece(providers):
    _, good = providers
    good.reply = "Wind supplies 51 percent [1]."
    pieces = []
    out = U.chat_stream("groq:openai/gpt-oss-120b", [{"role": "user", "content": "hi"}], pieces.append)
    assert out == "Wind supplies 51 percent [1]." and "".join(pieces) == out


def test_think_filter_handles_tags_split_across_pieces():
    f = P.ThinkFilter()
    text = "".join(f.feed(p) for p in ["Ans", "<thi", "nk>secret</th", "ink>wer"]) + f.flush()
    assert text == "Answer"


def test_specs_and_fast_models():
    assert P.parse_spec("qwen2.5:7b-instruct") == ("ollama", "qwen2.5:7b-instruct")
    assert P.parse_spec("groq:openai/gpt-oss-120b") == ("groq", "openai/gpt-oss-120b")
    groq = P.REGISTRY["groq"]
    assert P.fast_variant(groq, groq.model) == groq.fast_model
    assert P.fast_variant(groq, "some/other-model") == "some/other-model"


def test_too_large_requests_skip_small_tpm_providers():
    ok, why = P._available(P.REGISTRY["groq"], est_tokens=50_000)
    assert not ok and "tokens/min" in why


# ---------------------------------------------------------------- understanding
def test_rules_understand_simple_questions_without_a_model():
    from agents.understanding_agent import rules, wants_model
    u = rules("Compare the revenue of Acme and Globex in 2023 and plot it")
    assert u["intent"] == "comparison" and u["needs"]["chart"] and u["needs"]["timeline"]
    assert u["time_range"] == {"start": "2023", "end": "2023"}
    assert wants_model("What is the total due?", [], "en") == (False, "simple question")
    assert wants_model("And what about its tax?", [{"role": "user", "content": "x"}], "en")[0]
    assert wants_model("क्या यह अनुबंध 2027 में समाप्त होता है?", [], "hi")[0]


def test_language_instruction_and_script_detection():
    from agents.understanding_agent import split_language_instruction, detect_script_language
    q, lang = split_language_instruction("How much?\n\n[Instruction: write the complete final answer in Hindi (हिन्दी), keeping numbers exact.]")
    assert q == "How much?" and lang == "hi"
    assert detect_script_language("இந்த ஒப்பந்தம் எப்போது முடிகிறது") == "ta"
    assert detect_script_language("When does it end?") == "en"


def test_understanding_merges_the_model_answer(monkeypatch):
    import agents.understanding_agent as ua
    monkeypatch.setattr(ua, "chat_json", lambda *a, **k: {
        "resolved_query": "What tax does the Northwind invoice charge?", "language": "en",
        "search_queries": ["Northwind invoice GST tax amount"], "sub_questions": ["What tax does the invoice charge?"],
        "entities": ["Northwind"], "intent": "factual",
        "needs": {"calculation": False, "chart": True, "tables": False}, "time_range": None})
    u = ua.QueryUnderstandingAgent().understand("and its tax?", [{"role": "user", "content": "Northwind invoice total?"}])
    assert u["used_model"] and u["resolved_query"].startswith("What tax")
    assert u["search_queries"][0] == "Northwind invoice GST tax amount"
    assert u["needs"]["chart"] is False  # charts need an explicit request in the question


# ------------------------------------------------------------ deterministic agents
def test_temporal_reasoning_orders_events_and_sets_aside_out_of_range_passages():
    from agents.temporal_reasoning_agent import TemporalReasoningAgent, dates_in
    assert dates_in("Signed on 12 March 2021 and renewed in Q3 2023.")[0][0] == "2021-03-12"
    chunks = [{"chunk_id": "a", "doc_id": "d", "page_number": 1, "text": "The plant opened in 2019. It doubled output in March 2021."},
              {"chunk_id": "b", "doc_id": "d", "page_number": 2, "text": "In 2012 the site was surveyed."},
              {"chunk_id": "c", "doc_id": "d", "page_number": 3, "text": "Capacity reached 40 MW in 2022."}]
    out = TemporalReasoningAgent().run({"chunk_context": chunks, "needs": {"timeline": True},
                                        "time_filter": {"start": "2019", "end": "2023"}})
    assert out["time_filter"]["exclude_chunk_ids"] == ["b"]
    assert [e["date"][:4] for e in out["timeline"]] == ["2019", "2021", "2022"]


def test_document_intelligence_follows_references_and_neighbours():
    from agents.document_intelligence_agent import DocumentIntelligenceAgent

    class Store:
        def get_document_chunks(self, doc_id):
            return [RetrievedChunk(chunk_id="d_p1_c0", doc_id="d", page_number=1, text="Intro text about the plan and its goals."),
                    RetrievedChunk(chunk_id="d_p2_c0", doc_id="d", page_number=2, text="The fleet will need 3.8 million turbines and"),
                    RetrievedChunk(chunk_id="d_p2_c1", doc_id="d", page_number=2, text="49,000 solar plants worldwide by 2030."),
                    RetrievedChunk(chunk_id="d_p5_c0", doc_id="d", page_number=5, text="Table 3: Costs per kilowatt-hour by source.")]
    state = {"user_query": "What does Table 3 show?", "document_ids": ["d"],
             "chunk_context": [{"chunk_id": "d_p2_c0", "doc_id": "d", "page_number": 2, "score": 0.8,
                                "text": "The fleet will need 3.8 million turbines and"}]}
    added = {c["chunk_id"]: c["retrieval_method"] for c in DocumentIntelligenceAgent(Store()).run(state)["chunk_context"]}
    assert added == {"d_p5_c0": "reference", "d_p2_c1": "layout_context"}


def test_conflict_precheck_needs_the_same_quantity_with_different_figures():
    from agents.conflict_resolution_agent import suspected_conflicts

    def item(doc, text):
        return EvidenceItem(evidence_id=doc, source_type="vector_chunk", source_id=doc, content=text, provenance={"doc_id": doc})
    a = item("A", "The plan needs 3.8 million wind turbines rated at 5 megawatts.")
    assert suspected_conflicts([a, item("B", "Wind supplies 51 percent of demand.")]) == 0
    assert suspected_conflicts([a, item("C", "The plan calls for 4.2 million wind turbines rated at 5 megawatts.")]) == 1


def test_structured_data_queries_library_records(monkeypatch):
    import agents.table_agent as table_agent
    from retrieval.table_store import TableStore
    from retrieval.records import LibraryRecords
    from agents.structured_data_agent import StructuredDataAgent
    store = TableStore(os.path.join(tempfile.mkdtemp(), "t.db"))
    records = LibraryRecords(store, tempfile.mkdtemp())
    fields = [{"name": "total", "label": "Total due", "value": 991200, "status": "found"},
              {"name": "vendor", "label": "Vendor", "value": "Northwind", "status": "found"}]
    records.save("doc_inv", {"doc_type": "invoice", "fields": fields, "validation": [{"rule": "x", "status": "ok"}]})
    records.refresh([{"id": "doc_inv", "title": "inv.pdf", "doc_type": "invoice", "pages": 1, "upload_date": "2026-10-09"}])
    seen = {}

    def plan(model, prompt, **k):
        seen["prompt"] = prompt
        return {"queries": [{"table": "t_records_invoice", "sql": 'SELECT SUM("total_due") AS total FROM "t_records_invoice"', "answers": "total"}]}
    monkeypatch.setattr(table_agent, "chat_json", plan)
    agent = StructuredDataAgent(table_agent.TableQAAgent(store))
    out = agent.run({"user_query": "What is the total due across all my invoices?", "needs": {"library": True}})
    assert out["table_results"][0]["rows"] == [[991200]]
    assert "t_library" in seen["prompt"] and "t_records_invoice" in seen["prompt"]


def _reading_list_tables(store, doc_id="doc_list"):
    from parsing.docling_parser import _table
    from parsing.tables import normalize_table
    stage = normalize_table(["Book", "Author"], [["SPQR", "Mary Beard"], ["Persians", "Lloyd Llewellyn-Jones"]])
    prices = normalize_table(["Book", "Price"], [["SPQR", "18.99"], ["Persians", "24.50"]])
    store.add_tables(doc_id, [_table(doc_id, 1, 1, None, "Stage 2 — Ancient Civilizations and Empires", stage, "pdf"),
                              _table(doc_id, 2, 2, None, "Empires reading list prices", prices, "pdf")])


def test_text_only_tables_are_left_to_passage_search(monkeypatch):
    import agents.table_agent as table_agent
    from retrieval.table_store import TableStore
    from agents.structured_data_agent import StructuredDataAgent
    store = TableStore(os.path.join(tempfile.mkdtemp(), "t.db"))
    _reading_list_tables(store)
    prompts = []

    def plan(model, prompt, **k):
        prompts.append(prompt)
        return {"queries": [{"sql": 'SELECT "book" FROM "t_doc_list_1" WHERE "book" LIKE \'%conquer%\'', "answers": "x"}]}
    monkeypatch.setattr(table_agent, "chat_json", plan)
    agent = StructuredDataAgent(table_agent.TableQAAgent(store))
    # A semantic question over a Book | Author list: only the table with numbers is offered to SQL.
    agent.run({"user_query": "Which books deal with empires?", "document_ids": ["doc_list"]})
    assert "t_doc_list_2" in prompts[0] and "t_doc_list_1" not in prompts[0]
    prompts.clear()
    # Asked about rows, the text table is used; a LIKE search that matched nothing is not evidence.
    out = agent.run({"user_query": "List the rows of the empires table", "document_ids": ["doc_list"]})
    assert "t_doc_list_1" in prompts[0]
    assert out["table_results"] == [] and "matched no rows" in out["agent_traces"][0]["detail"]


def test_short_sections_keep_their_headings_in_the_text():
    from parsing.docling_parser import chunk_blocks
    blocks = [(1, "Stage 0 — Build the Habit", "Book Author The Great Gatsby F. Scott Fitzgerald"),
              (1, "Stage 1 — Humanity Before Civilization", "Book Author Sapiens Yuval Noah Harari"),
              (1, "Stage 2 — Ancient Civilizations and Empires", "Book Author SPQR Mary Beard Persians Lloyd Llewellyn-Jones")]
    chunks = chunk_blocks("doc_x", blocks)
    text = " ".join(c.text for c in chunks)
    assert chunks[0].section_title == "Stage 0 — Build the Habit"
    assert "Stage 1 — Humanity Before Civilization Book Author Sapiens" in text
    assert text.count("Stage 2 — Ancient Civilizations and Empires") == 1


def test_pdf_table_header_rows_are_not_headings():
    import fitz
    from parsing.docling_parser import DoclingParser
    folder = tempfile.mkdtemp()
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((56, 60), "A Reading Roadmap", fontsize=20, fontname="hebo")
    page.insert_text((56, 100), "This roadmap follows humanity from prehistory to the modern world in readable books.", fontsize=10)
    y = 150
    for title, rows in (("Stage 1 - Humanity Before Civilization", [("Sapiens", "Yuval Noah Harari"), ("Guns, Germs, and Steel", "Jared Diamond")]),
                        ("Stage 2 - Ancient Civilizations and Empires", [("SPQR", "Mary Beard"), ("Persians", "Lloyd Llewellyn-Jones")])):
        page.insert_text((56, y), title, fontsize=14, fontname="hebo")
        top = y + 15
        lines = [("Book", "Author")] + rows
        for i, (book, author) in enumerate(lines):
            ry = top + i * 22
            page.insert_text((62, ry + 15), book, fontsize=10, fontname="hebo" if i == 0 else "helv")
            page.insert_text((312, ry + 15), author, fontsize=10, fontname="hebo" if i == 0 else "helv")
        bottom = top + len(lines) * 22
        for i in range(len(lines) + 1):
            page.draw_line((56, top + i * 22), (556, top + i * 22))
        for x in (56, 306, 556):
            page.draw_line((x, top), (x, bottom))
        y = bottom + 50
    path = os.path.join(folder, "roadmap.pdf")
    doc.save(path)
    parsed = DoclingParser(extracted_images_dir=folder).parse_document(path, doc_id="doc_r", fast_mode=True)
    text = " ".join(c.text for c in parsed.chunks)
    sections = {c.section_title for c in parsed.chunks}
    assert "Book Author" not in sections
    assert "Stage 2 - Ancient Civilizations and Empires" in text or "Stage 2 - Ancient Civilizations and Empires" in sections
    assert [t["title"] for t in parsed.tables] == ["Stage 1 - Humanity Before Civilization",
                                                   "Stage 2 - Ancient Civilizations and Empires"]

def test_document_type_detection_and_validation():
    from agents.doc_classifier import classify
    from agents.validation import validate
    invoice = "TAX INVOICE\nInvoice No: NW-1\nBill To: Osmansagar\nSubtotal: 885,000\nGST: 106,200\nTotal Due: 991,200\nDue Date: 11 Sep 2026"
    assert classify(invoice, "scan.jpg")["type"] == "invoice"
    contract = "This Agreement is made between the parties hereinafter... Governing law: India. Termination: 30 days. Effective Date: 1 Jan 2026"
    assert classify(contract, "msa.pdf")["type"] == "contract"
    assert classify("Hello, here are some notes.", "notes.txt")["type"] == "other"
    fields = [{"name": "subtotal", "value": 885000, "status": "found"}, {"name": "tax", "value": 106200, "status": "found"},
              {"name": "total", "value": 991300, "status": "found"},
              {"name": "invoice_date", "value": "2026-08-12", "status": "found"}, {"name": "due_date", "value": "2026-09-11", "status": "found"}]
    by_rule = {c["rule"]: c["status"] for c in validate("invoice", fields)}
    assert by_rule["Subtotal + tax = total"] == "ok"  # within 1% rounding
    fields[2]["value"] = 1_200_000
    assert {c["rule"]: c["status"] for c in validate("invoice", fields)}["Subtotal + tax = total"] == "fail"


# ------------------------------------------------------- sensitive data, compare
def test_sensitive_data_checksums_and_redaction():
    from parsing import pii
    assert pii.verhoeff_ok("234567890124") and not pii.verhoeff_ok("234567890125")
    text = "Aadhaar 2345 6789 0124, PAN ABCPR1234K, card 4111 1111 1111 1111, invoice 2026-0419 total 991200."
    kinds = [f["type"] for f in pii.find_in_text(text)]
    assert kinds == ["aadhaar", "pan", "card"]
    redacted, n = pii.redact_text(text)
    assert n == 3 and "ABCPR1234K" not in redacted and "991200" in redacted


def test_compare_finds_changed_figures_and_clauses():
    from agents.compare_agent import compare
    a = [RetrievedChunk(chunk_id="a", doc_id="a", page_number=1, text="The monthly fee is INR 50,000. Payments are due within 15 days.")]
    b = [RetrievedChunk(chunk_id="b", doc_id="b", page_number=2, text="The monthly fee is INR 65,000. The supplier keeps insurance.")]
    r = compare(a, b)
    kinds = {c["kind"] for c in r["changes"]}
    assert kinds == {"modified", "added", "removed"}
    modified = next(c for c in r["changes"] if c["kind"] == "modified")
    assert modified["figures"] == [{"from": 50000.0, "to": 65000.0}] and modified["b"]["page"] == 2


# ------------------------------------------------------------------- web, MCP
@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/", "http://localhost/", "http://169.254.169.254/latest",
                                 "file:///etc/passwd", "ftp://example.com/x"])
def test_web_reader_refuses_private_and_non_http_addresses(url):
    from parsing.web import check_url, FetchError
    with pytest.raises(FetchError):
        check_url(url)


def test_readable_keeps_the_article_and_drops_boilerplate():
    from parsing.web import readable, passages
    html = ("<html><head><title>Guide</title><meta property='og:site_name' content='Solar Co'></head><body>"
            "<nav>Home About Contact us today</nav><article><h2>Panels</h2>"
            "<p>A typical rooftop panel produces about 400 watts in full sunlight during summer months.</p>"
            "<p>Inverters convert the direct current from panels into alternating current for the home.</p></article>"
            "<footer>Copyright 2026 all rights reserved by the company</footer></body></html>")
    page = readable(html, "https://example.com/guide")
    assert page["site"] == "Solar Co" and page["paragraphs"][0] == "## Panels"
    assert not any("Copyright" in p or "Contact" in p for p in page["paragraphs"])
    assert passages(page["paragraphs"])[0].startswith("Panels A typical rooftop panel")


def test_web_agent_searches_only_when_needed():
    from agents.web_search_agent import WebSearchAgent, wants_web
    agent = WebSearchAgent()
    assert wants_web("What is the latest news on the GST council?")
    assert agent.should_search({"needs": {"web_mode": "off"}, "user_query": "latest news"}) == ""
    assert agent.should_search({"needs": {"web_mode": "on"}, "user_query": "anything"})
    strong = [{"chunk_id": "c", "score": 0.9}]
    assert agent.should_search({"needs": {"web_mode": "auto"}, "user_query": "What is the total due?", "chunk_context": strong}) == ""
    assert agent.should_search({"needs": {"web_mode": "auto"}, "user_query": "What is the total due?", "chunk_context": []})


def test_mcp_server_speaks_json_rpc():
    import mcp_server
    init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"ask", "search_documents", "extract_fields", "compare_documents"} <= names
    missing = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}})
    assert missing["error"]["code"] == -32602
    json.dumps(init)  # serialisable
