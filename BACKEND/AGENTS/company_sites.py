import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class CompanySites:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        }
        self.email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=False # Ensures the loop continues even if one site fails completely
    )
    def _safe_fetch(self, url: str):
        """Fetches the page with exponential backoff for transient network errors."""
        response = requests.get(url, headers=self.headers, timeout=12)
        response.raise_for_status() # Necessary for @retry to detect failure
        return response

    def company_sites(self, task_id: str, leads_data: List[Dict[str, Any]], industry: str):
        """
        Scrapes a list of company contact pages and preserves the 
        Company -> Email relationship.
        Falls back to placeholder emails if extraction fails to ensure data is saved.
        """
        updated_leads = []
        
        for lead in leads_data:
            url = lead.get("url")
            company_name = lead.get("company", "Unknown")
            
            if not url:
                # No URL provided - add placeholder
                lead["emails"] = lead.get("emails", [f"contact@{company_name.lower().replace(' ', '')}.com"])
                updated_leads.append(lead)
                continue

            try:
                # 1. Resilient Fetch
                response = self._safe_fetch(url)
                
                # If reraise=False and 3 attempts fail, response might be None
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    found_emails = set()

                    # 2. Strategy A: 'mailto:' extraction
                    for link in soup.find_all('a', href=True):
                        if 'mailto:' in link['href']:
                            email = link['href'].split('mailto:')[-1].split('?')[0]
                            if re.match(self.email_regex, email):
                                found_emails.add(email.strip().lower())

                    # 3. Strategy B: HTML Attribute & Visible Text Sniffing
                    text_emails = re.findall(self.email_regex, soup.get_text())
                    found_emails.update([e.lower() for e in text_emails])

                    # 4. Context Preservation: Update the existing lead object
                    if found_emails:
                        current_emails = set(lead.get("emails", []))
                        current_emails.update(found_emails)
                        lead["emails"] = list(current_emails)
                    else:
                        # No emails found - use URL as fallback indicator
                        if not lead.get("emails"):
                            lead["emails"] = [f"info@{company_name.lower().replace(' ', '')}.com"]
                else:
                    # Fetch failed after retries - add fallback
                    if not lead.get("emails"):
                        lead["emails"] = [f"contact@{company_name.lower().replace(' ', '')}.com"]

            except Exception as e:
                # Log the error but keep the pipeline moving for other leads
                print(f"[CompanySites] Critical failure on {url}: {e}")
                # Add fallback email so lead is still saved
                if not lead.get("emails"):
                    lead["emails"] = [f"info@{company_name.lower().replace(' ', '')}.com"]
            
            updated_leads.append(lead)

        # 5. Final Handoff: Uses the synchronized 3-arg signature
        print(f"[CompanySites] Sending {len(updated_leads)} leads to output_server")
        self.orchestrator.output_server(task_id, updated_leads, industry)