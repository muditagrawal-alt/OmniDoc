# OmniDoc

OmniDoc is a **local, LLM-powered document intelligence system** for querying, summarizing, and extracting information from **PDF and DOCX documents**, including diagrams and figures inside PDFs.

It combines **Retrieval-Augmented Generation (RAG)** with **image understanding** to answer questions strictly using document content.

---

## 🚀 Features

- 📄 Question answering over documents
- 🧠 Automatic intent detection (QA / summary / extraction)
- 📚 RAG-based retrieval for large documents
- 📊 Diagram & image extraction from PDFs
- 🖼️ Image captioning using BLIP
- 🔍 Context-only answers (hallucination controlled)
- 🖥️ Streamlit-based UI
- 🔐 Runs fully locally using Ollama

---

## 🧠 How It Works

1. User uploads a PDF or DOCX file  
2. Text is extracted from the document  
3. *(PDF only)* Images are extracted using PyMuPDF  
4. Images are captioned using BLIP  
5. Captions are merged into document context  
6. Document is indexed using embeddings  
7. User query intent is detected  
8. Relevant chunks are retrieved via RAG  
9. LLM answers **strictly from retrieved context**  
10. Relevant diagrams are shown **only when useful**

---

## 🧰 Tech Stack

### UI
- Streamlit

### LLM
- Mistral (via Ollama)

### Embeddings
- `nomic-embed-text`

### RAG
- Custom in-memory pipeline

### Document Parsing
- PDF: PyMuPDF  
- DOCX: python-docx

### Image Understanding
- Image Captioning: BLIP  
- Image Processing: Pillow

---

## 🗂️ Project Structure

```text
OmniDoc/
│
├── app.py                # Streamlit UI
├── pipeline.py           # CLI pipeline
├── loader.py             # Document loaders
├── rag.py                # RAG logic
├── intent.py             # Intent detection
├── router.py             # Task routing
├── llm.py                # LLM interface
├── image_loader.py       # Image extraction & captioning
├── README.md


⸻

⚠️ Current Limitations
	•	Image relevance is caption-based (no vision embeddings yet)
	•	Duplicate images can appear in PDFs with reused assets
	•	Image ranking is keyword-based (semantic ranking pending)

⸻

🔮 Planned Improvements
	•	Vision embeddings for semantic image retrieval
	•	Image deduplication using perceptual hashing
	•	Cross-modal (text ↔ image) relevance scoring
	•	Persistent vector store (FAISS / Chroma)
	•	Multi-document support

⸻

🧪 Local Setup

pip install -r requirements.txt
ollama pull mistral
streamlit run app.py


⸻

📌 Why OmniDoc?
	•	Fully local and privacy-preserving
	•	No hallucinated answers
	•	Designed for technical, academic, and enterprise documents
	•	Extensible to multimodal RAG systems

---

## Final blunt truth

- Your **logic and content were solid**
- Your **Markdown formatting was wrong**
- GitHub was doing exactly what it should

This version will render **perfectly point-wise** in GitHub view.

If you want next:
- TL/interview **explanation version**
- Defense/research-oriented README
- Architecture diagram (text or visual)

Say the word.
