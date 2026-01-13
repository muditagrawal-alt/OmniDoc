import json
from llm import call_llm

INTENTS = {
    "question_answering",
    "summarization",
    "information_extraction",
}

SYSTEM_PROMPT = """
You are an intent classification engine.

Classify the user's request into EXACTLY ONE of the following tasks:
- question_answering
- summarization
- information_extraction

Rules:
- Respond with ONLY valid JSON
- Do NOT explain
- Do NOT add extra text
- Output format must be:
  {"task": "<task_name>"}
"""


def detect_intent(user_query: str) -> str:
    response = call_llm(
        prompt=user_query,
        system=SYSTEM_PROMPT
    )

    try:
        parsed = json.loads(response)
        task = parsed.get("task")

        if task not in INTENTS:
            raise ValueError(f"Invalid intent: {task}")

        return task

    except Exception:
        # Hard fallback — keeps system alive
        return "question_answering"


if __name__ == "__main__":
    tests = [
        "What does the contract say about termination?",
        "Summarize the key risks in this document",
        "Extract all API endpoints and their purpose",
        "Explain what this document is about",
    ]

    for t in tests:
        print(f"{t} → {detect_intent(t)}")