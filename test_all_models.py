import os
import urllib.request
import json
import time

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    with open(".env") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.strip().split("=")[1].strip('"\'')
                break

if not api_key:
    print("No API key found")
    exit(1)

def get_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        return [m["name"].split("models/")[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]

def test_model(model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": "Hello, this is a test."}]}]
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print(f"[SUCCESS] {model}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[FAILED] {model} - {e.code} {e.reason}")
        return False
    except Exception as e:
        print(f"[FAILED] {model} - {e}")
        return False

models = get_models()
print(f"Testing {len(models)} models...")

success_models = []
for m in models:
    if test_model(m):
        success_models.append(m)
    time.sleep(0.5)

print("\n--- Summary ---")
if success_models:
    print("Models that worked: " + ", ".join(success_models))
else:
    print("ALL models failed!")
