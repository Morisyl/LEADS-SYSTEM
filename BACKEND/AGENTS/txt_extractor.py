import re
import os
from groq import Groq
from dotenv import load_dotenv
from typing import List, Dict, Set, Any
import json

load_dotenv()

class TxtExtractor:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def extract_leads_structured(self, doc_dict: Dict[int, str]) -> List[Dict[str, Any]]:
        structured_leads = []

        for page_num, text in doc_dict.items():
            # 1. Ask Groq to pair emails with companies specifically
            prompt = (
                "Extract company names and their associated emails from the text below. "
                "Return the result strictly as a valid JSON object where keys are company names "
                "and values are lists of emails found for that company. "
                "Format: {'Company Name': ['email1@site.com', 'email2@site.com']}. "
                "If no emails are found for a company, return an empty list for that key. "
                f"\n\nText:\n{text[:4000]}"
            )

            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="llama-3.3-70b-versatile",
                    response_format={"type": "json_object"} # Force JSON mode
                )
                
                # 2. Parse the JSON response
                raw_json = chat_completion.choices[0].message.content
                extracted_data = json.loads(raw_json)

                # 3. Build the lead objects
                for company, emails in extracted_data.items():
                    structured_leads.append({
                        "company": company,
                        "emails": emails,
                        "url": None # To be filled by Serper later
                    })
            except Exception as e:
                print(f"Extraction error on page {page_num}: {e}")

        return structured_leads

    def _groq_parse_entities(self, messy_text: str) -> Set[str]:
        """Uses Groq to fix OCR typos and identify valid company names."""
        prompt = (
            "The following text is from a messy OCR scan. "
            "1. Fix obvious typos. 2. Identify all official company names. "
            "Return ONLY a comma-separated list of names. If none, return 'None'.\n\n"
            f"Text:\n{messy_text[:4000]}" # Truncate to save tokens
        )
        
        try:
            completion = self.client.chat.completions.create(
                model="llama-3.1-70b-versatile",
                messages=[{"role": "user", "content": prompt}]
            )
            res = completion.choices[0].message.content
            if "None" in res: return set()
            return {n.strip() for n in res.split(",") if n.strip()}
        except Exception as e:
            print(f"Groq Entity Error: {e}")
            return set()