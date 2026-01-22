import streamlit as st
import tempfile
import os
from loader import load_uploaded_document
from intent import detect_intent
from router import route
from image_loader import extract_images_with_captions

st.set_page_config(page_title="OmniDoc", layout="wide")

st.title("📄 OmniDoc")
st.caption("LLM-powered document Q&A, summarization, and extraction")

# ---------- SESSION STATE ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "document_context" not in st.session_state:
    st.session_state.document_context = None

if "image_data" not in st.session_state:
    st.session_state.image_data = None

# ---------- UPLOAD ----------
uploaded_file = st.file_uploader(
    "Upload a document",
    type=["pdf", "docx"]
)

if uploaded_file:
    try:
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

        st.success(f"Document loaded ({len(st.session_state.document_context)} characters)")
        st.session_state.messages = []

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

# ---------- MODERN CHAT INTERFACE ----------
# Render existing messages
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

# Chat input (replaces old text_input + Run)
query = st.chat_input("Ask something about the document…")

if query:
    if not st.session_state.document_context:
        st.warning("Please upload a document first.")
    else:
        # Save user message
        st.session_state.messages.append({
            "role": "user",
            "content": query
        })

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Use your current backend logic
                    task = detect_intent(query)
                    response = route(task, query, st.session_state.document_context)

                    relevant_images = find_relevant_images(query, st.session_state.image_data)

                    # Display text
                    st.write(response)

                    # Display relevant images inline
                    if relevant_images:
                        for img in relevant_images:
                            st.image(
                                img["image"],
                                caption=f"Page {img['page']}: {img['caption']}",
                                use_container_width=True
                            )

                    # Save assistant message
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "images": relevant_images if relevant_images else []
                    })

                except Exception as e:
                    st.error(str(e))