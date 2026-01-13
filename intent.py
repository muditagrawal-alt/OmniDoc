import subprocess
import json
import sys

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
    prompt = f"""
{SYSTEM_PROMPT}

User request:
\"\"\"{user_prompt}\"\"\"
"""

    try:
        result = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt,
            capture_output=True,
            text=True,
            check=True
        )

        raw_output = result.stdout.strip()
        print(f"RAW LLM OUTPUT: {raw_output}")

        parsed = json.loads(raw_output)
        return parsed["task"]

    except Exception as e:
        print(f"Intent detection failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_prompts = [
        "What does the contract say about termination?",
        "Summarize the key risks in this document",
        "Extract all API endpoints and their purpose"
    ]

    for p in test_prompts:
        intent = detect_intent(p)
        print(f"{p} → {intent}")