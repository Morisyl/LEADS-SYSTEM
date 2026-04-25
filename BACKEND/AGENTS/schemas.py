from pydantic import BaseModel, EmailStr
from typing import Set, List, Optional
from datetime import datetime

class Lead(BaseModel):
    email: str
    company: str = "Unknown"
    source_url: Optional[str] = None
    industry: str = "General"

class Recipe(BaseModel):
    domain: str
    pagination_type: str  # "html" or "java_button"
    selectors: dict
    max_pages: int = 5

class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending", "running", "complete", "failed"
    leads_found: int = 0
    created_at: datetime