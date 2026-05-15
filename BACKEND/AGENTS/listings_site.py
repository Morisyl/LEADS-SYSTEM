import time
import json
import re
import requests
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any, Set, Optional

from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed


from selenium import webdriver                 # kept for EC / By / WebDriverWait usage below
from seleniumbase import Driver                # replaces undetected_chromedriver; stable on Windows
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    InvalidSelectorException,
)

from .groq_helper import GroqRecipeParser


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMAIL_REGEX       = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
WAIT_TIMEOUT      = 15          # seconds to wait for a DOM element
AJAX_SETTLE       = 2           # seconds to wait after clicking a JS pagination button
DEFAULT_MAX_PAGES = 10          # safety cap on pages visited
TIER2_MAX_WORKERS = 5           # parallel threads for Tier 2 subpage scraping
HTML_SNIPPET_LEN  = 3000        # chars of HTML sent to Groq for recipe generation


# ---------------------------------------------------------------------------
# ListingsSiteAgent
# ---------------------------------------------------------------------------

class ListingsSiteAgent:
    """
    Three-tier extraction engine.

    Tier 1  — Emails visible directly on the listing page.
    Tier 2  — Emails live inside per-company subpages linked from the listing.
    Tier 3  — Only company names visible; names → Serper → CompanySites.

    Flow for all tiers
    ──────────────────
    1.  Flutter sends user-clicked selectors + tier choice.
    2.  start_system_sync() sends selectors + HTML snapshot to Groq to
        validate / refine them into a complete recipe.
    3.  The appropriate _execute_tier_N() runs against the live site.
    4.  Results flow to output_server().
    """

    def __init__(self, core):
        self.core  = core
        self.task_id:  Optional[str]            = None
        self.base_url: Optional[str]            = None
        self.driver:   Optional[Driver] = None  # SeleniumBase Driver; webdriver.Chrome subclass
        self.recipe:   Optional[dict]           = None

        self._leads_collected:   List[Dict[str, Any]] = []
        self._company_names_set: Set[str]             = set()

        self._groq    = GroqRecipeParser()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    # =========================================================================
    # DRIVER MANAGEMENT
    # =========================================================================

    def _init_driver(self) -> Driver:
        # SeleniumBase Driver(uc=True) handles all anti-detection patching internally.
        # Do NOT pass ChromeOptions manually — uc mode sets its own flags and adding
        # conflicting arguments (headless=new, excludeSwitches, AutomationControlled)
        # causes the GetHandleVerifier C++ crash seen with undetected-chromedriver.
        driver = Driver(uc=True, headless=True)
        driver.set_page_load_timeout(30)
        return driver

    def _ensure_driver(self):
        if self.driver is None:
            self.driver = self._init_driver()

    def _quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # =========================================================================
    # LIVE FRAME  (polled by ExecutionPage every 500 ms)
    # =========================================================================

    def get_live_frame(self) -> Optional[str]:
        if self.driver is None:
            return None
        try:
            return self.driver.get_screenshot_as_base64()
        except WebDriverException:
            return None

    # =========================================================================
    # TASK SETUP
    # =========================================================================

    def _setup_task(self, task_id: str, url: str):
        self.task_id              = task_id
        self.base_url             = url
        self._leads_collected     = []
        self._company_names_set   = set()
        self._ensure_driver()
        self.driver.get(url)
        self._log("EXTRACTING", f"Browser loaded: {url}")

    # =========================================================================
    # PUBLIC ENTRY POINTS
    # =========================================================================

    def start_system_sync(self, task_id: str, url: str, recipe_json: str):
        """
        Called from Orchestrator.run_trained_extraction() in a background thread.

        recipe_json now contains:
          - tier, primary_selector, pagination_selector, etc.
          - element_html: { primary, pagination, subpage, last_page }  ← outerHTML
          - site_url (the exact URL the user was on during training)
        """
        raw_recipe = json.loads(recipe_json)
        tier       = int(raw_recipe.get("tier", 1))
        site_url   = raw_recipe.get("site_url", url)

        self._setup_task(task_id, url)
        self._log("EXTRACTING", f"Tier {tier} — refining selectors with Groq…")

        # ── Build Groq context ──────────────────────────────────────────────
        # 1. outerHTML captured by the Flutter inspector (what the user clicked)
        element_html = raw_recipe.get("element_html", {})

        # 2. Grab surrounding HTML context: find the primary element on the
        #    live page and extract its parent's innerHTML so Groq sees siblings.
        page_html_context = ""
        primary_sel = raw_recipe.get("primary_selector", "")

        # When manual mode sent "__manual__" we cannot use it as a CSS selector.
        # Fall back to the raw element_html["primary"] value itself — Groq will
        # have the full HTML and can infer sibling structure from it.
        if primary_sel and primary_sel != "__manual__":
            try:
                soup  = BeautifulSoup(self.driver.page_source, "html.parser")
                match = soup.select_one(primary_sel)
                if match and match.parent:
                    page_html_context = str(match.parent)[:1500]
                elif match:
                    page_html_context = str(match)[:1500]
            except Exception:
                page_html_context = ""
        else:
            # Use the manually-pasted element HTML as context so Groq is not blind.
            page_html_context = element_html.get("primary", "")[:1500]

        user_selectors = {
            "primary_selector":    raw_recipe.get("primary_selector",    ""),
            "pagination_selector": raw_recipe.get("pagination_selector", ""),
            "subpage_selector":    raw_recipe.get("subpage_selector",    ""),
            "last_page_selector":  raw_recipe.get("last_page_selector",  ""),
        }

        self.recipe = self._groq.generate_recipe(
            tier               = tier,
            site_url           = site_url,
            element_html       = element_html,
            user_selectors     = user_selectors,
            page_html_context  = page_html_context,
        )
        self.recipe["max_pages"] = int(raw_recipe.get(
            "last_page_number",
            raw_recipe.get("max_pages", DEFAULT_MAX_PAGES)
        ))
        self.recipe.setdefault("last_page_number", self.recipe["max_pages"])

        self._log("EXTRACTING",
                  f"Recipe ready — primary: '{self.recipe.get('primary_selector')}' | "
                  f"pagination: '{self.recipe.get('pagination_selector')}' | "
                  f"method: {self.recipe.get('method')}")

        # ── Validate selectors before running ─────────────────────────────
        try:
            self._validate_selectors()
        except ValueError as e:
            self._log("FAILED", f"Selector validation failed: {e}")
            self.core.update_task_memory(task_id, "FAILED", str(e))
            self._quit_driver()
            return

        try:
            if tier == 1:
                self._execute_tier_1()
            elif tier == 2:
                self._execute_tier_2()
            elif tier == 3:
                self._execute_tier_3()
            else:
                raise ValueError(f"Unknown tier: {tier}")

            self._finalize(task_id)

        except Exception as e:
            self._log("FAILED", f"Extraction error: {e}")
            self.core.update_task_memory(task_id, "FAILED", f"Engine error: {e}")
        finally:
            self._quit_driver()

    def listings_site(self, task_id: str, url: str, industry: str):
        """
        Called by Orchestrator.run_listing_pipeline() for text-prompt searches.
        Checks the DB for a saved recipe for this domain, skips if none.
        """
        domain     = urlparse(url).netloc
        recipe_row = self.core.db.query_recipe(domain)
        if not recipe_row:
            self._log("EXTRACTING", f"No recipe for {domain} — skipping.")
            return

        recipe = {
            "tier":               1,
            "primary_selector":   recipe_row["selectors"].get("item_container", ""),
            "pagination_selector":recipe_row["selectors"].get("next_button",    ""),
            "subpage_selector":   recipe_row["selectors"].get("subpage",        ""),
            "method":             recipe_row.get("pagination_type", "BS4").upper(),
        }
        self.start_system_sync(task_id, url, json.dumps(recipe))

    # =========================================================================
    # SELECTOR VALIDATION
    # =========================================================================

    def _validate_selectors(self):
        """
        Test each selector against the live DOM before the extraction loop starts.
        Raises ValueError with a descriptive message if a critical selector is broken.
        """
        tier = self.recipe.get("tier", 1)

        critical = ["primary_selector"]
        if tier == 2:
            critical.append("subpage_selector")

        for key in critical:
            sel = self.recipe.get(key, "").strip()
            if not sel:
                raise ValueError(
                    f"'{key}' is empty. Please re-capture this element in the inspector."
                )
            try:
                # BeautifulSoup test
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                results = soup.select(sel)
                self._log("EXTRACTING",
                          f"Selector '{sel}' matched {len(results)} element(s) via BS4.")
            except Exception as e:
                raise ValueError(
                    f"CSS selector '{sel}' is invalid for BeautifulSoup: {e}. "
                    f"Please re-capture the element."
                )

            try:
                # Selenium test
                found = self.driver.find_elements(By.CSS_SELECTOR, sel)
                self._log("EXTRACTING",
                          f"Selector '{sel}' matched {len(found)} element(s) via Selenium.")
            except InvalidSelectorException as e:
                raise ValueError(
                    f"CSS selector '{sel}' is invalid for Selenium: {e}. "
                    f"Please re-capture the element."
                )

    # =========================================================================
    # TIER 1  — Emails directly on the listing pages
    # =========================================================================

    def _execute_tier_1(self):
        """
        Iterates paginated listing pages extracting emails using the
        Groq-validated selector and regex pattern.
        """
        method       = self.recipe.get("method", "BS4").upper()
        max_pages    = self.recipe.get("max_pages", DEFAULT_MAX_PAGES)
        primary_sel  = self.recipe.get("primary_selector", "")
        regex_pat    = self.recipe.get("regex_pattern", EMAIL_REGEX.pattern)
        pages_done   = 0

        try:
            item_regex = re.compile(regex_pat)
        except re.error:
            item_regex = EMAIL_REGEX

        target_attribute = self.recipe.get("target_attribute", "text")

        self._log("EXTRACTING",
                f"Tier 1 start | selector='{primary_sel}' | "
                f"attr='{target_attribute}' | regex='{regex_pat}' | method={method}")
        current_url = self.base_url

        while current_url and pages_done < max_pages:
            try:
                self._log("EXTRACTING", f"📄 Page {pages_done + 1}/{max_pages}: {current_url}")

                if method == "BS4":
                    soup = self._bs4_fetch(current_url)
                    if soup is None:
                        self._log("EXTRACTING", f"❌ Failed to fetch page {pages_done + 1}, skipping")
                        break
                else:  # SELENIUM
                    if self.driver.current_url != current_url:
                        self._log("EXTRACTING", f"🌐 Navigating to: {current_url}")
                        self.driver.get(current_url)
                    
                    try:
                        self._log("EXTRACTING", f"⏳ Waiting for selector: {primary_sel}")
                        self._wait_for_selector(primary_sel)
                        self._log("EXTRACTING", f"✓ Selector found, parsing page")
                    except TimeoutException:
                        self._log("EXTRACTING", f"⚠️ Wait selector timed out — proceeding without wait")
                        # You can keep the screenshot line here for debugging purposes without crashing the app:
                        self.driver.save_screenshot(f"timeout_page_{pages_done + 1}.png")
                        
                    soup = BeautifulSoup(self.driver.page_source, "html.parser")

                # DOM-first extraction
                extracted: Set[str] = set()
                elements_found = soup.select(primary_sel)
                self._log("EXTRACTING", f"🔍 Found {len(elements_found)} elements matching selector")
                
                if len(elements_found) == 0:
                    self._log("EXTRACTING", f"⚠️ WARNING: No elements matched selector '{primary_sel}'")
                
                for idx, el in enumerate(elements_found):
                    value = self._dom_extract(el, target_attribute, regex_pat)
                    if value:
                        extracted.add(value.lower())
                        # Log every 10th extraction to avoid spam
                        if idx % 10 == 0 or len(elements_found) < 20:
                            self._log("EXTRACTING", f"✓ Extracted: '{value[:50]}...'")

                self._absorb_emails(extracted, current_url)
                self._log("EXTRACTING", 
                        f"✅ Page {pages_done + 1} complete: {len(extracted)} values extracted | "
                        f"📊 Total leads: {len(self._leads_collected)}")

                if method == "BS4":
                    current_url = self._next_url_from_soup(soup, current_url)
                    if current_url:
                        self._log("EXTRACTING", f"➡️ Next page URL: {current_url}")
                    else:
                        self._log("EXTRACTING", f"🏁 No more pages found")
                else:
                    if self._is_last_page(pages_done):
                        self._log("EXTRACTING", "🏁 Last page indicator found, stopping")
                        break
                    next_url = self._selenium_next_page()
                    if next_url:
                        current_url = next_url
                        self._log("EXTRACTING", f"➡️ Moving to next page")
                    else:
                        self._log("EXTRACTING", f"🏁 No next page button found")
                        break

                pages_done += 1
                
            except Exception as e:
                self._log("EXTRACTING", f"❌ ERROR on page {pages_done + 1}: {type(e).__name__}: {str(e)}")
                import traceback
                traceback.print_exc()
                
                # Try to continue to next page
                if method != "BS4":
                    try:
                        self._log("EXTRACTING", f"🔄 Attempting to recover and continue...")
                        current_url = self._selenium_next_page()
                        if current_url is None:
                            self._log("EXTRACTING", f"❌ Recovery failed, stopping extraction")
                            break
                        pages_done += 1
                    except:
                        self._log("EXTRACTING", f"❌ Recovery failed, stopping extraction")
                        break
                else:
                    break

        self._log("EXTRACTING",
                f"🎉 Tier 1 complete. Processed {pages_done} pages. "
                f"📊 {len(self._leads_collected)} lead records accumulated.")

    # =========================================================================
    # TIER 2  — Emails inside subpages
    # =========================================================================

    def _execute_tier_2(self):
        """
        Phase A: Walk main listing pages, collect all subpage hrefs.
        Phase B: Fetch every subpage in parallel, extract emails using
                the Groq-validated subpage_selector and regex_pattern.
        """
        max_pages      = self.recipe.get("max_pages", DEFAULT_MAX_PAGES)
        pages_done     = 0
        primary_sel    = self.recipe.get("primary_selector", "")
        pagination_sel = self.recipe.get("pagination_selector", "")
        subpage_sel    = self.recipe.get("subpage_selector",    "")
        method         = self.recipe.get("method", "SELENIUM").upper()
        regex_pat      = self.recipe.get("regex_pattern", EMAIL_REGEX.pattern)

        target_attribute = self.recipe.get("target_attribute", "text")

        self._log("EXTRACTING",
                f"🎯 Tier 2 — Phase A: Collecting subpage links")
        self._log("EXTRACTING",
                f"   Primary selector: '{primary_sel}'")
        self._log("EXTRACTING",
                f"   Subpage selector: '{subpage_sel}'")
        self._log("EXTRACTING",
                f"   Regex pattern: '{regex_pat}'")

        all_subpage_urls: List[str] = []

        # PHASE A: Collect all subpage links
        while pages_done < max_pages:
            try:
                self._log("EXTRACTING", f"📄 Main listing page {pages_done + 1}/{max_pages}")
                
                try:
                    self._log("EXTRACTING", f"⏳ Waiting for selector: {primary_sel}")
                    self._wait_for_selector(primary_sel)
                    self._log("EXTRACTING", f"✓ Selector found, parsing page")
                except TimeoutException:
                    self._log("EXTRACTING", f"⚠️ Wait selector timed out — proceeding without wait")
                    # You can keep the screenshot line here for debugging purposes without crashing the app:
                    self.driver.save_screenshot(f"timeout_page_{pages_done + 1}.png")

                if method == "BS4":
                    soup = BeautifulSoup(self.driver.page_source, "html.parser")
                    elements = soup.select(primary_sel)
                    self._log("EXTRACTING", f"🔍 Found {len(elements)} listing items")
                    
                    for el in elements:
                        href = el.get("href") or (el.find("a") or {}).get("href")
                        if href:
                            all_subpage_urls.append(urljoin(self.driver.current_url, href))
                else:
                    elements = self._safe_find_elements(primary_sel)
                    self._log("EXTRACTING", f"🔍 Found {len(elements)} listing items via Selenium")
                    
                    for idx, el in enumerate(elements):
                        href = el.get_attribute("href")
                        if not href:
                            try:
                                from selenium.webdriver.common.by import By
                                from selenium.common.exceptions import NoSuchElementException
                                child = el.find_element(By.TAG_NAME, "a")
                                href  = child.get_attribute("href")
                            except NoSuchElementException:
                                pass
                        if href and not href.startswith("javascript"):
                            all_subpage_urls.append(href)
                            # Log every 10th link
                            if idx % 10 == 0:
                                self._log("EXTRACTING", f"   Found link: {href[:60]}...")

                unique_count = len(set(all_subpage_urls))
                self._log("EXTRACTING", f"📊 Total subpage links collected: {unique_count}")

                if self._is_last_page(pages_done):
                    self._log("EXTRACTING", "🏁 Last page reached")
                    break
                
                next_url = self._selenium_next_page()
                if next_url is None:
                    self._log("EXTRACTING", "🏁 No next page button found")
                    break
                
                self._log("EXTRACTING", f"➡️ Moving to page {pages_done + 2}")
                pages_done += 1
                
            except Exception as e:
                self._log("EXTRACTING", f"❌ Error collecting links on page {pages_done + 1}: {str(e)}")
                import traceback
                traceback.print_exc()
                break

        all_subpage_urls = list(dict.fromkeys(all_subpage_urls))
        self._log("EXTRACTING",
                f"✅ Phase A complete: {len(all_subpage_urls)} unique subpage URLs")
        
        if len(all_subpage_urls) == 0:
            self._log("EXTRACTING", "❌ No subpages found, stopping Tier 2")
            return

        # PHASE B: Scrape all subpages in parallel
        self._log("EXTRACTING", f"🚀 Phase B: Scraping {len(all_subpage_urls)} subpages (parallel)")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        successful_scrapes = 0
        failed_scrapes = 0
        
        with ThreadPoolExecutor(max_workers=TIER2_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    self._scrape_subpage, url, subpage_sel,
                    target_attribute, regex_pat
                ): url
                for url in all_subpage_urls
            }
            
            for idx, future in enumerate(as_completed(futures)):
                url = futures[future]
                try:
                    result = future.result()
                    if result and result["emails"]:
                        successful_scrapes += 1
                        self._leads_collected.append(result)
                        
                        # Log every 10th successful scrape
                        if successful_scrapes % 10 == 0:
                            self._log("EXTRACTING", 
                                    f"📈 Progress: {successful_scrapes}/{len(all_subpage_urls)} subpages scraped")
                    else:
                        failed_scrapes += 1
                except Exception as e:
                    failed_scrapes += 1
                    if failed_scrapes % 10 == 0:
                        self._log("EXTRACTING", f"⚠️ {failed_scrapes} subpages failed so far")

        self._log("EXTRACTING",
                f"🎉 Tier 2 complete: ✓ {successful_scrapes} successful | ❌ {failed_scrapes} failed | "
                f"📊 Total leads: {len(self._leads_collected)}")
        

    def _scrape_subpage(self, url: str, subpage_sel: str, 
                   target_attribute: str, regex_pat: str) -> Optional[Dict[str, Any]]:
        """
        Tier 2 worker: fetch one subpage via requests.Session, extract emails
        using the Groq-validated subpage_selector and regex_pattern.
        """
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            emails: Set[str] = set()
            for el in soup.select(subpage_sel):
                value = self._dom_extract(el, target_attribute, regex_pat)
                if value and "@" in value:
                    emails.add(value.lower())

            # Also try fallback email extraction
            emails |= self._emails_from_soup(soup)

            if emails:
                company = self._domain_as_company(url)
                # Only log successful extractions to avoid spam
                print(f"[Tier2] ✓ {url[:50]}: {len(emails)} email(s) from '{company}'")
                return {"company": company, "emails": list(emails), "url": url}
            
            return None
            
        except Exception as e:
            # Only log errors occasionally
            if hash(url) % 10 == 0:  # Log 10% of errors
                print(f"[Tier2] ❌ Failed {url[:50]}: {str(e)[:50]}")
            return None

    # =========================================================================
    # TIER 3  — Company names → Serper → CompanySites
    # =========================================================================

    def _execute_tier_3(self):
        """
        Extract company names, then hand them off to CompanySites agent.
        """
        max_pages   = self.recipe.get("max_pages", DEFAULT_MAX_PAGES)
        primary_sel = self.recipe.get("primary_selector", "")
        method      = self.recipe.get("method", "SELENIUM").upper()
        regex_pat   = self.recipe.get("regex_pattern", r"[\w\s&\-\.,']+")
        pages_done  = 0

        target_attribute = self.recipe.get("target_attribute", "text")

        self._log("EXTRACTING", f"🏢 Tier 3 — Company Name Extraction")
        self._log("EXTRACTING", f"   Selector: '{primary_sel}'")
        self._log("EXTRACTING", f"   Attribute: '{target_attribute}'")
        self._log("EXTRACTING", f"   Regex: '{regex_pat}'")

        while pages_done < max_pages:
            try:
                self._log("EXTRACTING", f"📄 Page {pages_done + 1}/{max_pages}")
                
                try:
                    self._log("EXTRACTING", f"⏳ Waiting for selector: {primary_sel}")
                    self._wait_for_selector(primary_sel)
                    self._log("EXTRACTING", f"✓ Selector found, parsing page")
                except TimeoutException:
                    self._log("EXTRACTING", f"⚠️ Wait selector timed out — proceeding without wait")
                    # You can keep the screenshot line here for debugging purposes without crashing the app:
                    self.driver.save_screenshot(f"timeout_page_{pages_done + 1}.png")

                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                elements = soup.select(primary_sel)
                self._log("EXTRACTING", f"🔍 Found {len(elements)} elements")

                page_companies: Set[str] = set()
                for idx, el in enumerate(elements):
                    name = self._dom_extract(el, target_attribute, regex_pat)
                    if name and len(name) > 2:
                        name_clean = name.strip()
                        page_companies.add(name_clean)
                        self._company_names_set.add(name_clean)
                        
                        # Log every 10th company
                        if idx % 10 == 0 or len(elements) < 20:
                            self._log("EXTRACTING", f"   Added company: '{name_clean[:50]}'")

                self._log("EXTRACTING", 
                        f"✅ Page {pages_done + 1}: {len(page_companies)} companies | "
                        f"📊 Total unique: {len(self._company_names_set)}")

                if self._is_last_page(pages_done):
                    self._log("EXTRACTING", "🏁 Last page reached")
                    break
                
                next_url = self._selenium_next_page()
                if next_url is None:
                    self._log("EXTRACTING", "🏁 No next page found")
                    break
                
                pages_done += 1
                
            except Exception as e:
                self._log("EXTRACTING", f"❌ Error on page {pages_done + 1}: {str(e)}")
                import traceback
                traceback.print_exc()
                break

        total_companies = len(self._company_names_set)
        self._log("EXTRACTING",
                f"🎉 Tier 3 name extraction complete: {total_companies} unique companies")

        if total_companies == 0:
            self._log("EXTRACTING", "❌ No companies found, stopping")
            return

        # Hand off to CompanySites agent
        self._log("EXTRACTING", 
                f"🔍 Starting Serper search for {total_companies} companies...")
        
        industry = self.core.active_tasks.get(self.task_id, {}).get("industry", "General")
        
        try:
            self.core.company_sites_agent.company_sites(
                task_id=self.task_id,
                company_names=list(self._company_names_set),
                industry=industry
            )
            self._log("EXTRACTING", "✅ CompanySites agent completed")
        except Exception as e:
            self._log("EXTRACTING", f"❌ CompanySites agent failed: {str(e)}")
            import traceback
            traceback.print_exc()

    # =========================================================================
    # PAGINATION HELPERS
    # =========================================================================

    def _is_last_page(self, pages_done: int = 0) -> bool:
        """
        Primary check: stop when pages_done >= last_page_number (user-defined limit).
        Fallback DOM check retained for sites that have a last_page_selector and the
        page count limit has not been reached yet.
        """
        limit = int(self.recipe.get("last_page_number",
                                     self.recipe.get("max_pages", DEFAULT_MAX_PAGES)))
        if pages_done >= limit:
            self._log("EXTRACTING", f"Page limit reached ({pages_done}/{limit}), stopping.")
            return True

        sel = self.recipe.get("last_page_selector", "").strip()
        if not sel:
            return False
        try:
            return bool(self.driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            return False

    def _next_url_from_soup(
        self, soup: BeautifulSoup, current_url: str
    ) -> Optional[str]:
        """BS4 path: extract the Next page href."""
        sel = self.recipe.get("pagination_selector", "").strip()
        if not sel:
            return None
        try:
            btn = soup.select_one(sel)
            if btn:
                href = btn.get("href") or ""
                if href and not href.startswith("javascript"):
                    return urljoin(current_url, href)
        except Exception:
            pass
        return None

    def _selenium_next_page(self) -> Optional[str]:
        """
        Navigate to the next page.

        Priority order:
        1. URL_NAVIGATION / BS4 path: read the href from the pagination element
           via BeautifulSoup, resolve it to an absolute URL with urljoin, then
           call driver.get().  Handles relative hrefs like "?page=2" or
           "/directory/page/2" correctly.
        2. SELENIUM JS-click fallback: used only when no valid href is found.

        Returns the new URL, or None when no next page exists.
        """
        sel    = self.recipe.get("pagination_selector", "").strip()
        method = self.recipe.get("method", "SELENIUM").upper()
        if not sel:
            return None

        current_url = self.driver.current_url

        # ── Path 1: href-based navigation (URL_NAVIGATION or BS4) ──────────
        if method in ("URL_NAVIGATION", "BS4"):
            try:
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                btn  = soup.select_one(sel)
                if btn:
                    href = btn.get("href", "").strip()
                    if href and not href.startswith("javascript"):
                        absolute_url = urljoin(current_url, href)
                        self._log("EXTRACTING",
                                  f"Pagination href resolved: '{href}' → '{absolute_url}'")
                        self.driver.get(absolute_url)
                        return self.driver.current_url
                    # href present but empty / javascript — fall through to click
                self._log("EXTRACTING",
                          f"Pagination selector '{sel}' found no usable href; "
                          "falling back to JS click.")
            except Exception as e:
                self._log("EXTRACTING", f"href-resolution error: {e}; falling back to click.")

        # ── Path 2: JS-click fallback ───────────────────────────────────────
        try:
            btn = WebDriverWait(self.driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            # One last attempt to pull href via Selenium before clicking
            href = btn.get_attribute("href") or ""
            if href and not href.startswith("javascript"):
                absolute_url = urljoin(current_url, href)
                self._log("EXTRACTING",
                          f"Pagination href (Selenium attr) resolved: '{href}' → '{absolute_url}'")
                self.driver.get(absolute_url)
                return self.driver.current_url

            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(AJAX_SETTLE)
            return self.driver.current_url

        except (TimeoutException, NoSuchElementException):
            self._log("EXTRACTING", "Pagination: no next button found — end of pages.")
            return None
        except Exception as e:
            self._log("EXTRACTING", f"Pagination error: {e}")
            return None

    # =========================================================================
    # SELENIUM HELPER
    # =========================================================================

    def _safe_find_elements(self, selector: str) -> list:
        """find_elements that returns [] instead of raising on bad selector."""
        try:
            return self.driver.find_elements(By.CSS_SELECTOR, selector)
        except (InvalidSelectorException, Exception):
            return []

    # =========================================================================
    # EMAIL EXTRACTION HELPERS
    # =========================================================================

    def _dom_extract(self, el, target_attribute: str, regex_pattern: str) -> Optional[str]:
        """
        BS4 DOM-first extraction — replaces raw regex-on-HTML.
        Step 1: pull the raw string from the element using target_attribute.
        Step 2: apply regex_pattern to CLEAN the raw string.
        Returns the cleaned value or None if nothing matched.
        """
        # Sanitize regex pattern
        if regex_pattern.startswith('r"') or regex_pattern.startswith("r'"):
            regex_pattern = regex_pattern[2:]
        if regex_pattern.endswith('"') or regex_pattern.endswith("'"):
            regex_pattern = regex_pattern[:-1]
        regex_pattern = regex_pattern.replace('\\"', '"').replace("\\'", "'")
        
        # Step 1 — extract raw string via DOM attribute
        if target_attribute == "text":
            raw = el.get_text(separator=" ", strip=True)
        else:
            raw = el.get(target_attribute, "")
            if raw:
                raw = raw.strip()

        if not raw:
            print(f"[DEBUG] _dom_extract: empty raw value for attribute '{target_attribute}'")
            return None

        # Step 2 — apply regex to clean / validate
        try:
            import re
            match = re.search(regex_pattern, raw)
        except re.error as e:
            print(f"[DEBUG] _dom_extract: regex error '{e}', returning raw: '{raw[:50]}'")
            return raw.strip() or None

        if not match:
            # LOG THE ACTUAL CONTENT THAT DIDN'T MATCH ← ADD THIS
            if self.task_id and len(raw) > 5:  # Only log meaningful content
                print(f"[DEBUG] _dom_extract: no regex match. Raw content: '{raw[:100]}'")
            return None

        clean = match.group(1) if match.groups() else match.group(0)
        return clean.strip() or None

    def _emails_from_soup(self, scope) -> Set[str]:
        """Extract emails from a BeautifulSoup Tag using the default EMAIL_REGEX."""
        return self._emails_from_soup_with_regex(scope, None, EMAIL_REGEX)

    def _emails_from_soup_with_regex(
        self,
        soup_or_scope,
        primary_selector: Optional[str],
        item_regex: re.Pattern,
    ) -> Set[str]:
        """
        Extract emails using the Groq-validated regex.
        If primary_selector is given, narrow the search to matching elements.
        Falls back to full-scope scan if selector matches nothing.
        """
        found: Set[str] = set()

        # Narrow scope to matched elements if selector provided
        scopes = []
        if primary_selector:
            try:
                scopes = soup_or_scope.select(primary_selector)
            except Exception:
                scopes = []

        if not scopes:
            scopes = [soup_or_scope]

        for scope in scopes:
            # Strategy A: mailto links
            for tag in scope.find_all("a", href=True):
                href = tag["href"]
                if "mailto:" in href:
                    email = href.split("mailto:")[-1].split("?")[0].strip().lower()
                    if item_regex.match(email):
                        found.add(email)
            # Strategy B: regex scan on visible text
            text = scope.get_text(separator=" ")
            for match in item_regex.findall(text):
                found.add(match.lower())

        return found

    def _absorb_emails(self, emails: Set[str], source_url: str):
        """Merge emails into _leads_collected, grouping by source URL."""
        if not emails:
            return
        company = self._domain_as_company(source_url)
        for record in self._leads_collected:
            if record["url"] == source_url:
                record["emails"] = list(set(record["emails"]) | emails)
                return
        self._leads_collected.append({
            "company": company,
            "emails":  list(emails),
            "url":     source_url,
        })

    # =========================================================================
    # NETWORK HELPERS
    # =========================================================================

    def _bs4_fetch(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            self._log("EXTRACTING", f"BS4 fetch failed ({url}): {e}")
            return None

    def _wait_for_selector(self, selector: Optional[str]):
        if not selector or not self.driver:
            return
        try:
            WebDriverWait(self.driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        except TimeoutException:
            self._log("EXTRACTING", f"⏱️ TIMEOUT ({WAIT_TIMEOUT}s) waiting for: {selector}")
            raise  # Re-raise INSIDE the except block

    # =========================================================================
    # FINALIZATION
    # =========================================================================

    def _finalize(self, task_id: str):
        """
        Send collected leads to output_server.
        Tier 3 does this itself via CompanySites, so short-circuit if empty.
        """
        if not self._leads_collected:
            return
        industry = self.core.active_tasks.get(task_id, {}).get("industry", "General")
        self._log("EXTRACTING",
                  f"Finalizing: {len(self._leads_collected)} lead records → output_server.")
        self.core.output_server(task_id, self._leads_collected, industry)

    # =========================================================================
    # UTILITY
    # =========================================================================

    def _log(self, status: str, message: str):
        """
        Update task status AND append a timestamped log line.
        Always pass an explicit status string — never None.
        """
        print(f"[ListingsAgent | {self.task_id}] [{status}] {message}")
        if self.task_id:
            # Don't downgrade COMPLETED status back to EXTRACTING
            current_status = self.core.active_tasks.get(self.task_id, {}).get("status", "")
            if current_status == "COMPLETED" and status == "EXTRACTING":
                # Just add the log without changing status
                ts = time.strftime("%H:%M:%S")
                self.core.active_tasks[self.task_id]["logs"].append(f"[{ts}] {message}")
            else:
                self.core.update_task_memory(self.task_id, status, message)

    def _domain_as_company(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc
            name   = netloc.replace("www.", "").replace("m.", "").split(".")[0]
            return name.capitalize()
        except Exception:
            return "Unknown"