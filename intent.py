import json
import ollama

OLLAMA_MODEL = "mistral:latest"

SYSTEM_PROMPT = """
You are an intent classification engine.

Your task is to classify the user's request into exactly ONE of the following tasks:

1. question_answering
2. summarization
3. information_extraction

Rules:
- Respond with ONLY valid JSON
- Do NOT explain
- Do NOT add extra text
- Output format must be: {"task": "<task_name>"}
"""


def detect_intent(user_prompt: str) -> str:
    """
    Detect user intent: QA, summarization, or extraction.
    Falls back to question_answering if detection fails.
    """
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            stream=False
        )
        
        raw_output = response["message"]["content"].strip()
        parsed = json.loads(raw_output)
        return parsed.get("task", "question_answering")
    
    except json.JSONDecodeError:
        print("⚠️ Intent detection: Invalid JSON response, defaulting to question_answering")
        return "question_answering"
    except Exception as e:
        print(f"⚠️ Intent detection failed: {e}, defaulting to question_answering")
        return "question_answering"


if __name__ == "__main__":
    test_prompts = [
        "What does the contract say about termination?",
        "Summarize the key risks in this document",
        "Extract all API endpoints and their purpose"
    ]

    for p in test_prompts:
        intent = detect_intent(p)
        print(f"{p} → {intent}")