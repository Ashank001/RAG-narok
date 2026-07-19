# pyrefly: ignore [missing-import]
import google.generativeai as genai
import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"Model Name: {m.name}")