import os
from typing import List, Optional, Literal, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="ChapterSmith AI – Complete Story Builder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Utility
# ---------------------------

def to_str_id(doc: Dict[str, Any]):
    if doc is None:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d

# ---------------------------
# Schemas (API I/O)
# ---------------------------

class CreateProjectRequest(BaseModel):
    title: Optional[str] = None
    outline: str
    chapter_count: Literal[3,4,5,6]
    pov_mode: Literal["female","male","dual"] = "female"
    genre: Optional[Literal["billionaire","werewolf","mafia","general"]] = "general"

class ProjectResponse(BaseModel):
    id: str
    title: Optional[str] = None
    outline: str
    chapter_count: int
    pov_mode: str
    genre: Optional[str] = None

class ChapterMeta(BaseModel):
    project_id: str
    number: int
    title: Optional[str] = None
    pov_used: Optional[str] = None
    status: Literal["pending","generated","edited","error"] = "pending"
    word_count: Optional[int] = None

class GenerateChapterRequest(BaseModel):
    project_id: str
    number: int
    outline_hint: Optional[str] = None
    override_pov: Optional[Literal["female","male"]] = None

class SaveChapterRequest(BaseModel):
    project_id: str
    number: int
    title: Optional[str] = None
    content: str
    pov_used: Optional[Literal["female","male"]] = None

# ---------------------------
# Health and utility endpoints
# ---------------------------

@app.get("/")
def read_root():
    return {"message": "ChapterSmith AI backend running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "❌ db not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ---------------------------
# Project + Chapter endpoints
# ---------------------------

@app.post("/api/projects", response_model=ProjectResponse)
def create_project(payload: CreateProjectRequest):
    data = payload.model_dump()
    project_id = create_document("project", data)
    doc = db["project"].find_one({"_id": ObjectId(project_id)})
    return to_str_id(doc)

@app.get("/api/projects", response_model=List[ProjectResponse])
def list_projects():
    docs = get_documents("project")
    return [to_str_id(d) for d in docs]

@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str):
    doc = db["project"].find_one({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    return to_str_id(doc)

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    # delete project and its chapters
    db["project"].delete_one({"_id": ObjectId(project_id)})
    db["chapter"].delete_many({"project_id": project_id})
    return {"ok": True}

@app.get("/api/projects/{project_id}/chapters", response_model=List[ChapterMeta])
def list_chapters(project_id: str):
    docs = db["chapter"].find({"project_id": project_id}).sort("number", 1)
    res = []
    for d in docs:
        res.append(ChapterMeta(
            project_id=project_id,
            number=d.get("number"),
            title=d.get("title"),
            pov_used=d.get("pov_used"),
            status=d.get("status", "pending"),
            word_count=d.get("word_count")
        ))
    return res

@app.post("/api/chapters/save")
def save_chapter(payload: SaveChapterRequest):
    # Enforce word count if provided
    wc = len(payload.content.split()) if payload.content else 0
    db["chapter"].update_one(
        {"project_id": payload.project_id, "number": payload.number},
        {"$set": {
            "title": payload.title,
            "content": payload.content,
            "pov_used": payload.pov_used,
            "status": "edited" if db["chapter"].find_one({"project_id": payload.project_id, "number": payload.number}) else "generated",
            "word_count": wc
        }},
        upsert=True
    )
    return {"ok": True, "word_count": wc}

# Placeholder generation route (no external LLM). It returns a structured prompt and guidance
# for the frontend to copy or use with their own key, then stores a placeholder chapter record.

class GenerationPlan(BaseModel):
    chapter_title: str
    resolved_pov: Literal["female","male"]
    system_rules: str
    user_prompt: str

@app.post("/api/chapters/prepare", response_model=GenerationPlan)
def prepare_chapter_generation(payload: GenerateChapterRequest):
    project = db["project"].find_one({"_id": ObjectId(payload.project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # POV resolution logic
    pov_mode = project.get("pov_mode", "female")
    resolved: Literal["female","male"]
    if payload.override_pov in ("female","male"):
        resolved = payload.override_pov
    elif pov_mode == "female":
        resolved = "female"
    elif pov_mode == "male":
        resolved = "male"
    else:  # dual
        resolved = "female" if (payload.number % 2 == 1) else "male"

    # Build rules and prompt
    word_rule = (
        "Each chapter must be strictly between 1400 and 1800 words. "
        "Do not write less than 1400 words, and do not exceed 1800 words. "
        "Ensure the chapter feels complete and cohesive while staying within this word count."
    )

    pov_rule = f"Use deep first-person POV from the {resolved} lead’s perspective, staying close to their thoughts, emotions, and physical sensations. Always use 'I', 'my', and 'me' for reactions."

    style_rules = (
        "Write in a clear, grounded, human tone. Avoid poetic or metaphor-heavy language, fragments, and clichés. "
        "Mix short and long sentences naturally, maintain smooth pacing, start with tension/action/dialogue, end with an emotional hook. "
        "Balance action with internal monologue. Show through concrete sensory detail without dramatized phrasing. "
        "Dialogue must be natural and reveal subtext through behavior and tone, not labels. "
        "No metaphors or flowery imagery unless absolutely necessary for character voice. "
        "Avoid contractions if that supports clarity (e.g., 'I had', 'He did not')."
    )

    genre_hint = project.get("genre", "general")
    genre_block = ""
    if genre_hint == "billionaire":
        genre_block = (
            "Billionaire Romance focus: wealth, control, power imbalance, luxury vs loneliness; high sexual tension with higher emotional stakes. "
            "Hero commanding yet complex; heroine torn between independence and desire.\n"
        )
    elif genre_hint == "werewolf":
        genre_block = (
            "Werewolf Romance focus: primal instinct, pack politics, destiny, protective alpha balancing dominance with tenderness.\n"
        )
    elif genre_hint == "mafia":
        genre_block = (
            "Mafia Romance focus: danger, loyalty, obsession, crime secrecy, and trust issues; dark but human.\n"
        )

    outline = payload.outline_hint or project.get("outline", "")

    system_rules = "\n".join([
        word_rule,
        pov_rule,
        style_rules,
        genre_block,
        "Maintain continuity with previous chapters; smooth transitions; no abrupt time jumps.",
        "Every chapter opens with immediate tension/action/dialogue and ends with a strong emotional beat or hook.",
    ])

    title = f"Chapter {payload.number}"

    user_prompt = f"""
You are writing Chapter {payload.number} of a {project.get('chapter_count')} chapter story.
POV Mode: {project.get('pov_mode')} (resolved to {resolved} for this chapter)
Genre: {genre_hint}

Outline/Foundation for this chapter:
{outline}

Write the full chapter now. Output only:
1) Chapter Title (single line)
2) Chapter Text (1400–1800 words)
3) Ensure natural, grounded first-person narration from the {resolved} lead. Keep tone human and emotionally authentic.
"""

    # Create/ensure placeholder document for continuity tracking
    db["chapter"].update_one(
        {"project_id": payload.project_id, "number": payload.number},
        {"$setOnInsert": {
            "project_id": payload.project_id,
            "number": payload.number,
            "status": "pending",
        }, "$set": {
            "pov_used": resolved,
            "title": title,
        }},
        upsert=True
    )

    return GenerationPlan(
        chapter_title=title,
        resolved_pov=resolved,
        system_rules=system_rules,
        user_prompt=user_prompt.strip()
    )
