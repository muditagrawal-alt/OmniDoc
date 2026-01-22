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

# ---------- UPLOAD ----------
uploaded_file = st.file_uploader(
    "Upload a document",
    type=["pdf", "docx"]
)

document_context = None
image_data = None

if uploaded_file:
    try:
        document_context = load_uploaded_document(uploaded_file)

        if uploaded_file.name.lower().endswith(".pdf"):
            with st.spinner("Extracting figures from document..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getbuffer())
                    pdf_path = tmp.name

                image_context, image_data = extract_images_with_captions(pdf_path)
                document_context += "\n\n" + image_context

                os.remove(pdf_path)

        st.success(f"Document loaded ({len(document_context)} characters)")

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

    # Sort by relevance score (highest first)
    scored_images.sort(key=lambda x: x[0], reverse=True)

    # Return only top-k images
    return [img for _, img in scored_images[:top_k]]

# ---------- QUERY ----------
query = st.text_input("Ask something about the document")

if st.button("Run") and query:
    if not document_context:
        st.warning("Please upload a document first.")
    else:
        with st.spinner("Thinking..."):
            try:
                task = detect_intent(query)
                response = route(task, query, document_context)

                st.subheader(f"Detected task: `{task}`")
                st.write(response)

                relevant_images = find_relevant_images(query, image_data)

                if relevant_images:
                    st.markdown("### 📊 Relevant Diagrams")
                    for img in relevant_images:
                        st.image(
                            img["image"],
                            caption=f"Page {img['page']}: {img['caption']}",
                            use_container_width=True
                        )

            except Exception as e:
                st.error(str(e))