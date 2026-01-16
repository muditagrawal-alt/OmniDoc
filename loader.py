import fitz  # PyMuPDF
from docx import Document
from io import BytesIO


def load_pdf_from_bytes(data: bytes) -> str:
    text = ""
    doc = fitz.open(stream=data, filetype="pdf")
    for page in doc:
        text += page.get_text()
    return text


def load_docx_from_bytes(data: bytes) -> str:
    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def load_uploaded_document(uploaded_file) -> str:
    """
    Accepts a Streamlit UploadedFile object
    """
    if uploaded_file is None:
        raise ValueError("No file uploaded")

    filename = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()

    if filename.endswith(".pdf"):
        return load_pdf_from_bytes(file_bytes)

    elif filename.endswith(".docx"):
        return load_docx_from_bytes(file_bytes)

    else:
        raise ValueError("Unsupported file type. Upload PDF or DOCX only.")