"""Phase 2 — student academic history and planned courses API."""

import re
from contextlib import asynccontextmanager
from threading import RLock

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel


class HistoryCourse(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class HistoryPayload(BaseModel):
    history: list[HistoryCourse]


class PlanPayload(BaseModel):
    planned_courses: list[PlannedCourse]


app = FastAPI(title="Student Academic Profile API", version="1.0")
app.state.students = {}
app.state.lock = RLock()


def grade_priority(raw: str) -> int:
    """Numeric > letter > pass/empty/other (for duplicate-course ties)."""
    grade = raw.strip()
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?", grade):
        return 2
    if re.fullmatch(r"[A-DF][+-]?", grade, re.IGNORECASE):
        return 1
    return 0


def read_credits(raw: str) -> int:
    value = raw.strip().replace(",", "")
    try:
        number = float(value)
        return int(number) if number >= 0 and number.is_integer() else 0
    except ValueError:
        return 0


def parse_transcript(html: bytes) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    chosen = {}  # (course_code, term) -> (grade_priority, credits, history_record)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header = None
        header_index = None
        for idx, row in enumerate(rows):
            if row.find_parent("table") is not table:
                continue
            labels = [cell.get_text(" ", strip=True).lower().strip() for cell in row.find_all(["th", "td"], recursive=False)]
            # A title column may be present between Course and Grade.
            required = {"status", "course", "grade", "term", "credits"}
            if required.issubset(set(labels)):
                header = {label: labels.index(label) for label in required}
                header_index = idx
                break
        if header is None:
            continue
        for row in rows[header_index + 1:]:
            if row.find_parent("table") is not table:
                continue
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) <= max(header.values()):
                continue
            values = {name: cells[pos].get_text(" ", strip=True) for name, pos in header.items()}
            status = values["status"]
            code = values["course"]
            term = values["term"]
            if status not in {"Completed", "In-Progress", "Attempted"} or not term or not code:
                continue
            credits = read_credits(values["credits"])
            grade_rank = grade_priority(values["grade"])
            key = (code, term)
            score = (grade_rank, credits)
            if key not in chosen or score > chosen[key][:2]:
                chosen[key] = (*score, {
                    "course_code": code, "term": term,
                    "credits_earned": credits, "status": status,
                })
    return [entry[2] for entry in chosen.values()]


def require_student(student_id: str):
    if student_id not in app.state.students:
        raise HTTPException(status_code=404, detail="Student not found")
    return app.state.students[student_id]


@app.get("/")
def root():
    return {"status": "success", "message": "Student Academic Profile API is running"}


@app.post("/api/v1/students/{student_id}/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...)):
    history = parse_transcript(await file.read())
    with app.state.lock:
        existing = app.state.students.get(student_id)
        plan = existing["plan"] if existing else []
        app.state.students[student_id] = {"history": history, "plan": plan}
    return {"status": "success", "past_courses_imported": len(history)}


@app.put("/api/v1/students/{student_id}/history")
def put_history(student_id: str, payload: HistoryPayload):
    with app.state.lock:
        require_student(student_id)["history"] = [entry.model_dump() for entry in payload.history]
    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    with app.state.lock:
        require_student(student_id)["history"] = []
    return {"status": "success", "message": "Academic history cleared successfully"}


@app.post("/api/v1/students/{student_id}/plan")
def post_plan(student_id: str, payload: PlanPayload):
    with app.state.lock:
        require_student(student_id)["plan"] = [entry.model_dump() for entry in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}


@app.put("/api/v1/students/{student_id}/plan")
def put_plan(student_id: str, payload: PlanPayload):
    with app.state.lock:
        require_student(student_id)["plan"] = [entry.model_dump() for entry in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    with app.state.lock:
        require_student(student_id)["plan"] = []
    return {"status": "success", "message": "Course plan cleared successfully"}


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    with app.state.lock:
        student = require_student(student_id)
        return {"student_id": student_id, "history": [dict(c) for c in student["history"]], "plan": [dict(c) for c in student["plan"]]}
