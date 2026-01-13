import ollama

MODEL = "mistral:latest"

def call_llm(prompt: str, system: str = "") -> str:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        options={
            "temperature": 0.2,
            "num_ctx": 8192,   # important for long docs later
        }
    )
    return response["message"]["content"]