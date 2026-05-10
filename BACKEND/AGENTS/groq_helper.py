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

        tier_desc = {
            1: """TIER 1 — Emails are directly visible on the main listing page.
GOAL: Extract email addresses from each listing row/card using DOM parsing.
- primary_selector : CSS selector for the CONTAINER element of one row/card.
                     BS4 calls soup.select(primary_selector) → iterates each element.
- target_attribute : EXACTLY one of "text", "href", or "content".
                     Use "href" if the email is inside a mailto: link attribute.
                     Use "text" if the email appears as visible text in the element.
- regex_pattern    : Python regex applied to the raw extracted string to CLEAN it.
                     For mailto hrefs: r"mailto:(.*)" — capture group 1 gives the address.
                     For visible text: r"[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}"
- pagination_selector: CSS selector for the Next-page <a> tag or JS button.
- pagination_href  : true if Next is a plain <a href=...>, false if JS button.
- method           : "BS4" if pagination is a plain href, "SELENIUM" if JS-driven.
- last_page_selector: CSS selector for the disabled Next indicator (or "").
OUTPUT JSON keys: tier, primary_selector, target_attribute, regex_pattern,
                  pagination_selector, pagination_href, method, last_page_selector""",

            2: """TIER 2 — Emails are inside per-company subpages linked from the listing.
GOAL: From the MAIN PAGE collect all subpage links → visit each → extract emails.
- primary_selector : CSS selector for the <a> link element on the MAIN page that
                     leads to the company subpage.
- target_attribute : For collecting subpage links this is always "href".
                     On the subpage itself, use "href" for mailto links or "text"
                     for visible email addresses.
- regex_pattern    : Python regex to clean the extracted string.
                     For mailto hrefs: r"mailto:(.*)"
                     For visible text: r"[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}"
- subpage_selector : CSS selector to narrow search area INSIDE the subpage (or "").
- pagination_selector: CSS selector for the Next-page element on the MAIN page.
- pagination_href  : true if Next is a plain href, false if JS button.
- method           : "BS4" or "SELENIUM".
OUTPUT JSON keys: tier, primary_selector, target_attribute, regex_pattern,
                  subpage_selector, pagination_selector, pagination_href, method""",

            3: """TIER 3 — Only company names are visible; no emails on the site.
GOAL: Extract company NAME TEXT from each row → Serper search → email scraping.
- primary_selector : CSS selector matching the ROOT (outermost) element of the
                     PRIMARY ELEMENT HTML block. soup.select(primary_selector)
                     returns ALL rows. DO NOT select a child <a> or <span>.
- target_attribute : Always "text" for Tier 3 — we call get_text() on each element.
- regex_pattern    : Python regex to clean the extracted name string.
                     Default: r"[A-Za-z0-9 &.,()\\-]+"
                     Use r".+" if the text is already clean (just validates non-empty).
- pagination_selector: Valid CSS selector for the Next-page <a> link.
                     Every class must be preceded by a dot.
- pagination_href  : true if the next-page element has a plain href, false if JS.
- method           : "BS4" if pagination_href is true, otherwise "SELENIUM".
OUTPUT JSON keys: tier, primary_selector, target_attribute, regex_pattern,
                  pagination_selector, pagination_href, method""",
        }

        import re as _re
        _root_tag   = (_re.match(r'<([a-zA-Z][a-zA-Z0-9]*)', primary_html or '') or [None,''])[1].lower() or 'div'
        _root_cls_m = _re.search(r'class=["\']([^"\']+)["\']', primary_html or '')
        _root_cls   = ' '.join(
            c for c in (_root_cls_m.group(1).split() if _root_cls_m else [])
            if not c.startswith('__leads')
        )
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
2. primary_selector MUST match the ROOT TAG of the PRIMARY ELEMENT HTML.
   - NEVER select a child element as primary_selector.
   - Remove :nth-child qualifiers so the selector matches ALL rows, not just one.
3. target_attribute MUST be exactly one of: "text", "href", or "content".
   - "text"    → extraction calls el.get_text(separator=" ", strip=True)
   - "href"    → extraction calls el.get("href", "").strip()
   - "content" → extraction calls el.get("content", "").strip()
   Choose based on WHERE the data lives in the element HTML provided.
4. regex_pattern is applied AFTER extraction to CLEAN the raw string.
   - If target_attribute is "href" and it's a mailto link, use r"mailto:(.*)"
     so the capture group strips the "mailto:" prefix automatically.
   - If the text is already clean, use r".+" (matches any non-empty string).
   - Always escape backslashes: \\d not \d.
5. pagination_selector MUST be syntactically valid CSS (every class preceded by a dot).
6. For pagination: plain href → pagination_href=true, method="BS4".
                   JS button  → pagination_href=false, method="SELENIUM".
7. All required keys must be non-empty strings. Use "" only for optional fields.
8. Simpler selectors are more robust — prefer tag.class over :nth-child chains.
CRITICAL: Return regex_pattern as a RAW regex string WITHOUT Python notation.
WRONG: "regex_pattern": "r\"[A-Za-z]+\""
CORRECT: "regex_pattern": "[A-Za-z]+"

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
            1: ["primary_selector", "target_attribute", "pagination_selector",
                "method", "regex_pattern"],
            2: ["primary_selector", "target_attribute", "pagination_selector",
                "subpage_selector", "method", "regex_pattern"],
            3: ["primary_selector", "target_attribute", "pagination_selector",
                "method", "regex_pattern"],
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

        # Default target_attribute when Groq omits it.
        # Tier 1/2 email extraction defaults to "text" (visible address) unless
        # the primary HTML shows a mailto href, in which case Groq should have
        # set "href" — we leave that to Groq and only provide a safe fallback.
        if not recipe.get("target_attribute"):
            recipe["target_attribute"] = "text"

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
        # Detect pagination type from the pagination_selector string itself
        # (not from the HTML) — simpler and avoids needing the raw element HTML here.
        pag = user_selectors.get("pagination_selector", "")
        is_href = bool(pag) and ("a" in pag.lower() or "href" in pag.lower())

        base = {
            "tier":               tier,
            # Strip the manual sentinel defensively.
            "primary_selector":   "" if user_selectors.get("primary_selector", "").strip() == "__manual__"
                                     else user_selectors.get("primary_selector", ""),
            "pagination_selector":user_selectors.get("pagination_selector", ""),
            "method":             "BS4" if is_href else "SELENIUM",
            "pagination_href":    is_href,
            "target_attribute":   "text",
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
        # Run through _validate_and_fill so all normalisation (method, pag_sel fix, etc.)
        # is applied consistently even in the fallback path.
        return self._validate_and_fill(tier, base, user_selectors)
