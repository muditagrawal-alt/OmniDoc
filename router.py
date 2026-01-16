from llm import call_llm

SYSTEMS = {
    "question_answering": (
        "Answer ONLY using the provided document context. "
        "If the answer is not present, say: 'Not found in document.'"
    ),
    "summarization": (
        "Summarize ONLY the provided document context. "
        "Do not add external knowledge."
    ),
    "information_extraction": (
        "Extract structured information strictly from the provided context. "
        "If data is missing, leave it blank."
    ),
}

def route(task: str, query: str, context: str) -> str:
    if task not in SYSTEMS:
        raise ValueError(f"Unsupported task: {task}")

    prompt = f"""
DOCUMENT CONTEXT:
{context}

USER TASK:
{query}
"""

    return call_llm(
        prompt=prompt,
        system=SYSTEMS[task]
    )