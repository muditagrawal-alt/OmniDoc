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
    file_path = input("Enter document path: ").strip()
    document = load_document(file_path)

if file_path.lower().endswith(".pdf"):
    from image_loader import extract_images_with_captions
    image_context = extract_images_with_captions(file_path)
    document = document + "\n\n" + image_context

    rag = RAGPipeline()
    rag.ingest(document)

    print("Document indexed with RAG")

    while True:
        q = input("\nQuery (or exit): ").strip()
        if q.lower() == "exit":
            break

        task = detect_intent(q)
        retrieved_chunks = rag.retrieve(q)

        context = "\n\n".join(retrieved_chunks)
        answer = route(task, q, context)

        print("\n--- ANSWER ---")
        print(answer)