import os
import uuid
import shutil
import time
import threading
import magic
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Depends, Header, Query, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Internal Imports
from DATA.DBmanager import DBManager
from AGENTS.doc_tool import DocTool
from AGENTS.txt_extractor import TxtExtractor
from AGENTS.search_engine import SearchEngine
from AGENTS.company_sites import CompanySites
from AGENTS.listings_site import ListingsSiteAgent
from AGENTS.output_server import OutputServer
from AGENTS.schemas import Recipe


# ============================================================
# UTILITY
# ============================================================

def is_url(text: str) -> bool:
    """Checks if the user input is a web address or a text prompt."""
    pattern = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(pattern, text) is not None


# ============================================================
# APP & SECURITY
# ============================================================

app = FastAPI(title="Enolix B2B Leads Orchestrator V3")

# Allow Flutter (running on localhost / emulator) to reach the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INTERNAL_TOKEN = os.getenv("ENOLIX_INTERNAL_KEY", "jkuat_secret_2026")
UPLOAD_DIR = Path("uploads")
EXPORT_DIR = Path("exports")

for folder in [UPLOAD_DIR, EXPORT_DIR]:
    folder.mkdir(exist_ok=True)


def verify_token(x_api_key: str = Header(...)):
    """Ensures only the Flutter UI can access protected endpoints."""
    if x_api_key != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")


# ============================================================
# ORCHESTRATOR
# ============================================================

class Orchestrator:
    def __init__(self):
        self.db = DBManager()
        self.doc_tool = DocTool()
        self.extractor = TxtExtractor()
        self.search_engine = SearchEngine()
        self.output_agent = OutputServer()

        # Agents receive 'self' so they can call back into the orchestrator
        self.company_sites_agent = CompanySites(self)
        self.listings_agent = ListingsSiteAgent(self)

        # In-memory task store.
        # Schema per entry:
        #   status        : str   — INITIALIZING | AWAITING_TRAINING | TRAINED |
        #                           QUEUED | EXTRACTING | COMPLETED | FAILED
        #   lead_count    : int
        #   company_count : int
        #   logs          : List[str]
        #   target_url    : str | None
        #   industry      : str
        self.active_tasks: Dict[str, Dict[str, Any]] = {}

    # ----------------------------------------------------------
    # Task memory helpers
    # ----------------------------------------------------------

    def _ensure_task(self, task_id: str, industry: str = "General"):
        """Creates the in-memory entry for a task if it does not exist yet."""
        if task_id not in self.active_tasks:
            self.active_tasks[task_id] = {
                "status": "INITIALIZING",
                "lead_count": 0,
                "company_count": 0,
                "logs": [],
                "target_url": None,
                "industry": industry,
            }

    def update_task_memory(self, task_id: str, status: str, log: str = None):
        """
        Updates status and appends an optional timestamped log line.
        Safe to call from background threads.
        """
        self._ensure_task(task_id)
        self.active_tasks[task_id]["status"] = status
        if log:
            ts = time.strftime("%H:%M:%S")
            self.active_tasks[task_id]["logs"].append(f"[{ts}] {log}")

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the live in-memory record first.
        Falls back to the DB so that completed / historical tasks
        are still accessible after a server restart.
        """
        if task_id in self.active_tasks:
            return self.active_tasks[task_id]

        db_data = self.db.get_task_status(task_id)
        if db_data:
            return {
                "status": db_data["status"].upper(),
                "lead_count": db_data["lead_count"],
                "company_count": 0,
                "logs": ["Task loaded from archive."],
                "target_url": None,
                "industry": db_data.get("industry", "General"),
            }
        return None

    # ----------------------------------------------------------
    # Centralized data handoff  (called by all agents)
    # ----------------------------------------------------------

    def output_server(self, task_id: str, structured_leads: List[Dict[str, Any]], industry: str):
        """
        Final landing zone for every agent.
        structured_leads format:
            [{'company': 'Acme', 'emails': ['a@acme.com'], 'url': 'https://acme.com'}, ...]
        """
        self.db.save_leads_batch(task_id, structured_leads, industry)

        # Refresh the live count so the Flutter polling loop sees it immediately
        task_db = self.db.get_task_status(task_id)
        if task_db and task_id in self.active_tasks:
            self.active_tasks[task_id]["lead_count"] = task_db["lead_count"]

        self.db.update_task_status(task_id, "completed")
        self.update_task_memory(task_id, "COMPLETED",
                                f"Pipeline finished. {len(structured_leads)} lead records saved.")

    # ----------------------------------------------------------
    # Background pipeline: document upload
    # ----------------------------------------------------------

    def run_doc_pipeline(self, task_id: str, file_path: str, industry: str):
        """OCR → Groq extraction → Serper discovery → scraping."""
        try:
            self.update_task_memory(task_id, "EXTRACTING", "Step 1/4: OCR processing document.")
            doc_dict = self.doc_tool.file_to_text_dict(file_path)

            self.update_task_memory(task_id, "EXTRACTING", "Step 2/4: Groq extracting companies & emails.")
            leads = self.extractor.extract_leads_structured(doc_dict)
            self.active_tasks[task_id]["company_count"] = len(leads)

            self.update_task_memory(task_id, "EXTRACTING", "Step 3/4: Serper discovering contact pages.")
            for lead in leads:
                if lead.get("company", "Unknown") != "Unknown":
                    urls = self.search_engine.company_names({lead["company"]})
                    if urls:
                        lead["url"] = list(urls)[0]

            self.update_task_memory(task_id, "EXTRACTING", "Step 4/4: Scraping contact pages.")
            self.company_sites_agent.company_sites(task_id, leads, industry)

        except Exception as e:
            self.db.update_task_status(task_id, "failed")
            self.update_task_memory(task_id, "FAILED", f"Pipeline error: {e}")

    # ----------------------------------------------------------
    # Background pipeline: text / prompt search
    # ----------------------------------------------------------

    def run_listing_pipeline(self, task_id: str, prompt: str, industry: str):
        """High-volume Serper search → listings agent scraping."""
        try:
            self.update_task_memory(task_id, "EXTRACTING", "Searching for listing pages via Serper.")
            listing_urls = self.search_engine.search_prompt(prompt)

            if not listing_urls:
                self.db.update_task_status(task_id, "completed", lead_count=0)
                self.update_task_memory(task_id, "COMPLETED", "Search returned no URLs.")
                return

            self.update_task_memory(task_id, "EXTRACTING",
                                    f"Found {len(listing_urls)} URLs. Starting scrape.")

            for url in listing_urls:
                self.listings_agent.listings_site(task_id, url, industry)

            self.db.update_task_status(task_id, "completed")
            self.update_task_memory(task_id, "COMPLETED", "Listing pipeline finished.")

        except Exception as e:
            self.db.update_task_status(task_id, "failed")
            self.update_task_memory(task_id, "FAILED", f"Listing pipeline error: {e}")

    # ----------------------------------------------------------
    # Background pipeline: URL training mode  (Selenium)
    # ----------------------------------------------------------

    def run_trained_extraction(self, task_id: str, url: str, recipe: dict, industry: str):
        """
        Runs AFTER the Flutter UI has saved a recipe.
        Called in a background thread so the endpoint returns immediately.
        """
        try:
            self.update_task_memory(task_id, "EXTRACTING",
                                    f"Tier {recipe.get('tier', 1)} engine starting.")
            self.listings_agent.start_system_sync(task_id, url, json.dumps(recipe))
        except Exception as e:
            self.db.update_task_status(task_id, "failed")
            self.update_task_memory(task_id, "FAILED", f"Extraction error: {e}")


# Single shared instance
core = Orchestrator()


# ============================================================
# BACKGROUND CLEANUP THREAD
# ============================================================

def _cleanup_worker():
    """Deletes uploaded files and exports older than 2 hours."""
    while True:
        cutoff = time.time() - 7200
        for folder in [UPLOAD_DIR, EXPORT_DIR]:
            for f in folder.iterdir():
                try:
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass
        time.sleep(3600)

threading.Thread(target=_cleanup_worker, daemon=True).start()


# ============================================================
# API ENDPOINTS
# ============================================================

# ----------------------------------------------------------
# 1.  Task status  (polled by ExecutionPage every 2 s)
# ----------------------------------------------------------

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    Returns live task state.
    ExecutionPage polls this endpoint to know when to show the Training
    Wizard, the START button, or the completed state.
    """
    task_data = core.get_task_info(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found in memory or DB.")
    return task_data


# ----------------------------------------------------------
# 2.  Task status PATCH  (called by VisualTrainerPage after saving recipe)
# ----------------------------------------------------------

@app.patch("/tasks/{task_id}/status", dependencies=[Depends(verify_token)])
async def patch_task_status(task_id: str, body: dict = Body(...)):
    """
    Allows VisualTrainerPage to signal that training is complete.
    Expected body: {"status": "TRAINED"}
    
    Flow:
        VisualTrainerPage saves recipe  →  POST /recipes
        VisualTrainerPage calls this    →  PATCH /tasks/{id}/status  {"status":"TRAINED"}
        ExecutionPage next poll sees TRAINED  →  START button activates
    """
    new_status = body.get("status", "").upper()
    allowed = {"TRAINED", "AWAITING_TRAINING", "FAILED"}
    if new_status not in allowed:
        raise HTTPException(status_code=400,
                            detail=f"Invalid status. Allowed values: {allowed}")

    core.update_task_memory(task_id, new_status,
                            f"Status set to {new_status} by client.")
    return {"ok": True, "status": new_status}


# ----------------------------------------------------------
# 3.  Manual START  (called by ExecutionPage START button)
# ----------------------------------------------------------

@app.post("/tasks/{task_id}/start", dependencies=[Depends(verify_token)])
def start_extraction(
    task_id: str,
    background_tasks: BackgroundTasks,
    recipe: dict = Body(...),
):
    """
    Triggered when the user presses START EXTRACTION after training.

    Expects the full recipe body that VisualTrainerPage collected:
    {
        "tier": 1,
        "primary_selector": "...",
        "pagination_selector": "...",
        "method": "BS4" | "SELENIUM"
    }

    Uses BackgroundTasks (thread-pool) so blocking Selenium calls
    never stall the event loop.
    """
    task_memory = core.active_tasks.get(task_id)
    if not task_memory:
        raise HTTPException(status_code=404, detail="Task not found in active memory.")

    url = task_memory.get("target_url")
    if not url:
        raise HTTPException(status_code=400,
                            detail="No target URL stored for this task. "
                                   "Was it created with a URL input?")

    industry = task_memory.get("industry", "General")

    core.update_task_memory(task_id, "EXTRACTING", "START command received. Launching engine.")

    # BackgroundTasks runs in a thread — safe for synchronous/blocking Selenium code
    background_tasks.add_task(
        core.run_trained_extraction, task_id, url, recipe, industry
    )

    return {"status": "STARTING"}


# ----------------------------------------------------------
# 4.  Live frame  (polled by ExecutionPage every 500 ms)
# ----------------------------------------------------------

@app.get("/tasks/{task_id}/frame")
async def get_task_frame(task_id: str):
    """
    Returns the latest base64 screenshot from the Selenium instance.
    Returns null when Selenium is not running for this task — the
    Flutter side should show a spinner in that case (which it already does).
    """
    agent = core.listings_agent
    if agent.driver is not None and agent.task_id == task_id:
        try:
            return {"frame": agent.get_live_frame()}
        except Exception:
            pass
    return {"frame": None}


# ----------------------------------------------------------
# 5.  Document upload
# ----------------------------------------------------------

@app.post("/upload", dependencies=[Depends(verify_token)])
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    industry: str = Query("General"),
):
    """Accepts a PDF / image, validates MIME type, and kicks off the doc pipeline."""
    task_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{task_id}_{file.filename}"

    with open(save_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    mime = magic.Magic(mime=True)
    detected = mime.from_file(str(save_path))
    if detected not in {"application/pdf", "image/jpeg", "image/png"}:
        os.remove(save_path)
        raise HTTPException(status_code=400,
                            detail=f"Unsupported file type: {detected}")

    core.db.create_task(task_id, industry)
    core._ensure_task(task_id, industry)
    core.update_task_memory(task_id, "EXTRACTING", "Document accepted. Pipeline starting.")

    background_tasks.add_task(core.run_doc_pipeline, task_id, str(save_path), industry)
    return {"task_id": task_id, "status": "Pipeline initialised."}


# ----------------------------------------------------------
# 6.  Search / URL input  (main entry point from HomePage)
# ----------------------------------------------------------

@app.get("/search-listings", dependencies=[Depends(verify_token)])
def start_search(
    background_tasks: BackgroundTasks,
    prompt: str = Query(...),
    industry: str = Query("General"),
):
    """
    Two behaviours depending on whether the input is a URL or a text prompt:

    URL  →  status = AWAITING_TRAINING
            The target URL is stored in memory.
            No Selenium is started yet — that happens only after the
            recipe is saved and the user presses START.
            ExecutionPage will detect AWAITING_TRAINING and navigate to
            VisualTrainerPage.

    Text →  status = QUEUED
            Serper + listings pipeline runs in the background immediately.
    """
    task_id = str(uuid.uuid4())
    core.db.create_task(task_id, industry)
    core._ensure_task(task_id, industry)
    core.active_tasks[task_id]["industry"] = industry

    if is_url(prompt):
        core.active_tasks[task_id]["target_url"] = prompt
        core.update_task_memory(
            task_id, "AWAITING_TRAINING",
            f"URL detected: {prompt}. Waiting for recipe from UI."
        )
        # Do NOT start Selenium here — that blocked the response and
        # caused the indefinite loading spinner described in the bug report.
    else:
        core.update_task_memory(task_id, "QUEUED", "Text prompt queued for Serper search.")
        background_tasks.add_task(core.run_listing_pipeline, task_id, prompt, industry)

    return {"task_id": task_id}


# ----------------------------------------------------------
# 7.  Recipe management  (called by VisualTrainerPage._saveRecipe)
# ----------------------------------------------------------

@app.post("/recipes", dependencies=[Depends(verify_token)])
def create_recipe(recipe: Recipe):
    """
    Persists the CSS selectors that VisualTrainerPage collected.
    VisualTrainerPage should call this THEN PATCH /tasks/{id}/status.
    """
    core.db.persist_recipe(
        recipe.domain,
        recipe.pagination_type,
        recipe.selectors,
        recipe.max_pages,
    )
    return {"status": "saved", "domain": recipe.domain}


@app.get("/recipes/{domain}", dependencies=[Depends(verify_token)])
def get_recipe(domain: str):
    """Returns the stored recipe for a domain, or 404 if none exists."""
    recipe = core.db.query_recipe(domain)
    if not recipe:
        raise HTTPException(status_code=404,
                            detail=f"No recipe found for domain: {domain}")
    return recipe


# ----------------------------------------------------------
# 8.  Job status  (used by PastTasksPage / history view)
# ----------------------------------------------------------

@app.get("/jobs/{task_id}/status", dependencies=[Depends(verify_token)])
def get_job_status(task_id: str):
    """
    DB-backed status for the history view.
    Includes industry and timestamps which the live /tasks endpoint omits.
    """
    status_data = core.db.get_task_status(task_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    return status_data


# ----------------------------------------------------------
# 9.  File download
# ----------------------------------------------------------

@app.get("/savefile", dependencies=[Depends(verify_token)])
def download_results(
    task_id: str = Query(...),
    format: str = Query(..., pattern="^(csv|pdf)$"),
):
    """Generates and streams the leads export for a completed task."""
    leads = core.db.get_leads_for_task(task_id)
    if not leads:
        raise HTTPException(
            status_code=400,
            detail="No leads found for this task, or the task is still processing."
        )

    file_path = core.output_agent.generate_file(leads, format)
    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="application/octet-stream",
    )


# ----------------------------------------------------------
# 10.  Shutdown hook
# ----------------------------------------------------------

@app.on_event("shutdown")
def shutdown_event():
    """Cleanly quits the Selenium driver on server stop."""
    if core.listings_agent.driver:
        try:
            core.listings_agent.driver.quit()
        except Exception:
            pass


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)