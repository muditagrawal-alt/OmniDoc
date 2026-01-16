import os
from docx import Document
import fitz  # PyMuPDF

from intent import detect_intent
from router import route

from rag import RAGPipeline   # NEW


def load_pdf(file_path: str) -> str:
    text = ""
    doc = fitz.open(file_path)
    for page in doc:
        text += page.get_text()
    return text


def load_docx(file_path: str) -> str:
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs])


def load_document(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return load_pdf(file_path)
    elif ext == ".docx":
        return load_docx(file_path)
    else:
        raise ValueError("Unsupported file type. Please upload PDF or DOCX.")


# ---------------- RAG-AWARE QUERY HANDLER ----------------

rag = RAGPipeline()

def handle_query(user_query: str):
    task = detect_intent(user_query)

    retrieved_chunks = rag.retrieve(user_query, top_k=5)
    context = "\n\n".join(retrieved_chunks)

    return route(task, user_query, context)


# ---------------- CLI ENTRY ----------------

if __name__ == "__main__":
    print("Enter the path of the document you want to summarize/Q&A on:")
    file_path = input().strip()

    try:
        document_text = load_document(file_path)
        rag.ingest(document_text)   # 🔥 INGEST ONCE
        print("Document indexed successfully.")
    except Exception as e:
        print(f"Error loading document: {e}")
        exit(1)

    while True:
        print("\nEnter your query (or 'exit'):", end=" ")
        q = input().strip()
        if q.lower() == "exit":
            break

        answer = handle_query(q)
        print("\n--- RESULT ---")
        print(answer)
        print("--------------")