import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class AuthManager:
    """Handle user authentication and authorization"""

    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _conn(self):
        """Return a fresh thread-safe connection from DBManager."""
        return self.db._get_connection()

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return f"{salt}${pwd_hash}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            salt, pwd_hash = stored_hash.split('$')
            test_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return test_hash == pwd_hash
        except Exception:
            return False

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, username: str, email: str, password: str,
                    full_name: str, role: str = 'viewer') -> Dict[str, Any]:
        user_id = str(uuid.uuid4())
        password_hash = self.hash_password(password)
        with self._conn() as conn:
            conn.execute(
                '''INSERT INTO users (user_id, username, email, password_hash, full_name, role)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (user_id, username, email, password_hash, full_name, role)
            )
        return {"user_id": user_id, "username": username,
                "email": email, "role": role}

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str,
                     ip_address: str, user_agent: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                '''SELECT user_id, username, email, password_hash, full_name, role, is_active
                   FROM users WHERE username = ? OR email = ?''',
                (username, username)
            ).fetchone()

        if not row:
            return None

        user_id, uname, email, pwd_hash, full_name, role, is_active = (
            row['user_id'], row['username'], row['email'],
            row['password_hash'], row['full_name'], row['role'], row['is_active']
        )

        if not is_active:
            return None
        if not self.verify_password(password, pwd_hash):
            return None

        # Update last login & create session in one connection block
        session_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=7)

        with self._conn() as conn:
            conn.execute(
                'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?',
                (user_id,)
            )
            conn.execute(
                '''INSERT INTO user_sessions
                   (session_id, user_id, token, ip_address, user_agent, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (session_id, user_id, token, ip_address, user_agent, expires_at)
            )

        return {
            "user_id": user_id,
            "username": uname,
            "email": email,
            "full_name": full_name,
            "role": role,
            "token": token,
            "expires_at": expires_at.isoformat()
        }

    # ------------------------------------------------------------------
    # Session validation / logout
    # ------------------------------------------------------------------

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                '''SELECT s.user_id, s.expires_at, u.username, u.email, u.role, u.is_active
                   FROM user_sessions s
                   JOIN users u ON s.user_id = u.user_id
                   WHERE s.token = ? AND s.is_active = 1''',
                (token,)
            ).fetchone()

        if not row:
            return None

        user_id, expires_at, username, email, role, is_active = (
            row['user_id'], row['expires_at'], row['username'],
            row['email'], row['role'], row['is_active']
        )

        if not is_active:
            return None
        if datetime.fromisoformat(expires_at) < datetime.now():
            self._deactivate_session(token)
            return None

        return {"user_id": user_id, "username": username,
                "email": email, "role": role}

    def _deactivate_session(self, token: str):
        with self._conn() as conn:
            conn.execute(
                'UPDATE user_sessions SET is_active = 0 WHERE token = ?',
                (token,)
            )

    def logout(self, token: str):
        self._deactivate_session(token)

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def log_activity(self, user_id: str, action_type: str,
                     resource_type: str = None, resource_id: str = None,
                     details: str = None, ip_address: str = None):
        log_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                '''INSERT INTO activity_log
                   (log_id, user_id, action_type, resource_type,
                    resource_id, details, ip_address)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (log_id, user_id, action_type, resource_type,
                 resource_id, details, ip_address)
            )

    def log_data_access(self, user_id: str, task_id: str,
                        company_name: str = None, email_viewed: str = None):
        access_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                '''INSERT INTO data_access_log
                   (access_id, user_id, task_id, company_name, email_viewed)
                   VALUES (?, ?, ?, ?, ?)''',
                (access_id, user_id, task_id, company_name, email_viewed)
            )

    def log_export(self, user_id: str, task_id: str, export_type: str,
                   file_format: str, record_count: int, file_path: str):
        export_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                '''INSERT INTO export_log
                   (export_id, user_id, task_id, export_type,
                    file_format, record_count, file_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (export_id, user_id, task_id, export_type,
                 file_format, record_count, file_path)
            )