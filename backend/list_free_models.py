import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("LLM_API_KEY")

response = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {api_key}"}
)

data = response.json()
for model in data["data"]:
    pricing = model.get("pricing", {})
    if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
        print(model["id"])