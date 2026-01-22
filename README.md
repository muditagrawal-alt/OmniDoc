OmniDoc

OmniDoc is a local, LLM-powered document intelligence system for querying, summarizing, and extracting information from PDF and DOCX documents, including diagrams and figures inside PDFs.

It combines Retrieval-Augmented Generation (RAG) with image understanding to answer questions using only the content present in the document.

⸻

Features
	•	📄 Question answering over documents
	•	🧠 Automatic intent detection
	•	📚 RAG-based retrieval for large documents
	•	🖼️ Diagram & image extraction from PDFs
	•	🖼️ Image captioning using BLIP
	•	🔍 Context-only answers (hallucination controlled)
	•	🖥️ Streamlit-based UI
	•	🔒 Runs locally using Ollama

⸻

How It Works
	1.	Upload a PDF or DOCX
	2.	Text is extracted from the document
	3.	(PDF only) Images are extracted and captioned
	4.	Captions are merged into document context
	5.	Document is indexed using embeddings
	6.	User query is classified (QA / summary / extraction)
	7.	Relevant chunks are retrieved
	8.	LLM answers strictly from retrieved context
	9.	Relevant diagrams are shown only if needed

⸻

Tech Stack
	•	UI: Streamlit
	•	LLM: Mistral (Ollama)
	•	Embeddings: nomic-embed-text
	•	RAG: Custom in-memory pipeline
	•	PDF Parsing: PyMuPDF
	•	DOCX Parsing: python-docx
	•	Image Captioning: BLIP
	•	Image Processing: Pillow

⸻

Project Structure

OmniDoc/
├── app.py            # Streamlit UI
├── pipeline.py       # CLI pipeline
├── loader.py         # Document loaders
├── rag.py            # RAG logic
├── intent.py         # Intent detection
├── router.py         # Task routing
├── llm.py            # LLM interface
├── image_loader.py   # Image extraction & captioning
└── README.md


⸻

Installation

1. Install Ollama

https://ollama.com

2. Pull Required Models

ollama run mistral
ollama pull nomic-embed-text

3. Install Python Dependencies

pip install streamlit pymupdf python-docx transformers pillow torch


⸻

Run the App

streamlit run app.py

Then upload a document and start querying.

⸻

Example Queries
	•	“Explain the network topology diagram”
	•	“Summarize this document”
	•	“Extract all APIs mentioned”
	•	“Show the architecture diagram related to routing”

Relevant diagrams are displayed automatically when useful.

⸻

Limitations
	•	Image relevance is caption-based
	•	No OCR for scanned PDFs
	•	Vector store is in-memory
	•	Tables are treated as text

⸻

Future Improvements
	•	OCR for scanned documents
	•	Vision embeddings for image relevance
	•	Vector database (FAISS / Chroma)
	•	Table structure extraction
	•	Faster image caching

⸻

License

Internal / Educational use

⸻

Author

Built by Mudit