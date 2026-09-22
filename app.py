"""
OmniDoc - Enterprise-grade document Q&A with RAG, image extraction, and web search.
"""
import streamlit as st
import tempfile
import os
import hashlib
import uuid
from pathlib import Path
import requests

from loader import load_uploaded_document
from intent import detect_intent
from router import route
from image_loader import extract_images_with_captions, extract_images_from_docx, find_relevant_images_semantic
from chat_ui import render_chat_ui
from rag import RAGPipeline
from db_store import OmniDocDB
from web_search import WebSearcher
from core.pipeline import AgenticGraphRAGPipeline

# ============================================================================
# CONFIGURATION & INITIALIZATION
# ============================================================================

st.set_page_config(
    page_title="🎓 OmniDoc - Enterprise Document AI",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for enterprise dashboard
st.markdown("""
<style>
    .main { padding: 2rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; }
    [data-testid="stMetricValue"] { font-size: 2rem; }
    .card { 
        border: 1px solid #e0e0e0;
        border-radius: 0.5rem;
        padding: 1.5rem;
        background: #f9f9f9;
    }
</style>
""", unsafe_allow_html=True)

# Initialize database
if "db" not in st.session_state:
    st.session_state.db = OmniDocDB()

# Initialize session state
if "document_context" not in st.session_state:
    st.session_state.document_context = None
if "document_id" not in st.session_state:
    st.session_state.document_id = None
if "document_name" not in st.session_state:
    st.session_state.document_name = None
if "rag_pipeline" not in st.session_state:
    st.session_state.rag_pipeline = None
if "image_data" not in st.session_state:
    st.session_state.image_data = None
if "doc_key" not in st.session_state:
    st.session_state.doc_key = None
if "conversations" not in st.session_state:
    st.session_state.conversations = {}
if "active_chat" not in st.session_state:
    st.session_state.active_chat = None
if "use_web_search" not in st.session_state:
    st.session_state.use_web_search = True
if "use_agentic_rag" not in st.session_state:
    st.session_state.use_agentic_rag = True
if "show_debug" not in st.session_state:
    st.session_state.show_debug = False
if "agentic_pipeline" not in st.session_state:
    try:
        st.session_state.agentic_pipeline = AgenticGraphRAGPipeline()
    except Exception:
        st.session_state.agentic_pipeline = None


# ============================================================================
# OLLAMA HEALTH CHECK
# ============================================================================

@st.cache_resource
def check_ollama_health():
    """Check if Ollama is running."""
    try:
        import ollama
        response = ollama.list()
        return True, "✓ Ollama is running"
    except Exception as e:
        return False, f"✗ Ollama error: {str(e)[:100]}"


def display_ollama_status():
    """Display Ollama connection status."""
    is_healthy, message = check_ollama_health()
    if is_healthy:
        st.success(message)
    else:
        st.error(message)
        st.warning("""
        **Please start Ollama:**
        ```bash
        ollama serve
        ```
        Then pull required models:
        ```bash
        ollama pull mistral
        ollama pull nomic-embed-text
        ```
        """)
        return False
    return True


# ============================================================================
# SIDEBAR & CONTROLS
# ============================================================================

with st.sidebar:
    st.title("⚙️ Settings & Control")
    
    # Status section
    st.subheader("System Status")
    if not display_ollama_status():
        st.stop()
    
    st.divider()
    
    # Settings
    st.subheader("Preferences")
    st.session_state.use_web_search = st.checkbox(
        "🌐 Enable Web Search",
        value=st.session_state.use_web_search,
        help="Enable real-time web search for queries"
    )
    
    st.session_state.use_agentic_rag = st.checkbox(
        "🕸️ Agentic Graph RAG (LangGraph + Kùzu)",
        value=st.session_state.use_agentic_rag,
        help="Use collaborative multi-agent execution with Kùzu property graph, LanceDB hybrid search, and strict guardrails."
    )
    
    st.session_state.show_debug = st.checkbox(
        "🐛 Debug Mode",
        value=st.session_state.show_debug,
        help="Show retrieval scores and metadata"
    )
    
    # Document info
    st.divider()
    st.subheader("📄 Current Document")
    if st.session_state.document_name:
        st.info(f"📌 {st.session_state.document_name}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Clear", use_container_width=True):
                st.session_state.document_context = None
                st.session_state.rag_pipeline = None
                st.session_state.document_name = None
                st.session_state.image_data = None
                st.rerun()
    else:
        st.warning("No document loaded")
    
    # Analytics
    if st.session_state.document_id:
        st.divider()
        st.subheader("📊 Analytics")
        all_chats = st.session_state.db.get_all_chats(st.session_state.document_id)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Chats", len(all_chats))
        with col2:
            total_msgs = sum(len(st.session_state.db.get_messages(chat['id'])) for chat in all_chats)
            st.metric("Messages", total_msgs)


# ============================================================================
# MAIN CONTENT AREA
# ============================================================================

st.title("🎓 OmniDoc")
st.caption("Enterprise-grade document intelligence with RAG, web search, and semantic image retrieval")

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📤 Upload Document")
    uploaded_file = st.file_uploader(
        "Upload a PDF or DOCX file",
        type=["pdf", "docx"],
        help="Supported formats: PDF, DOCX"
    )

with col2:
    st.metric("🤖 Status", "Ready")


# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

if uploaded_file:
    try:
        # Generate document hash for caching
        file_bytes = uploaded_file.read()
        doc_hash = hashlib.md5(file_bytes).hexdigest()
        doc_key = f"{uploaded_file.name}_{doc_hash}"
        
        # Check if document changed
        if st.session_state.doc_key != doc_key:
            st.session_state.doc_key = doc_key
            st.session_state.document_id = str(uuid.uuid4())[:8]
            st.session_state.document_name = uploaded_file.name
            st.session_state.conversations = {}
            st.session_state.active_chat = None
            
            # Register document
            st.session_state.db.add_document(
                st.session_state.document_id,
                uploaded_file.name,
                doc_hash,
                len(file_bytes),
                uploaded_file.name.split(".")[-1].lower()
            )
            
            # Load document
            with st.spinner("📖 Loading document..."):
                st.session_state.document_context = load_uploaded_document(uploaded_file)
            
            # Extract images
            image_context = ""
            st.session_state.image_data = []
            
            if uploaded_file.name.lower().endswith(".pdf"):
                with st.spinner("🖼️ Extracting images from PDF..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(file_bytes)
                        pdf_path = tmp.name
                    
                    image_context, st.session_state.image_data = extract_images_with_captions(pdf_path)
                    os.remove(pdf_path)
            
            elif uploaded_file.name.lower().endswith(".docx"):
                with st.spinner("🖼️ Extracting images from DOCX..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                        tmp.write(file_bytes)
                        docx_path = tmp.name
                    
                    image_context, st.session_state.image_data = extract_images_from_docx(docx_path)
                    os.remove(docx_path)
            
            # Initialize RAG pipeline
            with st.spinner("🧠 Building semantic index (this may take a minute)..."):
                st.session_state.rag_pipeline = RAGPipeline()
                full_context = st.session_state.document_context
                if image_context:
                    full_context += "\n\n" + image_context
                
                success = st.session_state.rag_pipeline.ingest(
                    full_context,
                    document_hash=doc_hash
                )

                # Ingest into Agentic Graph RAG (Docling + LanceDB + Kùzu)
                if st.session_state.agentic_pipeline and st.session_state.use_agentic_rag:
                    with st.spinner("🕸️ Indexing into Knowledge Graph (Kùzu) & LanceDB..."):
                        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_f:
                            tmp_f.write(file_bytes)
                            tmp_file_path = tmp_f.name
                        try:
                            st.session_state.agentic_pipeline.ingest_document(
                                file_path=tmp_file_path,
                                doc_id=st.session_state.document_id,
                                doc_hash=doc_hash
                            )
                        except Exception as e:
                            print(f"Agentic graph ingestion warning: {e}")
                        finally:
                            if os.path.exists(tmp_file_path):
                                os.remove(tmp_file_path)
                
                if success:
                    st.success(f"✅ Document ready! ({len(file_bytes)} bytes, {len(st.session_state.rag_pipeline.chunks)} chunks)")
                    if st.session_state.image_data:
                        st.info(f"🖼️ Extracted {len(st.session_state.image_data)} images")
                else:
                    st.warning("⚠️ Document loaded but semantic indexing failed - using keyword search")
    
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        import traceback
        if st.session_state.show_debug:
            st.code(traceback.format_exc())

st.divider()

# ============================================================================
# CHAT INTERFACE
# ============================================================================

st.subheader("💬 Conversation")

# Sidebar chat history
with st.sidebar:
    st.divider()
    st.subheader("💾 Chat History")
    
    if st.session_state.document_id:
        if st.button("➕ New Chat", use_container_width=True):
            chat_id = str(uuid.uuid4())
            st.session_state.conversations[chat_id] = {
                "title": "New conversation",
                "messages": []
            }
            st.session_state.db.create_chat(chat_id, st.session_state.document_id)
            st.session_state.active_chat = chat_id
            st.rerun()
        
        st.divider()
        
        all_chats = st.session_state.db.get_all_chats(st.session_state.document_id)
        
        for chat in all_chats:
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(chat['title'][:30], use_container_width=True, key=f"chat_{chat['id']}"):
                    st.session_state.active_chat = chat['id']
                    # Load messages from DB
                    messages = st.session_state.db.get_messages(chat['id'])
                    st.session_state.conversations[chat['id']] = {
                        "title": chat['title'],
                        "messages": messages
                    }
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{chat['id']}", use_container_width=True):
                    st.session_state.db.delete_chat(chat['id'])
                    if st.session_state.active_chat == chat['id']:
                        st.session_state.active_chat = None
                    st.rerun()

# Main chat area
query = render_chat_ui()

if query:
    if not st.session_state.document_context:
        st.warning("📁 Please upload a document first.")
    else:
        # Ensure active chat exists
        if st.session_state.active_chat not in st.session_state.conversations:
            chat_id = str(uuid.uuid4())
            st.session_state.conversations[chat_id] = {
                "title": "New conversation",
                "messages": []
            }
            st.session_state.db.create_chat(chat_id, st.session_state.document_id)
            st.session_state.active_chat = chat_id
        
        chat = st.session_state.conversations[st.session_state.active_chat]
        
        # Auto-title chat from first query
        if chat["title"] == "New conversation":
            chat["title"] = query[:50]
            st.session_state.db.update_chat_title(st.session_state.active_chat, chat["title"])
        
        # Save user message
        chat["messages"].append({"role": "user", "content": query})
        st.session_state.db.add_message(st.session_state.active_chat, "user", query)
        
        with st.chat_message("user"):
            st.write(query)
        
        # Process query
        with st.chat_message("assistant"):
            with st.spinner("🤔 Agentic Graph RAG reasoning..."):
                try:
                    if st.session_state.use_agentic_rag and st.session_state.agentic_pipeline:
                        # Extract prior conversation history for multi-turn anaphora resolution
                        prior_history = chat.get("messages", [])[:-1]

                        # Execute via LangGraph Multi-Agent Core
                        result = st.session_state.agentic_pipeline.query(
                            user_query=query,
                            doc_id=st.session_state.document_id,
                            session_id=st.session_state.active_chat,
                            conversation_history=prior_history
                        )
                        
                        response = result.get("verified_response") or result.get("draft_response", "")
                        verification = result.get("verification")
                        intent_contract = result.get("intent")
                        intent_res = result.get("intent_result")
                        graph_data = result.get("graph_context", [])
                        chunks_data = result.get("chunk_context", [])
                        plan = result.get("plan", [])
                        math_results = result.get("math_results", [])
                        visual_artifacts = result.get("visual_artifacts", [])
                        conflicts = result.get("conflicts", [])
                        evidence_pkg = result.get("evidence_package")
                        
                        # Display main cited response
                        st.write(response)

                        # Render Interactive Plotly Charts
                        if visual_artifacts:
                            for va in visual_artifacts:
                                spec = va.get("plotly_spec")
                                if spec:
                                    try:
                                        st.plotly_chart(spec, use_container_width=True)
                                        if va.get("caption"):
                                            st.caption(f"📊 **{va.get('title', 'Chart')}**: {va.get('caption')}")
                                    except Exception as p_err:
                                        st.warning(f"Could not render chart: {p_err}")

                        # Render Exact Mathematical Computations
                        if math_results:
                            for mr in math_results:
                                with st.expander(f"🔢 Mathematical Reasoning: {mr.get('task', 'Computation')}", expanded=True):
                                    if mr.get("formula"):
                                        try:
                                            st.latex(mr.get("formula"))
                                        except Exception:
                                            st.code(mr.get("formula"))
                                    st.markdown(f"**Exact Result:** `{mr.get('exact_result')} {mr.get('units', '')}`")
                                    if mr.get("code_executed"):
                                        st.code(mr.get("code_executed"), language="python")
                                    if mr.get("assumptions"):
                                        st.caption(f"*Assumptions:* {', '.join(mr.get('assumptions'))}")
                        
                        # Groundedness & Faithfulness Badge
                        if verification:
                            score_pct = int(verification.faithfulness_score * 100)
                            if verification.is_grounded:
                                st.success(f"🛡️ **Groundedness Score:** {score_pct}% • Verified by Output Guardrail")
                            else:
                                st.warning(f"⚠️ **Groundedness Score:** {score_pct}% • {verification.feedback}")

                        # Discrepancy & Conflict Audit
                        if conflicts:
                            with st.expander(f"⚖️ Conflict Resolution Audit ({len(conflicts)} Discrepancies Analyzed)", expanded=False):
                                for cf in conflicts:
                                    st.markdown(f"- **Claim:** {cf.get('conflicting_claim')}")
                                    st.markdown(f"  - **Status:** `{cf.get('resolution_status')}` • *Rationale:* {cf.get('rationale')}")
                        
                        # Knowledge Graph Subgraph Explorer
                        if graph_data:
                            for g in graph_data:
                                edges = g.get("edges", [])
                                if edges:
                                    with st.expander(f"🕸️ Knowledge Graph Subgraph ({len(edges)} Relations Traversed)", expanded=False):
                                        for e in edges:
                                            st.markdown(f"- **{e.get('source_name', e.get('source'))}** `[{e.get('relation')}]` ➔ **{e.get('target_name', e.get('target'))}**: *{e.get('description', '')}*")
                        
                        # Multi-Agent Execution Trace & DAG Handoffs
                        if plan:
                            with st.expander("🤖 Multi-Agent Execution Plan & Handoffs", expanded=False):
                                for i, step in enumerate(plan, 1):
                                    st.markdown(f"**Step {i}:** `{step}`")
                                if intent_res:
                                    st.caption(f"**Primary Intent:** `{intent_res.primary_intent}` | **Capabilities:** `{', '.join(intent_res.detected_requirements)}`")
                                elif intent_contract:
                                    st.caption(f"**Intent:** `{intent_contract.primary_intent}` | **Confidence:** `{intent_contract.confidence:.2f}`")

                        chat["messages"].append({
                            "role": "assistant",
                            "content": response,
                            "images": [],
                            "charts": visual_artifacts,
                            "math": math_results
                        })
                        st.session_state.db.add_message(
                            st.session_state.active_chat,
                            "assistant",
                            response
                        )

                    else:
                        # Fallback to legacy single-pass procedural pipeline
                        task = detect_intent(query)
                        retrieved_chunks = []
                        if st.session_state.rag_pipeline:
                            retrieved_chunks = st.session_state.rag_pipeline.retrieve(query, top_k=5)
                        
                        response, web_results, context_used = route(
                            task,
                            query,
                            st.session_state.document_context,
                            retrieved_chunks=retrieved_chunks,
                            use_web_search=st.session_state.use_web_search
                        )
                        
                        relevant_images = []
                        if st.session_state.image_data:
                            relevant_images = find_relevant_images_semantic(
                                query,
                                st.session_state.image_data,
                                top_k=2
                            )
                        
                        st.write(response)
                        if relevant_images:
                            st.subheader("📸 Related Images")
                            for img in relevant_images:
                                col1, col2 = st.columns([1, 2])
                                with col1:
                                    st.image(img["image"], use_container_width=True)
                                with col2:
                                    st.caption(f"📄 Page {img['page']}: {img['caption']}")
                        
                        if web_results:
                            st.subheader("🌐 Web Sources")
                            for i, res_w in enumerate(web_results, 1):
                                st.markdown(f"**{i}. {res_w['title']}**")
                                st.caption(f"[{res_w['link']}]({res_w['link']})")

                        chat["messages"].append({"role": "assistant", "content": response, "images": relevant_images})
                        st.session_state.db.add_message(
                            st.session_state.active_chat,
                            "assistant",
                            response,
                            images=relevant_images
                        )
                    st.session_state.db.add_search_record(
                        st.session_state.active_chat,
                        query,
                        [chunk for _, _, chunk in retrieved_chunks] if retrieved_chunks else [],
                        response
                    )
                
                except Exception as e:
                    st.error(f"❌ Error processing query: {str(e)}")
                    if st.session_state.show_debug:
                        import traceback
                        st.code(traceback.format_exc())

# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("🚀 OmniDoc Enterprise | Privacy-first • Fully Local • No API Keys Required")
