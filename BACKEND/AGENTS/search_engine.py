import os
import requests
import json
from dotenv import load_dotenv
from typing import Set

# Load .env from the root folder (one level up from AGENTS/)
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)

class SearchEngine:
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY")
        self.url = "https://google.serper.dev/search"
        self.headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        if not self.api_key:
            raise ValueError("SERPER_API_KEY not found in .env file.")

    def _call_serper(self, query: str, num: int = 10, page: int = 1) -> Set[str]:
        """Internal helper to handle the Serper API POST request."""
        payload = json.dumps({
            "q": query,
            "num": num,
            "page": page
        })
        
        try:
            response = requests.post(self.url, headers=self.headers, data=payload)
            response.raise_for_status()
            results = response.json()
            
            # Extract URLs from organic results
            urls = {item['link'] for item in results.get('organic', [])}
            return urls
        except Exception as e:
            print(f"Serper API Error for query '{query}': {e}")
            return set()

    def company_names(self, names: Set[str]) -> Set[str]:
        """
        Receives company names and finds their contact pages.
        """
        contact_urls = set()
        for name in names:
            # Explicitly search for the contact page
            query = f"{name} official contact page"
            results = self._call_serper(query, num=3) # Get top 3 to ensure accuracy
            contact_urls.update(results)
            
        return contact_urls

    def prompt_listings(self, prompt: str) -> Set[str]:
        """
        Searches for categories on listing sites based on a prompt.
        Example: "real estate agents Nairobi site:yellowpages.co.ke"
        """
        # We assume the prompt is already optimized for a listing search
        return self._call_serper(prompt, num=50)

    def search_prompt(self, prompt: str) -> Set[str]:
        """
        Gathers 200+ unique URL results for a given prompt via pagination.
        """
        all_urls = set()
        
        # Serper allows up to 100 results per page. 
        # We request 3 pages to ensure we cross the 200+ threshold.
        for page_num in range(1, 4):
            page_results = self._call_serper(prompt, num=100, page=page_num)
            all_urls.update(page_results)
            
            # Optimization: Stop if we aren't getting new results
            if len(page_results) == 0:
                break
                
        return all_urls

# Example usage (for testing):
if __name__ == "__main__":
    engine = SearchEngine()
    # print(engine.search_prompt("software companies in Nairobi"))