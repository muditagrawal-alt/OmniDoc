"""Task routing with RAG and web search integration."""
from llm import call_llm
from web_search import WebSearcher

SYSTEMS = {
    "question_answering": (
        "You are a helpful assistant. Answer ONLY using the provided document context and web results. "
        "If the answer is not present in either source, say: 'Not found in provided sources.' "
        "Be concise and cite sources when applicable."
    ),
    "summarization": (
        "Summarize ONLY the provided document context. "
        "Do not add external knowledge unless from web search results. "
        "Focus on key points and insights."
    ),
    "information_extraction": (
        "Extract structured information strictly from the provided context. "
        "Return data in a clear, organized format (lists, tables, JSON if appropriate). "
        "If data is missing, indicate it explicitly."
    ),
}


def route(
    task: str,
    query: str,
    context: str,
    retrieved_chunks: list = None,
    use_web_search: bool = False
) -> tuple:
    """
    Route query to appropriate handler with RAG and optional web search.
    
    Returns:
        (response_text, search_results_used, cited_sources)
    """
    if task not in SYSTEMS:
        raise ValueError(f"Unsupported task: {task}")
    
    # Prepare context from RAG chunks
    rag_context = ""
    if retrieved_chunks:
        rag_context = "\n\n--- RELEVANT DOCUMENT CHUNKS ---\n"
        for i, (idx, chunk, score) in enumerate(retrieved_chunks, 1):
            rag_context += f"\n[Chunk {i} - Relevance: {score:.2f}]:\n{chunk}\n"
    else:
        rag_context = f"\n--- FULL DOCUMENT ---\n{context}"
    
    # Web search if needed
    web_results = []
    web_context = ""
    if use_web_search and WebSearcher.should_use_web_search(query):
        print("🌐 Fetching real-time information...")
        web_results = WebSearcher.search_duckduckgo(query, max_results=3)
        web_context = WebSearcher.format_search_results(web_results)
    
    # Final prompt
    prompt = f"""
{rag_context}
{web_context}

USER QUERY:
{query}
"""
    
    response = call_llm(
        prompt=prompt,
        system=SYSTEMS[task]
    )
    
    return response, web_results, rag_context[:500] if rag_context else ""
