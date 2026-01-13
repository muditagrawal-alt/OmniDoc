# loader.py
from docx import Document
import PyPDF2

def load_document(file) -> str:
    """
    Load text from a PDF or DOCX file.
    
    :param file: A file-like object from Streamlit uploader
    :return: String of document text
    """
    text = ""

    if file.name.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() + "\n"

    elif file.name.endswith(".docx"):
        doc = Document(file)
        for para in doc.paragraphs:
            text += para.text + "\n"

    else:
        raise ValueError("Unsupported file type. Please upload PDF or DOCX.")

    return text.strip()