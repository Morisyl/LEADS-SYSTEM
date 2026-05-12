# File: BACKEND/AGENTS/company_sites.py

import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Max simultaneous outbound connections.
# 20 is safe for most home/VPS connections; raise to 30 if network allows.
_MAX_WORKERS = 20

class CompanySites:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        }
        self.email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=False,
    )
    def _safe_fetch(self, url: str):
        """Fetches the page with exponential backoff for transient network errors."""
        response = requests.get(url, headers=self.headers, timeout=12)
        response.raise_for_status()
        return response

    def _process_lead(self, lead: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetches and scrapes a single lead's contact URL.
        Designed to run inside a thread — never raises, always returns the lead.
        """
        url          = lead.get("url")
        company_name = lead.get("company", "Unknown")

        if not url:
            lead.setdefault("emails", [f"contact@{company_name.lower().replace(' ', '')}.com"])
            return lead

        try:
            response = self._safe_fetch(url)

            if response and response.status_code == 200:
                soup        = BeautifulSoup(response.text, 'html.parser')
                found_emails = set()

                # Strategy A: mailto: links
                for link in soup.find_all('a', href=True):
                    if 'mailto:' in link['href']:
                        email = link['href'].split('mailto:')[-1].split('?')[0]
                        if re.match(self.email_regex, email):
                            found_emails.add(email.strip().lower())

                # Strategy B: raw text scan
                found_emails.update(
                    e.lower() for e in re.findall(self.email_regex, soup.get_text())
                )

                if found_emails:
                    current = set(lead.get("emails", []))
                    current.update(found_emails)
                    lead["emails"] = list(current)
                else:
                    lead.setdefault("emails", [f"info@{company_name.lower().replace(' ', '')}.com"])
            else:
                lead.setdefault("emails", [f"contact@{company_name.lower().replace(' ', '')}.com"])

        except Exception as e:
            print(f"[CompanySites] Critical failure on {url}: {e}")
            lead.setdefault("emails", [f"info@{company_name.lower().replace(' ', '')}.com"])

        return lead

    def company_sites(self, task_id: str, leads_data: List[Dict[str, Any]], industry: str):
        """
        Scrapes all company contact pages in parallel using a thread pool,
        then hands results to output_server preserving original order.
        """
        # Preserve insertion order: map future → original index
        ordered_results: List[Dict[str, Any]] = [None] * len(leads_data)

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_idx = {
                executor.submit(self._process_lead, lead): idx
                for idx, lead in enumerate(leads_data)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    ordered_results[idx] = future.result()
                except Exception as e:
                    # Should never reach here since _process_lead swallows exceptions,
                    # but belt-and-suspenders: keep the original lead object.
                    print(f"[CompanySites] Unexpected thread error at index {idx}: {e}")
                    ordered_results[idx] = leads_data[idx]

        updated_leads = [r for r in ordered_results if r is not None]
        print(f"[CompanySites] Sending {len(updated_leads)} leads to output_server")
        self.orchestrator.output_server(task_id, updated_leads, industry)