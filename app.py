import streamlit as st
import tempfile
import os

from loader import load_uploaded_document
from intent import detect_intent
from router import route
from image_loader import extract_images_with_captions
from chat_ui import render_chat_ui

st.set_page_config(page_title="OmniDoc", layout="wide")

st.title("📄 OmniDoc")
st.caption("LLM-powered document Q&A, summarization, and extraction")

# ---------- SESSION STATE ----------
if "document_context" not in st.session_state:
    st.session_state.document_context = None

if "image_data" not in st.session_state:
    st.session_state.image_data = None

# 🔒 Document guard
if "doc_key" not in st.session_state:
    st.session_state.doc_key = None

# ---------- UPLOAD ----------
uploaded_file = st.file_uploader(
    "Upload a document",
    type=["pdf", "docx"]
)

if uploaded_file:
    try:
        doc_key = f"{uploaded_file.name}_{uploaded_file.size}"

        # 🔒 Reset conversations ONLY if document changes
        if st.session_state.doc_key != doc_key:
            st.session_state.doc_key = doc_key

            # reset conversations safely
            if "conversations" in st.session_state:
                st.session_state.conversations = {}
                st.session_state.active_chat = None

        st.session_state.document_context = load_uploaded_document(uploaded_file)

        if uploaded_file.name.lower().endswith(".pdf"):
            with st.spinner("Extracting figures from document..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getbuffer())
                    pdf_path = tmp.name

                image_context, image_data = extract_images_with_captions(pdf_path)
                st.session_state.document_context += "\n\n" + image_context
                st.session_state.image_data = image_data

                os.remove(pdf_path)

        st.success(
            f"Document loaded ({len(st.session_state.document_context)} characters)"
        )

    except Exception as e:
        st.error(str(e))

st.divider()

# ---------- IMAGE MATCHING ----------
def find_relevant_images(query, images, top_k=2):
    if not images:
        return []

    query_words = set(query.lower().split())
    scored_images = []

    for img in images:
        caption_words = set(img["caption"].lower().split())
        overlap = query_words.intersection(caption_words)

        if overlap:
            score = len(overlap) / len(query_words)
            scored_images.append((score, img))

    scored_images.sort(key=lambda x: x[0], reverse=True)
    return [img for _, img in scored_images[:top_k]]

# ---------- CHAT UI ----------
query = render_chat_ui()

if query:
    if not st.session_state.document_context:
        st.warning("Please upload a document first.")
    else:
        chat = st.session_state.conversations[st.session_state.active_chat]

        # auto-title chat
        if chat["title"] == "New conversation":
            chat["title"] = query[:40]

        # save user message
        chat["messages"].append({
            "role": "user",
            "content": query
        })

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    task = detect_intent(query)
                    response = route(
                        task,
                        query,
                        st.session_state.document_context
                    )

                    relevant_images = find_relevant_images(
                        query,
                        st.session_state.image_data
                    )

                    st.write(response)

                    for img in relevant_images:
                        st.image(
                            img["image"],
                            caption=f"Page {img['page']}: {img['caption']}",
                            use_container_width=True
                        )

                    # save assistant message
                    chat["messages"].append({
                        "role": "assistant",
                        "content": response,
                        "images": relevant_images
                    })

                except Exception as e:
                    st.error(str(e))
                    lol