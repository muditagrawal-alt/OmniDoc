# router.py
from llm import call_llm

SYSTEMS = {
    "question_answering": "You answer questions strictly from the provided document context.",
    "summarization": "You summarize documents clearly and concisely.",
    "information_extraction": "You extract structured information accurately.",
}

def route(task: str, query: str, context: str) -> str:
    if task not in SYSTEMS:
        raise ValueError(f"Unsupported task: {task}")

    prompt = f"""
DOCUMENT:
{context}

TASK:
{query}
"""

    return call_llm(
        prompt=prompt,
        system=SYSTEMS[task]
    )