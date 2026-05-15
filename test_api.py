import os
import json
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

print("--- TEST 1: chiamata semplice ---")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=200,
    messages=[{
        "role": "user",
        "content": "Dimmi una parola tedesca utile in ambito farmaceutico. Formato: parola | traduzione italiana | esempio."
    }]
)
print(response.content[0].text)

print("\n--- TEST 2: risposta JSON ---")
response2 = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=400,
    messages=[{
        "role": "user",
        "content": 'Dammi 3 parole tedesche farmaceutiche. Rispondi SOLO con JSON valido, zero testo aggiuntivo, zero backtick. Formato: {"words": [{"german": "...", "italian": "...", "example": "..."}]}'
    }]
)

raw_text = response2.content[0].text
print(f"DEBUG risposta grezza: {repr(raw_text[:150])}")

# Pulizia difensiva
clean_text = raw_text.strip()
if clean_text.startswith("```"):
    lines = clean_text.split("\n")
    clean_text = "\n".join(lines[1:-1]).strip()

data = json.loads(clean_text)

for word in data["words"]:
    print(f"  {word['german']} → {word['italian']}")
    print(f"  Esempio: {word['example']}\n")

print("✅ Tutto funziona.")