import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

base_url = (os.getenv("LLM_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
api_key = os.getenv("LLM_API_KEY")

client = OpenAI(
    base_url=base_url,
    api_key=api_key,
)

response = client.chat.completions.create(
    model=(os.getenv("LLM_MODELS") or "nemotron-3-ultra-free").split(",")[0].strip(),
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)

print(response.choices[0].message.content)
