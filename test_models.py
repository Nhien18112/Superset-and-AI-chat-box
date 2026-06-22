import os
import urllib.request
import json

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    # Try reading from .env
    with open(".env") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.strip().split("=")[1].strip('"\'')
                break

if not api_key:
    print("No API key found")
    exit(1)

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print("Available models:")
        for model in data.get("models", []):
            if "generateContent" in model.get("supportedGenerationMethods", []):
                print(f"- {model['name'].split('models/')[-1]}")
except Exception as e:
    print(f"Error listing models: {e}")
