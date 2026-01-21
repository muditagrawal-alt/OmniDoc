# pipeline.py
import os
import fitz
from docx import Document
from intent import detect_intent
from router import route
from rag import RAGPipeline

def load_pdf(path):
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc)

def load_docx(path):
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

def load_document(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return load_pdf(path)
    elif ext == ".docx":
        return load_docx(path)
    else:
        raise ValueError("Only PDF and DOCX supported")

if __name__ == "__main__":
    # Load the document
    file_path = input("Enter document path: ").strip()
    document = load_document(file_path)

    # If it's a PDF, extract image captions and append to the text
    if file_path.lower().endswith(".pdf"):
        from image_loader import extract_images_with_captions
        image_context, _ = extract_images_with_captions(file_path)
        document = document + "\n\n" + image_context

    # Initialize RAG with the combined context
    rag = RAGPipeline()
    rag.ingest(document)

    print("Document indexed with RAG")

    # Query loop
    while True:
        q = input("\nQuery (or exit): ").strip()
        if q.lower() == "exit":
            break

        # Detect task
        task = detect_intent(q)

        # Retrieve relevant chunks from RAG
        retrieved_chunks = rag.retrieve(q)

        # Join retrieved chunks for context
        context = "\n\n".join(retrieved_chunks)

        # Get LLM answer
        answer = route(task, q, context)

        print("\n--- ANSWER ---")
        print(answer)