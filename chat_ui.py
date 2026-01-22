import streamlit as st
import tempfile
import os

from loader import load_uploaded_document
from intent import detect_intent
from router import route
from image_loader import extract_images_with_captions


def init_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "document_context" not in st.session_state:
        st.session_state.document_context = None

    if "image_data" not in st.session_state:
        st.session_state.image_data = None


def find_relevant_images(query, images, max_images=2):
    if not images:
        return []

    q = query.lower()

    trigger_words = [
        "diagram", "figure", "architecture",
        "flow", "workflow", "network",
        "topology", "layout", "structure"
    ]

    explicit_request = any(w in q for w in trigger_words)

    scored = []
    for img in images:
        score = sum(word in img["search_text"] for word in q.split())
        if explicit_request or score > 0:
            scored.append((score, img))

    scored.sort(reverse=True, key=lambda x: x[0])
    return [img for _, img in scored[:max_images]]


def render_chat_ui():
    init_session()

    st.title("📄 OmniDoc")
    st.caption("Chat with your documents")

    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.header("📄 Document")
        uploaded_file = st.file_uploader(
            "Upload PDF or DOCX",
            type=["pdf", "docx"]
        )

        if uploaded_file:
            with st.spinner("Processing document..."):
                document_context = load_uploaded_document(uploaded_file)

                image_data = None
                if uploaded_file.name.lower().endswith(".pdf"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.getbuffer())
                        pdf_path = tmp.name

                    image_context, image_data = extract_images_with_captions(pdf_path)
                    document_context += "\n\n" + image_context
                    os.remove(pdf_path)

                st.session_state.document_context = document_context
                st.session_state.image_data = image_data
                st.session_state.messages = []

            st.success("Document loaded and indexed")

    # ---------- CHAT HISTORY ----------
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

            if msg.get("images"):
                for img in msg["images"]:
                    st.image(
                        img["image"],
                        caption=f"Page {img['page']}: {img['caption']}",
                        use_container_width=True
                    )

    # ---------- USER INPUT ----------
    query = st.chat_input("Ask OmniDoc…")

    if query and st.session_state.document_context:
        st.session_state.messages.append({
            "role": "user",
            "content": query
        })

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
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

                if relevant_images:
                    for img in relevant_images:
                        st.image(
                            img["image"],
                            caption=f"Page {img['page']}: {img['caption']}",
                            use_container_width=True
                        )

        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "images": relevant_images if relevant_images else []
        })

    elif query:
        st.warning("Please upload a document first.")