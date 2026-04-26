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

        # DEBUG — print everything received by generate_recipe so we can
        # confirm the full HTML arrived from the Dart side intact.
        print("\n" + "═" * 70)
        print(f"[GroqHelper] generate_recipe() CALLED")
        print(f"  tier     : {tier}")
        print(f"  site_url : {site_url}")
        print("─" * 70)
        print(f"  element_html['primary']    ({len(element_html.get('primary',''))} chars):")
        print(element_html.get("primary", "«EMPTY»"))
        print("─" * 70)
        print(f"  element_html['pagination'] ({len(element_html.get('pagination',''))} chars):")
        print(element_html.get("pagination", "«EMPTY»"))
        print("─" * 70)
        print(f"  user_selectors: {user_selectors}")
        print("─" * 70)
        print(f"  page_html_context ({len(page_html_context)} chars):")
        print(page_html_context[:500] if page_html_context else "«EMPTY»")
        print("═" * 70 + "\n")

        try:
            # DEBUG — print the full prompt being sent to Groq.
            # If this shows "mkjsa" then the element_html never arrived correctly.
            # If it shows the real HTML, the problem is in Groq's response parsing.
            print("\n" + "═" * 70)
            print("[GroqHelper] PROMPT SENT TO GROQ:")
            print("─" * 70)
            print(prompt)   # full prompt, no truncation
            print("═" * 70 + "\n")

            resp = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                response_format={"type": "json_object"},
            )
            raw    = resp.choices[0].message.content

            # DEBUG — print the raw string Groq returned before any parsing.
            # If json.loads fails, this is what caused it.
            print("\n" + "═" * 70)
            print("[GroqHelper] RAW GROQ RESPONSE:")
            print("─" * 70)
            print(raw)      # full response, no truncation
            print("═" * 70 + "\n")

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
- primary_selector  : CSS selector matching the ROOT (outermost) element of the
                      PRIMARY ELEMENT HTML block above.  BeautifulSoup will call
                      soup.select(primary_selector) to get a list of all rows, then
                      call get_text(strip=True) on each matched element to get the
                      company name.  DO NOT select a child <a> or <span> — select
                      the container row element so that ALL rows are matched at once.
- regex_pattern     : Python regex to clean / validate extracted name strings.
                      Default: r'[A-Za-z0-9 &.,()\\-]+'
- extract_field     : "text"
- pagination_selector: Valid CSS selector for the Next-page <a> link derived from
                      the PAGINATION ELEMENT HTML above.  Must be syntactically
                      correct — every class name must be preceded by a dot.
- pagination_href   : true if the next-page element has a plain href, false if JS.
- method            : "BS4" if pagination_href is true, otherwise "SELENIUM".
OUTPUT JSON keys: tier, primary_selector, regex_pattern, extract_field,
                  pagination_selector, pagination_href, method""",
        }

        # Pull the root tag and root classes from primary_html so we can tell
        # Groq exactly what selector the root element produces — it must not
        # invent a selector from a child element it finds inside the HTML block.
        import re as _re
        _root_tag   = (_re.match(r'<([a-zA-Z][a-zA-Z0-9]*)', primary_html or '') or [None,''])[1].lower() or 'div'
        _root_cls_m = _re.search(r'class=["\']([^"\']+)["\']', primary_html or '')
        _root_cls   = ' '.join(
            c for c in (_root_cls_m.group(1).split() if _root_cls_m else [])
            if not c.startswith('__leads')
        )
        # Build a concrete selector from the root element so Groq has no ambiguity.
        # e.g.  "div.flex.items-center.gap-4"
        _root_selector = _root_tag + ('.' + '.'.join(_root_cls.split()[:3]) if _root_cls else '')

        html_section = f"""
=== PRIMARY ELEMENT — THE EXACT HTML BLOCK THE USER PROVIDED ===
CRITICAL RULE: Your primary_selector MUST match the OUTERMOST (root) tag of this
HTML block, not any child element inside it.  The root element here is:
  <{_root_tag}> with classes: "{_root_cls}"
  Suggested selector from root: "{_root_selector}"
Use this selector (or a simpler equivalent that matches ALL similar rows on the
page) as primary_selector.  Do NOT select a child <a>, <span>, or <td> inside it.

{primary_html[:1500] if primary_html else "NOT PROVIDED"}

=== PAGINATION ELEMENT — THE EXACT HTML THE USER PROVIDED ===
CRITICAL RULE: Derive pagination_selector from the root tag of this HTML block.
If pagination is a <ul> or <li> container, select the <a> INSIDE the non-active
<li> that has an href — that is the "next page" link.
Ensure the CSS selector is syntactically valid: every class must be preceded by a dot.
Example of INVALID selector: "ul.pagination enf-pagination li a"  ← missing dot
Example of VALID   selector: "ul.pagination.enf-pagination li a"  ← correct

{pagination_html[:800] if pagination_html else "NOT PROVIDED"}
"""
        if subpage_html:
            html_section += f"""
=== SUBPAGE ELEMENT (user clicked this inside a subpage) ===
{subpage_html[:800]}
"""
        if page_html_context:
            html_section += f"""
=== SURROUNDING PAGE CONTEXT (sibling rows — use to generalise the selector) ===
{page_html_context[:1500]}
"""

        # ── HTML evidence section ─────────────────────────────────────────────
        if subpage_html:
            html_section += f"""
=== SUBPAGE ELEMENT (user clicked this inside a subpage) ===
{subpage_html[:800]}
"""
        if page_html_context:
            html_section += f"""
=== SURROUNDING PAGE CONTEXT (sibling rows — use to generalise the selector) ===
{page_html_context[:1500]}
"""

        # Omit the user_selectors block entirely when the primary HTML is available —
        # Groq must derive the selector from the HTML, not from a possibly-wrong string.
        _has_primary_html = bool(element_html.get("primary", "").strip())
        _selector_note = (
            "IMPORTANT: User selectors are NOT provided for this run. "
            "Derive primary_selector and pagination_selector ONLY from the HTML elements below."
            if _has_primary_html
            else f"USER-PROVIDED CSS SELECTORS (fallback only — prefer HTML evidence above):\n"
                 f"{json.dumps(user_selectors, indent=2)}"
        )

        return f"""You are an expert web-scraping engineer helping build a B2B leads extraction system.

A user has clicked elements on the page at:
  URL: {site_url}

They clicked specific elements to indicate what they want to extract and how to paginate.
The exact outerHTML of each clicked element is provided below.
Your job is to produce a validated extraction recipe as a JSON object.

{tier_desc.get(tier, "")}

{_selector_note}

{html_section}

VALIDATION RULES:
1. Return ONLY valid JSON — no markdown, no prose, no code fences.
2. primary_selector MUST be derived from the ROOT TAG of the PRIMARY ELEMENT HTML.
   - The root tag is the first opening tag in that HTML block (e.g. <div>, <li>, <tr>).
   - NEVER select a child element (e.g. inner <a>, <span>, <td>) as primary_selector.
   - The selector must match ALL similar rows on the page, not just the one example.
   - Remove :nth-child qualifiers — they make the selector match only one row.
3. pagination_selector MUST be syntactically valid CSS:
   - Every class name must have a dot prefix: "ul.pagination.enf-pagination li a" not
     "ul.pagination enf-pagination li a" (missing dot = invalid = matches nothing).
   - Target the <a> tag inside the non-active next-page <li> that has an href.
4. For pagination: if the next-page <a> has an href that is not "javascript:…",
   set pagination_href=true and method="BS4".  Otherwise set method="SELENIUM".
5. regex_pattern must be a valid Python regex string with escaped backslashes.
6. All required selector values must be non-empty strings.
   Use "" ONLY for genuinely optional fields (subpage_selector, last_page_selector).
7. Simpler selectors are more robust — prefer tag.class over long :nth-child chains.
"""

        # Omit the user_selectors block entirely when the primary HTML is available —
        # Groq must derive the selector from the HTML, not from a possibly-wrong string.
        _has_primary_html = bool(element_html.get("primary", "").strip())
        _selector_note = (
            "IMPORTANT: User selectors are NOT provided for this run. "
            "Derive primary_selector and pagination_selector ONLY from the HTML elements below."
            if _has_primary_html
            else f"USER-PROVIDED CSS SELECTORS (fallback only — prefer HTML evidence above):\n"
                 f"{json.dumps(user_selectors, indent=2)}"
        )

        return f"""You are an expert web-scraping engineer helping build a B2B leads extraction system.

A user has clicked elements on the page at:
  URL: {site_url}

They clicked specific elements to indicate what they want to extract and how to paginate.
The exact outerHTML of each clicked element is provided below.
Your job is to produce a validated extraction recipe as a JSON object.

{tier_desc.get(tier, "")}

{_selector_note}

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

        # Strip the manual-mode sentinel so it can never propagate into the recipe.
        # If Groq left a field empty and the only fallback is "__manual__", leave
        # the field empty — it is better for extraction to skip than to use garbage.
        def _clean(val: str) -> str:
            return "" if val.strip() == "__manual__" else val.strip()

        fallback_selectors = {
            "primary_selector":    _clean(user_selectors.get("primary_selector",    "")),
            "pagination_selector": _clean(user_selectors.get("pagination_selector", "")),
            "subpage_selector":    _clean(user_selectors.get("subpage_selector",    "")),
            "last_page_selector":  _clean(user_selectors.get("last_page_selector",  "")),
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

        # Fix a common Groq mistake: pagination_selector with a space before a class
        # name instead of a dot (e.g. "ul.pagination enf-pagination li a").
        # Repair by replacing any "word space word" boundary where the second token
        # looks like a bare class name (no dot/# prefix) with "word.word".
        pag_sel = recipe.get("pagination_selector", "")
        if pag_sel:
            import re as _re2
            def _fix_css(sel):
                # Insert a dot before any bare word that follows a space and is
                # preceded by a CSS token (tag or classed element), not a combinator.
                # Combinators are: space (descendant), >, +, ~
                # We only fix the case of "word space bareword" where bareword has
                # no leading . # [ : — i.e. it is a missing-dot class name.
                return _re2.sub(
                    r'(?<=[\w\-])(\s+)(?=[a-zA-Z][a-zA-Z0-9\-]*(?:\s|$|\.|\[|:))',
                    lambda m: m.group(1),  # keep descendant combinator as-is
                    sel
                )
            # Simpler targeted fix: "pagination enf-pagination" → "pagination.enf-pagination"
            # Pattern: two adjacent CSS class-like words separated only by a space
            pag_sel_fixed = _re2.sub(
                r'(?<=[a-zA-Z0-9\-])( )(?=[a-zA-Z][a-zA-Z0-9\-]+(?:\s+[a-zA-Z]|\s*$))',
                '.',
                pag_sel,
            )
            if pag_sel_fixed != pag_sel:
                print(f"[GroqHelper] Auto-fixed pagination_selector: '{pag_sel}' → '{pag_sel_fixed}'")
            recipe["pagination_selector"] = pag_sel_fixed

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
            # Strip the manual sentinel defensively — primary_selector must always
            # be a real CSS selector string that BeautifulSoup/Selenium can use.
            "primary_selector":   "" if user_selectors.get("primary_selector", "").strip() == "__manual__"
                                     else user_selectors.get("primary_selector", ""),
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