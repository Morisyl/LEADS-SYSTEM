# File: BACKEND/AGENTS/search_engine.py

import os
import requests
import json
from dotenv import load_dotenv
from typing import Set
from concurrent.futures import ThreadPoolExecutor, as_completed

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)

_SEARCH_WORKERS = 5  # parallel Serper agents

class SearchEngine:
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY")
        self.url     = "https://google.serper.dev/search"
        self.headers = {
            'X-API-KEY':    self.api_key,
            'Content-Type': 'application/json',
        }
        if not self.api_key:
            raise ValueError("SERPER_API_KEY not found in .env file.")

    def _call_serper(self, query: str, num: int = 10, page: int = 1) -> Set[str]:
        payload = json.dumps({"q": query, "num": num, "page": page})
        try:
            response = requests.post(self.url, headers=self.headers,
                                     data=payload, timeout=10)
            response.raise_for_status()
            return {item['link'] for item in response.json().get('organic', [])}
        except Exception as e:
            print(f"[SearchEngine] Serper error for '{query}': {e}")
            return set()

    def _search_one(self, name: str) -> Set[str]:
        """Single-company search — runs inside a thread."""
        return self._call_serper(f"{name} official contact page", num=3)

    def company_names(self, names: Set[str]) -> Set[str]:
        """
        Searches all company names in parallel using 5 worker threads.
        A batch of 100 names that took ~100s serially now takes ~20s.
        """
        contact_urls: Set[str] = set()
        with ThreadPoolExecutor(max_workers=_SEARCH_WORKERS) as executor:
            futures = {executor.submit(self._search_one, name): name
                       for name in names}
            for future in as_completed(futures):
                try:
                    contact_urls.update(future.result())
                except Exception as e:
                    print(f"[SearchEngine] Thread error for '{futures[future]}': {e}")
        return contact_urls

    def prompt_listings(self, prompt: str) -> Set[str]:
        return self._call_serper(prompt, num=50)

    def search_prompt(self, prompt: str) -> Set[str]:
        all_urls: Set[str] = set()
        for page_num in range(1, 4):
            page_results = self._call_serper(prompt, num=100, page=page_num)
            all_urls.update(page_results)
            if not page_results:
                break
        return all_urls