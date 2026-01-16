import streamlit as st

from loader import load_uploaded_document
from intent import detect_intent
from router import route

st.set_page_config(page_title="OmniDoc", layout="wide")

st.title("📄 OmniDoc")
st.caption("LLM-powered document Q&A, summarization, and extraction")

# Upload document
uploaded_file = st.file_uploader(
    "Upload a document",
    type=["pdf", "docx"]
)

document_context = None

if uploaded_file:
    try:
        document_context = load_uploaded_document(uploaded_file)
        st.success(f"Document loaded ({len(document_context)} characters)")
    except Exception as e:
        st.error(str(e))

st.divider()

# User query
query = st.text_input("Ask something about the document")

if st.button("Run") and query:
    if not document_context:
        st.warning("Please upload a document first.")
    else:
        with st.spinner("Thinking..."):
            task = detect_intent(query)
            try:
                response = route(task, query, document_context)
                st.subheader(f"Detected task: `{task}`")
                st.write(response)
            except Exception as e:
                st.error(str(e))