import os
from docx import Document
import fitz  # PyMuPDF
from router import route
from intent import detect_intent

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

def handle_query(user_query: str, doc_content: str) -> str:
    task = detect_intent(user_query)
    return route(task, user_query, doc_content)

if __name__ == "__main__":
    print("Enter the path of the document you want to summarize/Q&A on:")
    file_path = input().strip()

    try:
        DOCUMENT_CONTEXT = load_document(file_path)
        print(f"Loaded document: {len(DOCUMENT_CONTEXT)} characters")
    except Exception as e:
        print(f"Error loading document: {e}")
        exit(1)

    while True:
        print("\nEnter your query (or 'exit'):", end=" ")
        q = input().strip()
        if q.lower() == "exit":
            break
        answer = handle_query(q, DOCUMENT_CONTEXT)
        print("\n--- RESULT ---")
        print(answer)
        print("--------------")