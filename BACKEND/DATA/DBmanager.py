import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

class DBManager:
    def __init__(self, db_name="enolix_leads_v3.db"):
        # Ensure the database stays in the DATA folder
        self.db_path = os.path.join(os.path.dirname(__file__), db_name)
        self._init_db()

    def _get_connection(self):
        """Returns a thread-safe connection with row factory for dict-like access."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes the schema with Job Tracking, Recipes, and Leads."""
        with self._get_connection() as conn:
            # 1. Tasks/Jobs Table (Replaces global session_results)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'pending', -- pending, running, completed, failed
                    industry TEXT,
                    lead_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')

            # 2. Recipes Table (For the Listing Sites Agent)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS recipes (
                    domain TEXT PRIMARY KEY,
                    pagination_type TEXT, -- html, java_button
                    selectors_json TEXT,  -- CSS selectors map
                    max_pages INTEGER DEFAULT 5
                )
            ''')

            # 3. Leads Library (Maintains the Company -> Email -> URL link)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS leads_library (
                    email TEXT PRIMARY KEY,
                    company_name TEXT,
                    industry TEXT,
                    source_url TEXT,
                    task_id TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                )
            ''')
            conn.commit()

    # --- Task / Job Management ---

    def create_task(self, task_id: str, industry: str):
        """Initializes a new background job."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, status, industry, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, 'running', industry, now, now)
            )
            conn.commit()

    def update_task_status(self, task_id: str, status: str, lead_count: int = None):
        """Updates the status and lead count for the /status endpoint."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            if lead_count is not None:
                conn.execute(
                    "UPDATE tasks SET status = ?, lead_count = ?, updated_at = ? WHERE task_id = ?",
                    (status, lead_count, now, task_id)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                    (status, now, task_id)
                )
            conn.commit()

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Returns the current state of a job for polling."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    # --- Recipe Management (Training Mode) ---

    def persist_recipe(self, domain: str, p_type: str, selectors: Dict, max_p: int = 5):
        """Saves or updates site-specific selectors."""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO recipes (domain, pagination_type, selectors_json, max_pages)
                VALUES (?, ?, ?, ?)
            ''', (domain, p_type, json.dumps(selectors), max_p))
            conn.commit()

    def query_recipe(self, domain: str) -> Optional[Dict]:
        """Retrieves selectors for a given domain."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM recipes WHERE domain = ?", (domain,)).fetchone()
            if row:
                res = dict(row)
                res['selectors'] = json.loads(res['selectors_json'])
                return res
            return None

    # --- Lead Management (Preserving Relationships) ---

    def save_leads_batch(self, task_id: str, leads: List[Dict[str, Any]], industry: str):
        """
        Saves a structured list of leads. 
        Expected format: [{'company': 'Safaricom', 'emails': ['info@safaricom.co.ke'], 'url': '...'}]
        """
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            for lead in leads:
                company = lead.get('company', 'Unknown')
                url = lead.get('url', 'N/A')
                for email in lead.get('emails', []):
                    conn.execute('''
                        INSERT OR IGNORE INTO leads_library 
                        (email, company_name, industry, source_url, task_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (email.lower(), company, industry, url, task_id, now))
            
            conn.commit()

        # FIX: Calculate true accumulation across all batches for this task
        cursor = conn.execute(
            "SELECT COUNT(*) FROM leads_library WHERE task_id = ?", 
            (task_id,)
        )
        total_count = cursor.fetchone()[0]
        
        # Update the task record with the real total
        self.update_task_status(task_id, 'running', lead_count=total_count)

    def get_leads_for_task(self, task_id: str) -> List[Dict]:
        """Retrieves all leads associated with a specific task for export."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM leads_library WHERE task_id = ?", (task_id,)).fetchall()
            return [dict(r) for r in rows]