OmniDoc

Overview

OmniDoc is a local, LLM-powered document intelligence system for querying, summarizing, and extracting information from PDF and DOCX documents, including diagrams and figures inside PDFs.

It combines Retrieval-Augmented Generation (RAG) with image understanding to answer questions strictly using content present in the document.

⸻

Key Features
	•	📄 Question answering over uploaded documents
	•	🧠 Automatic intent detection (QA / summarization / extraction)
	•	📚 RAG-based retrieval for large documents
	•	🖼️ Diagram & image extraction from PDFs
	•	📝 Image captioning using BLIP
	•	🔍 Context-only answers (hallucination controlled)
	•	🖥️ Streamlit-based interactive UI
	•	🔒 Fully local execution using Ollama

⸻

How It Works
	1.	User uploads a PDF or DOCX document
	2.	Text is extracted from the document
	3.	(PDF only) Images are extracted page-wise
	4.	Images are captioned using a vision-language model
	5.	Captions are merged into the document context
	6.	Document is indexed using embeddings
	7.	User query intent is classified
	8.	Relevant chunks are retrieved
	9.	LLM answers strictly from retrieved context
	10.	Relevant diagrams are shown only if required

⸻

Tech Stack
	•	UI: Streamlit
	•	LLM: Mistral (via Ollama)
	•	Embeddings: nomic-embed-text
	•	RAG: Custom in-memory retrieval pipeline
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

Current Limitations
	•	Image relevance matching is caption-based (no visual embeddings yet)
	•	Duplicate or weakly-related diagrams may appear in some queries
	•	Large PDFs may slow down image captioning

⸻

Planned Improvements
	•	Image deduplication using perceptual hashing
	•	Cross-modal retrieval (text ↔ image embeddings)
	•	Smarter diagram relevance ranking
	•	Optional vector database support
	•	Architecture visualization export

⸻

Why OmniDoc?

OmniDoc is designed for controlled, explainable document intelligence where accuracy and source-grounding matter more than raw generation.
