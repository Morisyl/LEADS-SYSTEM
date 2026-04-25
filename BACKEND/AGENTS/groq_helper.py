import os
import json
import re
from groq import Groq


class GroqRecipeParser:
    """
    Sends the actual outerHTML of user-clicked elements + site URL to Groq.
    Groq validates the selectors against the real HTML and returns a complete
    extraction recipe including:
      - Validated / corrected CSS selectors
      - The regex pattern extraction engine should use
      - What field to extract (text, href, email, etc.)
      - Pagination method (BS4 href or SELENIUM click)

    This replaces the old approach of sending raw page_source[:3000] which
    was mostly navigation boilerplate and never included the actual elements.
    """

    def __init__(self):
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model  = "llama-3.3-70b-versatile"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def generate_recipe(
        self,
        tier: int,
        site_url: str,
        element_html: dict,        # keys: primary, pagination, subpage, last_page
        user_selectors: dict,      # keys: primary_selector, pagination_selector, …
        page_html_context: str = "", # surrounding HTML around primary element (optional)
    ) -> dict:
        """
        Build a validated extraction recipe.

        element_html values are the raw outerHTML strings captured by
        VisualTrainerPage — this is what the user actually clicked on,
        giving Groq concrete HTML to reason about instead of a bare selector.
        """
        tier = int(tier)
        prompt = self._build_prompt(
            tier, site_url, element_html, user_selectors, page_html_context
        )

        try:
            resp = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                response_format={"type": "json_object"},
            )
            raw    = resp.choices[0].message.content
            recipe = json.loads(raw)
            print(f"[Groq] Raw recipe for Tier {tier}:\n{json.dumps(recipe, indent=2)}")
            return self._validate_and_fill(tier, recipe, user_selectors)

        except Exception as e:
            print(f"[Groq] Error: {e}. Falling back to user selectors.")
            return self._fallback_recipe(tier, user_selectors, element_html)

    # ─────────────────────────────────────────────────────────────────────────
    # Prompt builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        tier: int,
        site_url: str,
        element_html: dict,
        user_selectors: dict,
        page_html_context: str,
    ) -> str:

        primary_html    = element_html.get("primary",    "").strip()
        pagination_html = element_html.get("pagination", "").strip()
        subpage_html    = element_html.get("subpage",    "").strip()

        # ── Per-tier task description ────────────────────────────────────────
        tier_desc = {
            1: """TIER 1 — Emails are directly visible on the main listing page.
GOAL: Extract email addresses from each listing row/card.
- primary_selector  : CSS selector for the CONTAINER element of one listing row/card
                      (the element the user clicked). BeautifulSoup will .select() this
                      to get a list of items, then scan each for emails.
- regex_pattern     : Python regex to extract email addresses from the container's text.
                      Default: r'[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}'
- extract_field     : "email"
- pagination_selector: CSS selector for the Next-page <a> tag or JS button.
- pagination_href   : true if Next is a plain <a href=...>, false if JS button.
- method            : "BS4" if pagination is a plain href, "SELENIUM" if JS-driven.
- last_page_selector: CSS selector for the disabled / hidden Next indicator (or "").
OUTPUT JSON keys: tier, primary_selector, regex_pattern, extract_field,
                  pagination_selector, pagination_href, method, last_page_selector""",

            2: """TIER 2 — Emails are inside per-company subpages linked from the listing.
GOAL: From the MAIN PAGE collect all subpage links → visit each subpage → extract emails.
- primary_selector  : CSS selector for the <a> link element on the MAIN page that
                      leads to the company subpage. Must resolve to elements with href.
- regex_pattern     : Python regex to extract email addresses from the subpage HTML.
                      Default: r'[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}'
- extract_field     : "email"
- subpage_selector  : CSS selector to narrow the search area INSIDE the subpage
                      (e.g. '.contact-section', 'div.company-details').
                      Use "" to scan the full subpage.
- pagination_selector: CSS selector for the Next-page element on the MAIN page.
- pagination_href   : true if Next is a plain href, false if JS button.
- method            : "BS4" or "SELENIUM".
OUTPUT JSON keys: tier, primary_selector, regex_pattern, extract_field,
                  subpage_selector, pagination_selector, pagination_href, method""",

            3: """TIER 3 — Only company names are visible; no emails on the site.
GOAL: Extract company NAME TEXT from each listing row → pass to Serper search engine
      → find company websites → scrape emails from those websites.
- primary_selector  : CSS selector for the element whose visible TEXT is the company name.
- regex_pattern     : Python regex to clean / validate extracted company name strings.
                      Default: r'[A-Za-z0-9 &.,()\\-]+'
- extract_field     : "text" (get_text(strip=True) on the matched element)
- pagination_selector: CSS selector for the Next-page element.
- pagination_href   : true if plain href, false if JS button.
- method            : "BS4" or "SELENIUM".
OUTPUT JSON keys: tier, primary_selector, regex_pattern, extract_field,
                  pagination_selector, pagination_href, method""",
        }

        # ── HTML evidence section ─────────────────────────────────────────────
        html_section = f"""
=== PRIMARY ELEMENT (user clicked this — what you must target) ===
{primary_html[:1500] if primary_html else "NOT PROVIDED"}

=== PAGINATION ELEMENT (user clicked this — how to get to next page) ===
{pagination_html[:800] if pagination_html else "NOT PROVIDED"}
"""
        if subpage_html:
            html_section += f"""
=== SUBPAGE ELEMENT (user clicked this inside a subpage) ===
{subpage_html[:800]}
"""
        if page_html_context:
            html_section += f"""
=== SURROUNDING PAGE CONTEXT (siblings of the primary element) ===
{page_html_context[:1500]}
"""

        return f"""You are an expert web-scraping engineer helping build a B2B leads extraction system.

A user has clicked elements on the page at:
  URL: {site_url}

They clicked specific elements to indicate what they want to extract and how to paginate.
The exact outerHTML of each clicked element is provided below.
Your job is to produce a validated extraction recipe as a JSON object.

{tier_desc.get(tier, "")}

USER-PROVIDED CSS SELECTORS (auto-generated from click position — verify against the HTML):
{json.dumps(user_selectors, indent=2)}

{html_section}

VALIDATION RULES:
1. Return ONLY valid JSON — no markdown, no prose, no code fences.
2. Study the PRIMARY ELEMENT HTML carefully:
   - Check its tag, class names, href, and text content.
   - If the auto-generated CSS selector looks wrong (e.g. too specific with :nth-child,
     or missing a key class), produce a SIMPLER, MORE ROBUST selector from the HTML.
   - For Tier 1: the selector should match ALL rows/cards, not just one.
   - For Tier 3: the selector must match elements whose text() IS the company name.
3. For the pagination element: check if it has an href attribute.
   - If href present and not "javascript:…" → set pagination_href=true, method="BS4".
   - If no href or href="javascript:…" → set pagination_href=false, method="SELENIUM".
4. regex_pattern must be a valid Python regex string (escape backslashes).
5. All selector values must be non-empty strings.
   Use "" ONLY for optional fields (subpage_selector, last_page_selector) that genuinely
   do not apply.
6. Simpler selectors are more robust — prefer tag.class over long :nth-child chains.
"""

    # ─────────────────────────────────────────────────────────────────────────
    # Post-processing helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_and_fill(self, tier: int, recipe: dict, user_selectors: dict) -> dict:
        """
        Ensure required keys exist and fall back gracefully to user-provided
        values when Groq returns empty / missing fields.
        """
        recipe["tier"] = tier

        required_by_tier = {
            1: ["primary_selector", "pagination_selector", "method",
                "regex_pattern", "extract_field"],
            2: ["primary_selector", "pagination_selector", "subpage_selector",
                "method", "regex_pattern", "extract_field"],
            3: ["primary_selector", "pagination_selector", "method",
                "regex_pattern", "extract_field"],
        }

        fallback_selectors = {
            "primary_selector":    user_selectors.get("primary_selector",    ""),
            "pagination_selector": user_selectors.get("pagination_selector", ""),
            "subpage_selector":    user_selectors.get("subpage_selector",    ""),
            "last_page_selector":  user_selectors.get("last_page_selector",  ""),
        }

        for key in required_by_tier.get(tier, []):
            if not recipe.get(key, ""):
                recipe[key] = fallback_selectors.get(key, "")

        # Defaults for fields Groq may omit
        if not recipe.get("regex_pattern"):
            recipe["regex_pattern"] = (
                r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
                if tier in (1, 2)
                else r"[A-Za-z0-9 &.,()\-]+"
            )
        if not recipe.get("extract_field"):
            recipe["extract_field"] = "email" if tier in (1, 2) else "text"

        # Normalise method
        method = recipe.get("method", "SELENIUM").upper().strip()
        recipe["method"] = method if method in ("BS4", "SELENIUM") else "SELENIUM"

        # Ensure optional keys exist
        recipe.setdefault("last_page_selector", "")
        recipe.setdefault("pagination_href",
                          recipe["method"] == "BS4")

        if tier == 2:
            recipe.setdefault("subpage_selector", "")
        if tier == 1:
            recipe.setdefault("last_page_selector",
                              user_selectors.get("last_page_selector", ""))

        return recipe

    def _fallback_recipe(self, tier: int, user_selectors: dict, element_html: dict) -> dict:
        """
        When Groq fails entirely, derive the best recipe we can from what the
        user clicked — including a safe default regex for the tier.
        """
        primary_html = element_html.get("primary", "")

        # Try to detect pagination type from the pagination element HTML
        pag_html = element_html.get("pagination", "")
        is_href  = bool(re.search(r'href=["\'](?!javascript)', pag_html))

        base = {
            "tier":               tier,
            "primary_selector":   user_selectors.get("primary_selector",    ""),
            "pagination_selector":user_selectors.get("pagination_selector", ""),
            "method":             "BS4" if is_href else "SELENIUM",
            "pagination_href":    is_href,
            "regex_pattern": (
                r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
                if tier in (1, 2)
                else r"[A-Za-z0-9 &.,()\-]+"
            ),
            "extract_field":      "email" if tier in (1, 2) else "text",
            "last_page_selector": user_selectors.get("last_page_selector", ""),
        }

        if tier == 2:
            base["subpage_selector"] = user_selectors.get("subpage_selector", "")

        return base