import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

class DBManager:
    def __init__(self, db_name="enolix_leads_v3.db"):
        # Ensure the database stays in the DATA folder
        self.db_path = os.path.join(os.path.dirname(__file__), db_name)
        self._create_users_table()
        self._create_user_sessions_table()
        self._create_activity_log_table()
        self._create_data_access_log_table()
        self._create_export_log_table()
        self._init_db()

    def _get_connection(self):
        """Returns a thread-safe connection with row factory for dict-like access."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes the schema with Job Tracking, Recipes, and Leads."""
        with self._get_connection() as conn:
            # 1. Tasks/Jobs Table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'pending',
                    industry TEXT,
                    lead_count INTEGER DEFAULT 0,
                    company_count INTEGER DEFAULT 0,
                    current_tier INTEGER DEFAULT 1,
                    progress_state TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            
            # MIGRATION: Add new columns if they don't exist
            try:
                conn.execute("SELECT current_tier FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                conn.execute("ALTER TABLE tasks ADD COLUMN current_tier INTEGER DEFAULT 1")
                print("[DB Migration] Added current_tier column to tasks table")
            
            try:
                conn.execute("SELECT progress_state FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE tasks ADD COLUMN progress_state TEXT")
                print("[DB Migration] Added progress_state column to tasks table")
            
            try:
                conn.execute("SELECT company_count FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE tasks ADD COLUMN company_count INTEGER DEFAULT 0")
                print("[DB Migration] Added company_count column to tasks table")

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
             # 4. admin setup — always ensure correct hash regardless of existing row
            import hashlib
            _salt = 'defaultsalt00001'
            _hash = hashlib.sha256(('admin1234' + _salt).encode()).hexdigest()
            _pwd = f'{_salt}${_hash}'
            conn.execute(
                '''INSERT OR IGNORE INTO users
                   (user_id, username, email, password_hash, full_name, role, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                ('admin-001', 'admin', 'admin@leadsystem.local',
                 _pwd, 'System Administrator', 'admin', 1)
            )
            conn.execute(
                'UPDATE users SET password_hash = ?, is_active = 1 WHERE user_id = ?',
                (_pwd, 'admin-001')
            )
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
    
    def update_task_progress(self, task_id: str, tier: int, progress_state: dict):
        """Updates task progress for recovery."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE tasks 
                SET current_tier = ?, 
                    progress_state = ?, 
                    updated_at = ?
                WHERE task_id = ?
            """, (tier, json.dumps(progress_state), datetime.now(), task_id))
            conn.commit()


    def get_task_progress(self, task_id: str) -> Optional[dict]:
        """Retrieves task progress for recovery."""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT current_tier, progress_state 
                FROM tasks 
                WHERE task_id = ?
            """, (task_id,)).fetchone()
            if row:
                return {
                    "tier": row["current_tier"],
                    "state": json.loads(row["progress_state"]) if row["progress_state"] else {}
                }
            return None 

    def get_leads_by_industry(self, industry: str) -> List[Dict]:
        """Retrieves all leads for a specific industry."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM leads_library WHERE LOWER(industry) = LOWER(?) ORDER BY created_at DESC", 
                (industry,)
            ).fetchall()
            return [dict(r) for r in rows]
    
    def get_all_industries(self) -> List[str]:
        """Returns a list of all unique industries in the database."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT industry FROM leads_library WHERE industry IS NOT NULL ORDER BY industry"
            ).fetchall()
            return [row[0] for row in rows if row[0]]

    # Add after existing table definitions

    def _create_users_table(self):
        """Create users authentication table"""
        with self._get_connection() as conn:
            conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                role TEXT DEFAULT 'viewer',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        conn.commit()

    def _create_user_sessions_table(self):
        """Track active user sessions"""
        with self._get_connection() as conn:
            conn.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()

    def _create_activity_log_table(self):
        """Log all user activities"""
        with self._get_connection() as conn:
            conn.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                log_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                details TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()

    def _create_data_access_log_table(self):
        """Track what data users viewed"""
        with self._get_connection() as conn:
            conn.execute('''
            CREATE TABLE IF NOT EXISTS data_access_log (
                access_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                task_id TEXT,
                company_name TEXT,
                email_viewed TEXT,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        ''')
        conn.commit()

    def _create_export_log_table(self):
        """Track document exports"""
        with self._get_connection() as conn:
            conn.execute('''
            CREATE TABLE IF NOT EXISTS export_log (
                export_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                task_id TEXT,
                export_type TEXT NOT NULL,
                file_format TEXT,
                record_count INTEGER,
                file_path TEXT,
                exported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        ''')
        conn.commit()               
