"""
Database Schemas for ChapterSmith AI

Define MongoDB schemas using Pydantic models. Each class name lowercased maps to the collection name.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

class Project(BaseModel):
    title: Optional[str] = Field(None, description="Optional project title")
    outline: str = Field(..., description="User provided outline text")
    chapter_count: Literal[3,4,5,6] = Field(..., description="Total chapters to generate")
    pov_mode: Literal["female","male","dual"] = Field("female", description="POV mode selection")
    genre: Optional[Literal["billionaire","werewolf","mafia","general"]] = Field("general", description="Optional genre hints")

class Chapter(BaseModel):
    project_id: str = Field(..., description="Related project id as string")
    number: int = Field(..., ge=1, description="Chapter number (1-indexed)")
    title: Optional[str] = Field(None, description="Chapter title")
    content: Optional[str] = Field(None, description="Full chapter text")
    pov_used: Optional[Literal["female","male"]] = Field(None, description="Resolved POV for this chapter")
    word_count: Optional[int] = Field(None, ge=0)
    status: Literal["pending","generated","edited","error"] = Field("pending")
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
