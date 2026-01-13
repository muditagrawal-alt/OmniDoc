import streamlit as st
from pipeline import handle_query  # your existing function
from loader import load_document  # if you have a function to load docs

st.set_page_config(page_title="OmniDoc", page_icon="📄")

st.title("OmniDoc 📄")
st.write("Upload a document and ask questions or summarize it.")

# --- Document Upload ---
uploaded_file = st.file_uploader("Choose a PDF or DOCX file", type=["pdf", "docx"])
document_context = ""
if uploaded_file is not None:
    try:
        document_context = load_document(uploaded_file)
        st.success("Document loaded successfully!")
    except Exception as e:
        st.error(f"Error loading document: {e}")

# --- User Query ---
user_query = st.text_input("Enter your query or summarization request:")

if st.button("Run"):
    if not uploaded_file:
        st.warning("Please upload a document first!")
    elif not user_query.strip():
        st.warning("Please enter a query or summarization request!")
    else:
        with st.spinner("Processing..."):
            try:
                result = handle_query(user_query, document_context)
                st.markdown("---")
                st.subheader("Result")
                st.write(result)
            except Exception as e:
                st.error(f"Error: {e}")