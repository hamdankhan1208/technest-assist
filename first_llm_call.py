import os
import sys

from groq import Groq, GroqError
from ollama import chat

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
MESSAGES = [
    {
        "role": "user",
        "content": (
            "You are helping build TechNest Assist, an assistant for a "
            "technology retailer. In two short sentences, explain what "
            "you can help a customer with."
        ),
    }
]


def _ollama_response(messages):
    response = chat(
        model=OLLAMA_MODEL,
        messages=messages,
    )
    return response.message.content


def generate_response(messages):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("GROQ_API_KEY is unset; using Ollama.", file=sys.stderr)
        return _ollama_response(messages)

    try:
        response = Groq(api_key=api_key).chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
        )
    except GroqError as error:
        print(
            f"Groq request failed ({type(error).__name__}); falling back to Ollama.",
            file=sys.stderr,
        )
        return _ollama_response(messages)

    return response.choices[0].message.content or ""


def main() -> None:
    print(generate_response(MESSAGES))


if __name__ == "__main__":
    main()
