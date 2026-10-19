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


@pytest.fixture()
def single_provider(monkeypatch):
    """Only NVIDIA configured (no fallback), with a clock that moves on when the router sleeps."""
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OMNIDOC_LLM_PROVIDERS", "nvidia")
    monkeypatch.setenv("OMNIDOC_LOCAL_FALLBACK", "0")
    slept = []
    monkeypatch.setattr(U.time, "sleep", lambda s: (slept.append(s), P._cooldown.clear()))
    return slept


def test_a_single_provider_is_waited_for_after_a_server_error(single_provider, monkeypatch):
    flaky = FakeLLM(reply="ok", fail_first=1)
    monkeypatch.setattr(P.REGISTRY["nvidia"], "base_url", flaky.url)
    assert U.chat("nvidia:nvidia/nemotron-3-super-120b-a12b", [{"role": "user", "content": "hi"}]) == "ok"
    assert len(flaky.requests) == 2 and len(single_provider) == 1 and 25 <= single_provider[0] <= 31
    flaky.close()


def test_a_single_provider_is_given_up_after_two_waits(single_provider, monkeypatch):
    limited = FakeLLM(rate_limited=True)
    monkeypatch.setattr(P.REGISTRY["nvidia"], "base_url", limited.url)
    with pytest.raises(RuntimeError):
        U.chat("nvidia:nvidia/nemotron-3-super-120b-a12b", [{"role": "user", "content": "hi"}])
    assert len(limited.requests) == 3 and len(single_provider) == 2
    limited.close()


def test_cut_off_json_keeps_its_complete_elements():
    from agents.llm_utils import parse_llm_json
    cut_after_key = '{"chunks": [{"id": "C1", "entities": [{"name": "a", "category": "org"}, {"name": "b", "category"'
    assert parse_llm_json(cut_after_key) == {"chunks": [{"id": "C1", "entities": [{"name": "a", "category": "org"}]}]}
    cut_mid_key = '{"chunks": [{"id": "C1", "entities": [{"name": "a"}]}, {"id": "C2", "entities": [{"na'
    assert parse_llm_json(cut_mid_key) == {"chunks": [{"id": "C1", "entities": [{"name": "a"}]}]}
    assert parse_llm_json('Here: {"a": [1, 2]} done') == {"a": [1, 2]}


def test_graph_batches_cut_off_ask_again_for_the_missing_chunks(monkeypatch):
    from types import SimpleNamespace
    from graph.extractor import GraphExtractor
    calls = []

    def reply(model, prompt, **k):
        calls.append(prompt)
        ids = [i for i in ("C1", "C2", "C3") if f"[{i}]" in prompt]
        keep = ids[:1] if len(calls) == 1 else ids  # the first reply stops after one chunk
        return {"chunks": [{"id": i, "entities": [{"name": "Acme", "category": "org", "description": "x"}]} for i in keep]}
    monkeypatch.setattr(U, "chat_json", reply)
    store = SimpleNamespace(added=[], add_chunk=lambda **k: None, link_chunk_to_entity=lambda *a: None,
                            add_relation=lambda **k: None)
    store.add_entity = lambda **k: store.added.append(k["entity_id"])
    chunks = [SimpleNamespace(chunk_id=f"d_p1_c{i}", page_number=1, section_title="S", text=f"Acme report part {i}.")
              for i in range(3)]
    created = GraphExtractor(store, "nvidia:x").extract_batch("d", chunks)
    assert len(calls) == 2 and "[C1] Acme report part 1." in calls[1] and created == 3


def test_graph_batches_are_asked_in_parallel_and_written_in_order(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace
    from graph.extractor import GraphExtractor
    lock, active, peak, seen = threading.Lock(), [0], [0], []

    def reply(model, prompt, **k):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            seen.append(prompt)
        time.sleep(0.15)
        with lock:
            active[0] -= 1
        if "part 5." in prompt and sum("part 5." in p for p in seen) == 1:
            raise RuntimeError("rate limit")  # the second batch fails once and is asked again at the end
        ids = [i for i in ("C1", "C2", "C3", "C4") if f"[{i}]" in prompt]
        return {"chunks": [{"id": i, "entities": [{"name": "Acme", "category": "org", "description": "x"}]} for i in ids]}
    monkeypatch.setattr(U, "chat_json", reply)
    written = []
    store = SimpleNamespace(add_chunk=lambda **k: written.append(k["chunk_id"]), link_chunk_to_entity=lambda *a: None,
                            add_relation=lambda **k: None, add_entity=lambda **k: None)
    chunks = [SimpleNamespace(chunk_id=f"d_p1_c{i}", page_number=1, section_title="S", text=f"Acme report part {i}.")
              for i in range(12)]
    created = GraphExtractor(store, "nvidia:x").extract_batch("d", chunks)
    assert peak[0] >= 2 and created == 12 and len(seen) == 4      # three batches at once, one asked again
    assert written == [f"d_p1_c{i}" for i in (0, 1, 2, 3, 8, 9, 10, 11, 4, 5, 6, 7)]  # in order; the retried batch last


def test_a_per_minute_quota_is_not_mistaken_for_a_daily_one(monkeypatch):
    from types import SimpleNamespace
    p = P.REGISTRY["gemini"]
    per_minute = ('[{"error": {"code": 429, "message": "You exceeded your current quota.", "details": [{"violations": '
                  '[{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"retryDelay": "17s"}]}}]')
    per_day = per_minute.replace("PerMinute", "PerDay")
    for body, low, high in ((per_minute, 19, 21), (per_day, 3599, 3601)):  # 17 s asked, 20 s at least
        P._cooldown.clear()
        with pytest.raises(P.ProviderError):
            P._raise_for(p, SimpleNamespace(status_code=429, text=body, headers={}))
        assert low <= P.wait_seconds(p, 100) <= high


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

def test_page_references_in_questions():
    from agents.document_intelligence_agent import DocumentIntelligenceAgent as D
    refs = lambda q: [n for k, n in D.references(q) if k == "page"]
    from agents.document_intelligence_agent import numbered_pages as D_numbered
    assert refs("What date is mentioned at the beginning of page(1)?") == ["1"]
    assert refs("How many times does a phone appear on pages 16 and 18?") == ["16", "18"]
    assert refs("What animals appear on page nine?") == ["9"]
    assert refs("Is there a signature on the last page?") == ["last"]
    assert refs("How many websites are on the cover page?") == ["1"]
    assert refs("Summarise pages 3-5") == ["3", "4", "5"]
    assert refs("What page has a snowflake image?") == []
    assert D_numbered("How many websites are on the cover page?") == [] and D_numbered("the third page and page nine") == ["9"]
    assert D.references("What is in Table 3 on page 12?") == [("page", "12"), ("table", "3")]


def test_financial_statements_are_added_for_the_figures_a_question_needs():
    from types import SimpleNamespace
    from core.state import RetrievedChunk
    from agents.document_intelligence_agent import DocumentIntelligenceAgent

    def chunk(i, page, section, text):
        return RetrievedChunk(chunk_id=f"d_p{page}_c{i}", doc_id="d", text=text, page_number=page, section_title=section,
                              score=0.0, retrieval_method="hybrid")
    chunks = [chunk(0, 2, "Table of Contents", "Consolidated Balance Sheets 61 Consolidated Statements of Income 59"),
              chunk(0, 30, "Results of Operations", "Inventories rose because of supply chain delays in the year."),
              chunk(0, 59, "CONSOLIDATED STATEMENTS OF INCOME", "2021 2020 Revenues $ 44,538 $ 37,403 Cost of sales 24,576 21,162 "
                    "Gross profit 19,962 16,241 Net income 5,727 2,539"),
              chunk(0, 61, "CONSOLIDATED BALANCE SHEETS", "2021 2020 Cash 9,889 8,348 Inventories 6,854 7,367 "
                    "Total current assets 26,291 20,556 Total current liabilities 9,674 8,284")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    state = {"user_query": "What is the FY2021 inventory turnover ratio (COGS / average inventory) using the statement of financial position?",
             "document_ids": ["d"], "chunk_context": [{**chunks[1].model_dump(), "score": 0.8}]}
    statements = lambda q: sorted(c["page_number"] for c in agent.run({**state, "user_query": q})["chunk_context"]
                                  if c["retrieval_method"] == "reference")
    assert statements(state["user_query"]) == [59, 61]          # not the contents page that names them
    assert statements("What was the capital expenditure?") == []  # no cash flow statement in this filing
    assert statements("Who is the chief executive?") == []
    assert statements("What is cash_ratio in FY2021 for Nike?") == [61]
    assert statements("What is the cash conversion cycle in FY2021?") == [59, 61]
    added = [c for c in agent.run(state)["chunk_context"] if c["retrieval_method"] == "reference"]
    assert {c["chunk_id"] for c in added} == {"d_p59_page", "d_p61_page"} and all(c["full_page"] for c in added)


def test_statements_come_from_where_they_sit_together_not_from_summaries():
    """A five-year summary repeats every line item; the statements themselves sit a few pages apart."""
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent

    def chunk(page, text):
        return RetrievedChunk(chunk_id=f"d_p{page}_c0", doc_id="d", text=text, page_number=page, section_title="")
    chunks = [chunk(20, "2022 2021 2020 2019 2018 Statement of Operations Data: Net sales 9,100 8,800 8,500 8,100 7,900 "
                        "Cost of sales 5,100 4,900 4,700 4,500 4,300 Gross profit 4,000 3,900 3,800 3,600 3,600 Net income "
                        "1,200 1,100 1,000 900 850 Total assets 20,100 19,000 18,500 17,900 17,000 Total current assets 7,100 "
                        "6,900 6,500 6,100 5,900 Total current liabilities 4,100 3,900 3,700 3,500 3,300 Net cash provided by "
                        "operating activities 1,900 1,800 1,700 1,600 1,500"),
              chunk(60, "December 31, 2022 2021 Assets Cash and cash equivalents 2,100 1,900 Inventories 1,400 1,300 Total "
                        "current assets 7,100 6,900 Property and equipment 5,000 4,800 Total assets 20,100 19,000 Accounts "
                        "payable 1,600 1,500 Total current liabilities 4,100 3,900 Retained earnings 6,000 5,200"),
              chunk(61, "Years ended December 31, 2022 2021 2020 Net sales 9,100 8,800 8,500 Cost of sales 5,100 4,900 4,700 "
                        "Gross profit 4,000 3,900 3,800 Operating income 1,700 1,600 1,500 Net income 1,200 1,100 1,000"),
              chunk(63, "Years ended December 31, 2022 2021 2020 Operating activities Net income 1,200 1,100 1,000 Depreciation "
                        "and amortization 400 390 380 Net cash provided by operating activities 1,900 1,800 1,700 Investing "
                        "activities Capital expenditures (500) (480) (450) Financing activities Dividends paid (300) (280) (260)")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    picked = agent._statement_passages("FY2022 working capital, gross margin and capex from the balance sheet, income and cash flow "
                                       "statements", ["d"], {})
    assert [p.page_number for p in picked] == [60, 61, 63]


def test_whole_statement_pages_survive_evidence_selection():
    """A page of numbers scores low with the reranker, but a statement the question needs is always kept, whole."""
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent, page_passage
    from agents.evidence_selection_agent import EvidenceSelectionAgent, MAX_CHUNKS
    from agents.citations import build_sources

    def chunk(i, page, text):
        return RetrievedChunk(chunk_id=f"d_p{page}_c{i}", doc_id="d", text=text, page_number=page, section_title="")
    sheet = [chunk(0, 50, "Consolidated Balance Sheet As of June 30, 2020 2019 Cash and cash equivalents $ 742.6 $ 601.6 "
                          "Trade receivables, net 1,615.9 1,864.3 Inventories, net 1,831.9 1,953.8 Total current assets"),
             chunk(1, 50, "Inventories, net 1,831.9 1,953.8 Total current assets 4,534.7 5,210.1 Total assets $ 16,442.1 "
                          "$ 17,165.0 Trade payables 2,170.8 2,303.4 Total current liabilities 3,973.6 4,541.8")]
    whole = page_passage(sheet, "d", 50)
    assert whole.chunk_id == "d_p50_page" and whole.text.count("Inventories, net") == 1  # the overlap is not repeated
    narrative = [{"chunk_id": f"d_p{p}_c0", "doc_id": "d", "page_number": p, "score": 0.9, "retrieval_method": "neural_reranked",
                  "text": f"Page {p}: receivables are collected within 60 days; management reviews credit risk."} for p in range(1, 13)]
    statement = {**whole.model_dump(), "score": 0.2, "retrieval_method": "reference", "full_page": True}
    reranker = SimpleNamespace(score_pairs=lambda q, texts: [0.0 if "$" in t else 0.9 for t in texts])
    state = {"user_query": "What is Amcor's year end FY2020 net AR?", "session_id": "s",
             "chunk_context": narrative + [{**sheet[0].model_dump(), "score": 0.5}, statement]}
    package = EvidenceSelectionAgent(reranker=reranker).run(state)["evidence_package"]
    ids = [it.source_id for it in package.items]
    assert ids[0] == "d_p50_page" and "d_p50_c0" not in ids and len(ids) == 1 + MAX_CHUNKS
    sources = build_sources(evidence_package=package)
    assert "Total current liabilities 3,973.6" in sources[0]["_text"]  # the whole page reaches the writer


def test_finance_notes_name_only_what_a_question_needs():
    from agents.finance_terms import notes_for, search_terms
    notes = notes_for("What is Amcor's year end FY2020 net AR (in USD millions)?")
    assert "trade receivables, net" in notes and "EBITDA" not in notes and "inventory turnover" not in notes
    turnover = notes_for("Calculate inventory turnover for FY2022; if inventory management is not meaningful for the company, say why.")
    assert "COGS / average inventory" in turnover and "end of the prior year" in turnover and "card issuers" in turnover
    assert notes_for("What is the CAGR if revenue grew from $100M in 2020 to $160M in 2024?") == ""
    assert "trade receivables" in search_terms("net AR") and search_terms("Who is the chief executive?") == ""


def test_names_the_document_never_mentions_are_noted():
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent, question_names
    assert question_names("Compared to MMDU, how many more QA pairs does SnapNtell have?") == ["MMDU", "SnapNtell"]
    assert question_names("Did JnJ's net earnings rise in Q2 of FY2023 compared to Q2 of FY2022?") == ["JnJ"]
    text = [RetrievedChunk(chunk_id="p_p5_c0", doc_id="p", page_number=5, text="SnapNTell has 75,680 QA pairs; ViQuAE has 3,700.")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: text))
    out = agent.run({"user_query": "Compared to MMDU, how many more QA pairs does SnapNtell have?", "document_ids": ["p"],
                     "chunk_context": [{**text[0].model_dump(), "score": 0.9}]})
    assert out["absent_terms"] == ["MMDU"]


def test_questions_about_the_whole_document_scan_every_page(monkeypatch):
    import fitz
    import agents.vision_agent as V
    assert V.scan_kind("How many exterior photos of organisations does this report provide?") == "count"
    assert V.scan_kind("What page has an eight-pointed snowflake image? Give me an integer.") == "locate"
    assert V.scan_kind("How many times does mobile phone appear on pages 16 and 18?") is None  # those pages are read directly
    assert V.scan_kind("How many employees does PwC Assurance have?") is None
    assert V.scan_kind("How many Democratic people in the survey said neither party has high ethical standards?") is None
    assert V.scan_kind("How many people are there in the images on the cover?") == "count"
    folder = tempfile.mkdtemp()
    os.makedirs(os.path.join(folder, "uploads"))
    doc = fitz.open()
    for n in range(14):
        doc.new_page().insert_text((72, 72), f"Slide {n + 1}")
    doc.save(os.path.join(folder, "uploads", "doc_s.pdf"))
    batches = []

    def scan(model, prompt, pages, **k):
        batches.append([n for n, _ in pages])
        found = {3: ["photo of the head office"], 13: ["photo of a branch", "photo of the lab"]}
        return json.dumps({"pages": [{"page": n, "items": found.get(n, [])} for n, _ in pages]})
    monkeypatch.setattr(V, "vision_chat_pages", scan)
    agent = V.VisionAgent(images_dir=os.path.join(folder, "figures"))
    ask = {"document_ids": ["doc_s"], "user_query": "How many photos does this report provide?"}
    agent._scan("gemini:gemini-3.5-flash-lite", ask, "count")
    assert batches == [list(range(1, 15))]  # a short document is scanned in one request
    batches.clear()
    monkeypatch.setattr(V, "WHOLE_READ_PAGES", 10)
    findings, detail = agent._scan("gemini:gemini-3.5-flash-lite", ask, "count")
    assert batches == [list(range(1, 13)), [13, 14]]  # a long one a batch at a time
    summary, *pages = findings
    assert "found 3 matching item(s) on 2 page(s): page 3 (1), page 13 (2)" in summary["analysis"]
    assert [f["page"] for f in pages] == [3, 13] and "photo of the lab" in pages[1]["analysis"]


def _pdf_with_figures(folder: str) -> str:
    """Page 1 text only, page 2 a large chart image, page 3 text with a small logo."""
    import io
    import fitz
    from PIL import Image, ImageDraw
    def png(w, h):
        img = Image.new("RGB", (w, h), "white")
        ImageDraw.Draw(img).rectangle([10, 10, w - 10, h - 10], outline="black", width=4)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    doc = fitz.open()
    for page_no in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Page {page_no + 1}: revenue grew in every region.", fontsize=11)
        if page_no == 1:
            page.insert_image(fitz.Rect(60, 120, 535, 620), stream=png(800, 800))
        if page_no == 2:
            page.insert_image(fitz.Rect(500, 20, 560, 60), stream=png(160, 160))
    os.makedirs(os.path.join(folder, "uploads"), exist_ok=True)
    path = os.path.join(folder, "uploads", "doc_v.pdf")
    doc.save(path)
    return path


def test_vision_reads_rendered_pages_that_carry_figures(monkeypatch):
    import agents.vision_agent as V
    folder = tempfile.mkdtemp()
    _pdf_with_figures(folder)
    agent = V.VisionAgent(images_dir=os.path.join(folder, "figures"))

    def state(pages, asked=False):
        return {"chunk_context": [{"doc_id": "doc_v", "page_number": p, "score": 1 - i / 10} for i, p in enumerate(pages)],
                "needs": {"figures": asked}, "user_query": "What does the chart show?"}
    assert agent.visual_pages(state([1, 2])) and not agent.visual_pages(state([1, 3]))  # a logo is not a figure
    assert [c["page"] for c in agent._page_candidates(state([1, 2]), strict=True)] == [2]
    # Asked about a figure the search missed: the largest picture (known from ingestion), then the logo page.
    os.makedirs(os.path.join(folder, "figures", "doc_v"))
    open(os.path.join(folder, "figures", "doc_v", "p2_img0.png"), "wb").close()
    assert [c["page"] for c in agent._page_candidates(state([1, 3], asked=True), strict=False)] == [2, 3]
    seen = []
    monkeypatch.setattr(V.VisionAgent, "_hosted_model", staticmethod(lambda: "gemini:gemini-3.5-flash-lite"))

    def read(model, prompt, pages, **k):
        seen.extend((n, image[:8]) for n, image in pages)
        return json.dumps({"answer": "Revenue by region; Asia is 42.", "answer_pages": [2],
                           "pages": [{"page": 2, "finding": "A bar chart of revenue by region; Asia 42."}]})
    monkeypatch.setattr(V, "vision_chat_pages", read)
    out = agent.run(state([2, 1], asked=True))
    # A hosted model reads the candidate pages together, rendered as PNG, and answers from them first;
    # a short document in scope is read whole.
    assert [n for n, _ in seen] == [2] and all(img == b"\x89PNG\r\n\x1a\n" for _, img in seen)
    seen.clear()
    assert agent.run({**state([2, 1], asked=True), "document_ids": ["doc_v"]})["visual_context"]
    assert [n for n, _ in seen] == [1, 2, 3]
    assert agent.short_document({"document_ids": ["doc_v"]}) and not agent.short_document({"document_ids": []})
    reading, page = out["visual_context"]
    assert reading["page"] == 2 and reading["analysis"] == "Answer read from page(s) 2: Revenue by region; Asia is 42."
    assert page["page"] == 2 and "Asia 42" in page["analysis"] and "render" not in page
    # A page the question names comes first when its text was not retrieved.
    named = {**state([1]), "user_query": "What is in the box on page 3?"}
    assert agent.visual_pages(named) and [c["page"] for c in agent._page_candidates(named, strict=True)] == [3]


def test_picture_pages_are_read_with_ocr_and_described_for_search(monkeypatch):
    import fitz
    import agents.vision_agent as V
    from types import SimpleNamespace
    from parsing import ocr
    from core.pipeline import AgenticGraphRAGPipeline
    folder = tempfile.mkdtemp()
    path = _pdf_with_figures(folder)
    with fitz.open(path) as doc:
        assert not ocr.page_needs_ocr(doc[0], 60)          # a text page
        page = doc.new_page(width=595, height=842)          # a slide exported as one picture, with a footer
        page.insert_image(fitz.Rect(0, 0, 595, 800), stream=doc[1].get_pixmap().tobytes("png"))
        page.insert_text((72, 830), "www.example.org - page 4", fontsize=8)
        assert ocr.page_needs_ocr(page, 30) and not ocr.page_needs_ocr(page, 900)
    agent = V.VisionAgent(images_dir=os.path.join(folder, "figures"))
    assert agent.caption_candidates(path) == [2]             # the chart page; not the logo or text pages
    monkeypatch.setattr(V.VisionAgent, "_hosted_model", staticmethod(lambda: "gemini:gemini-3.5-flash-lite"))
    monkeypatch.setattr(V, "vision_chat", lambda model, prompt, image, **k: "Bar chart: revenue by region, Asia 42.")
    indexed = []
    stub = SimpleNamespace(vision_agent=agent, summarizer=SimpleNamespace(load=lambda d: {"summary": "Annual report. More."}),
                           _index_chunks=lambda title, chunks, overview, replace=True: indexed.append((chunks, overview, replace)))
    assert AgenticGraphRAGPipeline._describe_figures(stub, "doc_v", "report.pdf") == 1
    (chunks, overview, replace), = indexed
    assert chunks[0].chunk_id == "doc_v_p2_fig" and chunks[0].page_number == 2 and "Asia 42" in chunks[0].text
    assert overview == "Annual report." and replace is False  # added to the document's text, not instead of it


def test_added_passages_join_a_document_and_re_ingest_replaces_it():
    """A real store: picture descriptions join the text passages; re-ingesting a document replaces all of its rows."""
    from retrieval.lancedb_store import LanceDBStore
    store = LanceDBStore(db_dir=os.path.join(tempfile.mkdtemp(), "lancedb"))

    def chunk(cid, page, text):
        return RetrievedChunk(chunk_id=cid, doc_id="d", page_number=page, text=text, section_title="S")
    text = [chunk(f"d_p{i}_c0", i, f"Passage {i} about revenue.") for i in (1, 2, 3)]
    store.add_chunks(text, [[1.0, 0.0, 0.0, float(i)] for i in range(3)])
    caption = [chunk("d_p2_fig", 2, "Description of the pictures and charts on page 2: a bar chart.")]
    for _ in range(2):  # adding the descriptions again does not duplicate them
        store.add_chunks(caption, [[0.0, 1.0, 0.0, 0.0]], replace=False)
    assert sorted(c.chunk_id for c in store.get_document_chunks("d")) == ["d_p1_c0", "d_p2_c0", "d_p2_fig", "d_p3_c0"]
    store.add_chunks(text[:2], [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 1.0]])
    assert sorted(c.chunk_id for c in store.get_document_chunks("d")) == ["d_p1_c0", "d_p2_c0"]


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


def test_the_reranker_moves_to_the_cpu_when_the_gpu_runs_out_of_memory():
    from retrieval.reranker import ChunkReranker

    class Model:
        device = "mps"

        def to(self, device):
            self.device = device
            return self

        def predict(self, pairs, **k):
            if self.device != "cpu":
                raise RuntimeError("MPS backend out of memory (MPS allocated: 3.02 GiB, other allocations: 27.19 GiB)")
            return [2.0 if "receivables" in text else -2.0 for _, text in pairs]
    reranker = ChunkReranker.__new__(ChunkReranker)
    reranker.model, reranker.model_name, reranker._outputs_logits = Model(), "stub", True
    scores = reranker.score_pairs("net AR", ["Trade receivables, net 1,615.9", "The weather was fine"])
    assert reranker.model.device == "cpu" and scores[0] > 0.8 > 0.2 > scores[1]  # cross-encoder scores, not word overlap


def test_nomic_embeddings_get_their_task_prefixes_and_cache_keys(tmp_path, monkeypatch):
    from retrieval.embeddings import EmbeddingService
    sent = []
    svc = EmbeddingService(model_name="nomic-embed-text", cache_dir=str(tmp_path))
    monkeypatch.setattr(svc, "_embed_ollama", lambda texts: sent.extend(texts) or [[1.0, 0.0]] * len(texts))
    svc.embed_texts(["net sales rose"])
    svc.embed_queries(["net sales rose"])
    svc.embed_queries(["net sales rose"])  # cached
    # A query and a passage of the same text are embedded (and cached) apart.
    assert sent == ["search_document: net sales rose", "search_query: net sales rose"]
    e5 = EmbeddingService(model_name="st:intfloat/multilingual-e5-small", cache_dir=str(tmp_path))
    assert e5._prefix("x", "query") == "query: x" and EmbeddingService("bge-m3", str(tmp_path))._prefix("x", "query") == "x"


def test_search_fuses_the_cross_encoder_order_with_the_hybrid_order():
    from types import SimpleNamespace
    from agents.hybrid_agent import HybridRetrievalAgent
    hybrid = [RetrievedChunk(chunk_id=c, doc_id="d", text=c) for c in "ABCD"]
    relevance = {"A": 0.8, "B": 0.6, "C": 0.4, "D": 0.9}  # alone, the cross-encoder would put D (last in hybrid order) first
    agent = HybridRetrievalAgent(SimpleNamespace(embed_queries=lambda qs: [[1.0]] * len(qs)),
                                 SimpleNamespace(hybrid_search=lambda **k: hybrid),
                                 SimpleNamespace(is_neural=True, score_pairs=lambda q, texts: [relevance[t] for t in texts]))
    top, pool = agent.search(["q"], top_k=2)
    assert [c.chunk_id for c in top] == ["A", "D"] and pool == 4
    assert [c.score for c in top] == [0.8, 0.9] and top[0].retrieval_method == "neural_reranked"  # cross-encoder relevance kept


def test_the_cross_encoder_avoids_apple_gpus(monkeypatch):
    import types
    import torch
    from retrieval import reranker as R
    seen = {}

    class CrossEncoder:
        def __init__(self, name, **kw):
            seen.update(kw)
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=CrossEncoder))
    monkeypatch.setattr(R, "_MODEL_CACHE", {})
    monkeypatch.setattr(R, "_FAILED_MODELS", {})
    assert R._load_cross_encoder("stub") is not None
    assert seen["device"] == ("cuda" if torch.cuda.is_available() else "cpu")  # never "mps": memory grows per input shape


def test_hosted_retrieval_embeddings_say_whether_they_embed_a_query_or_a_passage(monkeypatch):
    from types import SimpleNamespace
    sent = []

    class Reply:
        status_code = 200

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
    monkeypatch.setattr(P, "_http", lambda *a, **k: SimpleNamespace(post=lambda url, headers=None, json=None, **kw: sent.append(json) or Reply()))
    P.openai_embed(P.REGISTRY["nvidia"], "nvidia/nemotron-3-embed-1b", ["x"], kind="query")
    P.openai_embed(P.REGISTRY["nvidia"], "nvidia/nemotron-3-embed-1b", ["x"])
    P.openai_embed(P.REGISTRY["jina"], "jina-embeddings-v3", ["x"], kind="query")
    assert [b.get("input_type") for b in sent[:2]] == ["query", "passage"] and sent[0]["truncate"] == "END"
    assert sent[2]["task"] == "retrieval.query"


def test_rank_fusion_weights_one_ranking_over_another():
    from retrieval.lancedb_store import rrf_fuse
    equal = rrf_fuse([["a", "b"], ["b", "a"]])
    assert equal["a"] == equal["b"]
    weighted = rrf_fuse([["a", "b"], ["b", "a"]], weights=[3.0, 1.0])
    assert weighted["a"] > weighted["b"]


def test_finance_notes_read_the_cover_page_list_of_registered_securities():
    from agents.finance_terms import notes_for, search_terms
    q = "Which debt securities are registered to trade on a national securities exchange under American Express' name as of 2022?"
    assert "Section 12(b)" in notes_for(q) and "there are none" in notes_for(q)
    assert "section 12(b)" in search_terms(q)
    assert "Section 12(b)" not in notes_for("What was the gross margin in FY2022?")
    assert notes_for("How many registered users does the app have?") == "" and search_terms("How many registered users?") == ""


def test_finance_notes_for_capital_intensity_ppne_and_debt():
    from agents.finance_terms import notes_for, search_terms
    from agents.document_intelligence_agent import question_names
    intensity = notes_for("Is Verizon a capital intensive business based on FY 2022 data?")
    assert "capex with revenue" in intensity and "need not use the phrase" in intensity
    assert "capital expenditures" in search_terms("Is 3M a capital-intensive business based on FY2022 data?")
    assert "PPNE" in notes_for("Did Pfizer grow its PPNE between FY20 and FY21?")
    assert "property plant and equipment" in search_terms("Did Pfizer grow its PPNE between FY20 and FY21?")
    assert question_names("Did Pfizer grow its PPNE between FY20 and FY21?") == ["Pfizer"]
    assert "long-term debt" in search_terms("Has Verizon increased its debt on balance sheet between 2022 and 2021?")
    assert "average total debt" not in notes_for("Which debt securities are registered to trade under 3M's name?")
    assert "long-term debt" not in search_terms("Which debt securities are registered to trade under 3M's name?")
    assert "average shareholders' equity" in notes_for("What is After-tax Return on Average Equity for fiscal 2022?")
    assert "no gross profit line" in notes_for("Does Boeing have an improving gross margin profile as of FY2022?")
    assert notes_for("By what percentage has gross profit increased in Q1 of 2023 compared to Q1 of 2022?") == ""


def test_fiscal_years_ending_in_january_are_named_by_the_year_they_end():
    from agents.finance_terms import fiscal_year_note
    note = fiscal_year_note("What percent of Ulta Beauty's FY2023 stock repurchases occurred in Q4 of FY2023?",
                            "Fiscal 2022 (52 weeks ended January 28, 2023) share repurchases of $900.0 million")
    assert "fiscal 2022" in note
    assert fiscal_year_note("What was revenue in FY2022?", "Year ended December 31, 2022: revenue 9,100") == ""
    assert fiscal_year_note("What is ROE for the fiscal year ending January 28, 2023?", "52 weeks ended January 28, 2023") == ""


def test_a_balance_sheet_split_over_two_pages_is_given_whole():
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent

    def chunk(page, text):
        return RetrievedChunk(chunk_id=f"d_p{page}_c0", doc_id="d", text=text, page_number=page, section_title="")
    chunks = [chunk(80, "Item 8. Financial Statements and Supplementary Data. Report of Independent Registered Public Accounting Firm."),
              chunk(81, "Consolidated Balance Sheets (In millions) December 31, 2022 2021 ASSETS Property, plant and equipment "
                        "29,736 27,413 Cash and cash equivalents 85 116 Accounts receivable 334 271 Total current assets 1,250 1,554 "
                        "Goodwill 1,143 1,139 Total assets 25,075 26,075"),
              chunk(82, "Consolidated Balance Sheets (In millions) CAPITALIZATION AND LIABILITIES Common stockholders' equity 7,976 "
                        "7,231 Retained earnings 1,029 868 Long-term debt 10,926 10,341 Accounts payable 236 227 Total current "
                        "liabilities 2,811 4,554 Total capitalization and liabilities 25,075 26,075 Accrued taxes 49 176 Other 1,129 "
                        "Short-term debt 1,175 584 Current portion of long-term debt 281 57 Accrued interest 88 86"),
              chunk(83, "Consolidated Statements of Operations (In millions) For the years ended December 31, 2022 2021 2020 "
                        "Operating revenues 3,792 3,930 3,777 Operation and maintenance 1,589 1,777 1,622 Operating income 1,410 "
                        "1,421 1,323 Net income attributable to common shareholders 820 1,263 709")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    picked = agent._statement_passages("Does American Water Works have positive working capital based on FY2022 data?", ["d"], {})
    assert [p.page_number for p in picked] == [81, 82]
    assert [p.page_number for p in agent._statement_passages("What was the FY2022 net income?", ["d"], {})] == [83]


def test_survey_counts_get_the_table_of_sample_sizes():
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent, asks_people_count
    from agents.synthesis_agent import SynthesisAgent
    q = "How many Democratic people in the survey said neither party has 'high ethical standards'?"
    assert asks_people_count(q) and not asks_people_count("What percent of Democrats said neither party has high ethical standards?")
    chunks = [RetrievedChunk(chunk_id="s_p12_c0", doc_id="s", page_number=12, text="Neither party has high ethical standards: "
                             "Democrats 18%, Republicans 13%, Independents 34%."),
              RetrievedChunk(chunk_id="s_p17_c0", doc_id="s", page_number=17, text="Methodology. Group Unweighted sample size "
                             "Plus or minus Total sample 1,503 2.9 percentage points Rep/Lean Rep 625 4.5 Dem/Lean Dem 710 4.2 "
                             "Sample sizes and sampling errors for other subgroups are available upon request.")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    out = agent.run({"user_query": q, "document_ids": ["s"], "chunk_context": [{**chunks[0].model_dump(), "score": 0.9}]})
    assert [c["chunk_id"] for c in out["chunk_context"] if c["retrieval_method"] == "reference"] == ["s_p17_page"]
    sources = [{"n": n, "kind": "chunk", "doc_id": "s", "page": c.page_number, "_text": c.text, "snippet": c.text}
               for n, c in enumerate(chunks, 1)]
    prompt = SynthesisAgent()._build_user_prompt({}, q, sources)
    assert "SURVEY COUNTS" in prompt
    assert "SURVEY COUNTS" not in SynthesisAgent()._build_user_prompt({}, "What percent of Democrats said so?", sources)


def test_a_name_one_word_away_from_the_evidence_is_called_another_name():
    from agents.document_intelligence_agent import name_variants
    from agents.synthesis_agent import SynthesisAgent
    text = "MQA Executive Leadership: Lucy C. Gee, Lola Pouncey. Rotary and Mission Systems sales grew. Wave II results."
    assert name_variants("HAQ Executive Leadership", text) == ["MQA Executive Leadership"]
    assert name_variants("Wave III", text) == ["Wave II"]
    assert name_variants("Rotary and Mission Sytems", text) == []  # a misspelling, not another name
    assert name_variants("MMDU", text) == []
    sources = [{"n": 1, "kind": "chunk", "doc_id": "d", "page": 3, "_text": text, "snippet": text}]
    prompt = SynthesisAgent()._build_user_prompt({"absent_terms": ["HAQ Executive Leadership"]},
                                                 "How many people are there in the HAQ Executive Leadership?", sources)
    assert '"HAQ Executive Leadership" (the evidence has "MQA Executive Leadership", another name)' in prompt


def test_a_page_named_by_number_is_also_read_where_that_number_is_printed():
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent, printed_page_offset, page_texts
    from agents.evidence_selection_agent import EvidenceSelectionAgent
    from agents.citations import build_sources
    from agents.synthesis_agent import SynthesisAgent
    from agents.vision_agent import printed_pages_hint
    body = {1: "Strategic Plan 2016-2018 cover", 2: "Executive Summary ........ 1 Planning Summary ........ 8"}
    body.update({p: f"Version 1.3 {p - 3} " + ("Monitoring Summary: the diagram Leadership, Workforce and Infrastructure"
                                               if p == 12 else f"Section text of page {p} with 2.5 percent growth in 2016.")
                 for p in range(4, 18)})
    body[3] = "Table of contents"
    chunks = [RetrievedChunk(chunk_id=f"d_p{p}_c0", doc_id="d", page_number=p, text=t) for p, t in sorted(body.items())]
    assert printed_page_offset(page_texts(chunks)) == 3
    assert printed_page_offset({p: f"Page {p} of the report, {p * 7} words" for p in range(1, 12)}) == 0  # numbered by position
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    hits = agent._reference_hits("page", "9", chunks, numbered=True)
    assert [(h.page_number, h.section_title or "") for h in hits] == [(9, ""), (12, "printed page 9")]
    assert [h.page_number for h in agent._reference_hits("page", "1", chunks)] == [1]  # "the cover page": a position
    q = "What is the title of the diagram on page 9?"
    added = agent.run({"user_query": q, "document_ids": ["d"], "chunk_context": []})["chunk_context"]
    reranker = SimpleNamespace(score_pairs=lambda q, texts: [0.5 for _ in texts])
    package = EvidenceSelectionAgent(reranker=reranker).run({"user_query": q, "session_id": "s", "chunk_context": added})["evidence_package"]
    sources = build_sources(evidence_package=package)
    assert any(s.get("section") == "printed page 9" and s.get("page") == 12 for s in sources)
    assert "PAGE NUMBERS" in SynthesisAgent()._build_user_prompt({}, q, sources)
    assert "the page printed 9 is page 12" in printed_pages_hint(q, 3) and printed_pages_hint(q, 0) == ""


def test_the_vision_agent_reads_a_named_page_and_where_its_number_is_printed(monkeypatch):
    import fitz
    import agents.vision_agent as V
    folder = tempfile.mkdtemp()
    os.makedirs(os.path.join(folder, "uploads"))
    doc = fitz.open()
    for p in range(1, 15):
        page = doc.new_page()
        page.insert_text((72, 40), f"Version 1.3 {p - 3}" if p > 3 else "Cover")
        page.insert_text((72, 300), f"Body text of this page about the plan's goals and measures, item {p * 11}.")
    doc.save(os.path.join(folder, "uploads", "doc_n.pdf"))
    assert V.pdf_page_offset(os.path.join(folder, "uploads", "doc_n.pdf")) == 3
    agent = V.VisionAgent(images_dir=os.path.join(folder, "figures"))
    state = {"document_ids": ["doc_n"], "user_query": "What is the title of the diagram on page 9?", "chunk_context": []}
    assert [f["page"] for f in agent._page_candidates(state, strict=False, limit=6)][:2] == [9, 12]


def test_a_defined_ratio_is_given_as_a_decimal_unless_a_percentage_is_asked():
    from agents.finance_terms import notes_for
    roa = notes_for("What is the FY2017 return on assets (ROA) for Coca Cola? ROA is defined as: FY2017 net income / (average "
                    "total assets between FY2016 and FY2017). Round your answer to two decimal places.")
    assert "0.0146 is 0.01" in roa
    assert "0.0146" not in notes_for("What is the FY2019 EBITDA % margin? EBITDA is defined as operating income + D&A. Round to "
                                     "one decimal place.")


def test_printed_page_numbers_come_from_the_stored_pdf_when_the_passages_lost_them():
    import fitz
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent
    folder = tempfile.mkdtemp()
    doc = fitz.open()
    for p in range(1, 31):
        page = doc.new_page()
        page.insert_text((72, 300), "Body text of this page.")
        if p > 18:
            page.insert_text((72, 800), f"{p - 18}   T480 User Guide")  # a footer the parser drops
    doc.save(os.path.join(folder, "doc_t.pdf"))
    chunks = [RetrievedChunk(chunk_id=f"doc_t_p{p}_c0", doc_id="doc_t", page_number=p, text="Body text of this page.")
              for p in range(1, 31)]
    store = SimpleNamespace(get_document_chunks=lambda doc_id: chunks)
    q = "What is shown on page 4?"
    without = DocumentIntelligenceAgent(store).run({"user_query": q, "document_ids": ["doc_t"], "chunk_context": []})
    assert [c["page_number"] for c in without["chunk_context"]] == [4]
    with_pdf = DocumentIntelligenceAgent(store, files_dir=folder).run({"user_query": q, "document_ids": ["doc_t"], "chunk_context": []})
    assert [(c["page_number"], c["section_title"]) for c in with_pdf["chunk_context"]][1] == (22, "printed page 4")


def test_a_question_about_registered_securities_gets_the_cover_page():
    from types import SimpleNamespace
    from agents.document_intelligence_agent import DocumentIntelligenceAgent
    chunks = [RetrievedChunk(chunk_id="m_p1_c0", doc_id="m", page_number=1, text="FORM 10-Q 3M COMPANY Securities registered "
                             "pursuant to Section 12(b) of the Act: Title of each class Trading Symbol(s) Name of each exchange "
                             "Common Stock MMM New York Stock Exchange 1.500% Notes due 2026 MMM26 New York Stock Exchange"),
              RetrievedChunk(chunk_id="m_p40_c0", doc_id="m", page_number=40, text="Medium-term notes program, Series F.")]
    agent = DocumentIntelligenceAgent(SimpleNamespace(get_document_chunks=lambda doc_id: chunks))
    q = "Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2023?"
    out = agent.run({"user_query": q, "document_ids": ["m"], "chunk_context": [{**chunks[1].model_dump(), "score": 0.9}]})
    assert [c["chunk_id"] for c in out["chunk_context"] if c["retrieval_method"] == "reference"] == ["m_p1_page"]
    assert agent.run({"user_query": "How many registered users?", "document_ids": ["m"], "chunk_context": []})["chunk_context"] == []
