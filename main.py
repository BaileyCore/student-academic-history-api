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

# Phase 3: catalog import and academic audit integration.
app.state.catalog = {}


def normalize_code(value: str) -> str:
    return re.sub(r'[\s-]', '', value).upper()


def course_codes(value: str) -> list[str]:
    return list(dict.fromkeys(normalize_code(c) for c in
        re.findall(r'\b[A-Za-z]{3,5}[ -]?\d{4}[A-Za-z]?\b', value)))


def term_order(term: str) -> tuple[int, int]:
    match = re.fullmatch(r'(\d{2}|\d{4})([WSF])', term.upper().strip())
    if not match:
        raise HTTPException(422, detail=f'Invalid term: {term}; use YYW, YYS, or YYF')
    year = int(match[1])
    return (year + 2000 if year < 100 else year, {'W': 0, 'S': 1, 'F': 2}[match[2]])


@app.post('/api/v1/admin/catalog/import', status_code=201)
async def import_catalog(file: UploadFile = File(...)):
    soup = BeautifulSoup(await file.read(), 'html.parser')
    catalog = {}
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        mapping = None
        for row in rows:
            cells = row.find_all(['th', 'td'], recursive=False)
            values = [c.get_text(' ', strip=True) for c in cells]
            labels = [v.lower() for v in values]
            if {'course code', 'credits', 'prerequisites', 'cross-listed'}.issubset(labels):
                mapping = {label: labels.index(label) for label in labels}
                continue
            if not mapping or len(values) <= max(mapping.values()):
                continue
            get = lambda key: values[mapping[key]] if key in mapping else ''
            codes = course_codes(get('course code'))
            if not codes:
                continue
            catalog[codes[0]] = {'course_code': get('course code'),
                'credits': read_credits(get('credits')),
                'prerequisites': course_codes(get('prerequisites')),
                'cross_listed': course_codes(get('cross-listed'))}
    if not catalog:
        raise HTTPException(422, detail='No catalog courses found in the uploaded table')
    with app.state.lock:
        app.state.catalog = catalog
    return {'status': 'success', 'courses_imported': len(catalog)}


@app.get('/api/v1/students/{student_id}/audit-report')
def audit_report(student_id: str, strict: bool = False):
    with app.state.lock:
        student = require_student(student_id)
        history = [dict(c) for c in student['history']]
        plan = [dict(c) for c in student['plan']]
        catalog = dict(app.state.catalog)
    completed = {}
    for course in history:
        if course['status'] == 'Completed':
            code = normalize_code(course['course_code'])
            completed[code] = max(completed.get(code, 0), course['credits_earned'])
    timeline = []
    violations = []
    seen_plan = set()
    planned_credits = 0
    for course in sorted(plan, key=lambda c: term_order(c['term'])):
        code = normalize_code(course['course_code'])
        order = term_order(course['term'])
        errors = []
        spec = catalog.get(code)
        if spec is None:
            errors.append({'type': 'UNKNOWN_COURSE', 'course_code': course['course_code']})
        else:
            if code not in seen_plan:
                planned_credits += spec['credits']
                seen_plan.add(code)
            available = {normalize_code(h['course_code']) for h in history
                if h['status'] == 'Completed' and term_order(h['term']) < order}
            available.update(normalize_code(p['course_code']) for p in plan
                if term_order(p['term']) < order)
            for prereq in spec['prerequisites']:
                if prereq not in available:
                    errors.append({'type': 'MISSING_PREREQUISITE',
                        'course_code': course['course_code'], 'prerequisite': prereq})
            related = set(spec['cross_listed'])
            related.update(k for k, v in catalog.items() if code in v['cross_listed'])
            for other in sorted(related):
                if other in completed or any(normalize_code(p['course_code']) == other for p in plan):
                    violation = {'type': 'CROSS_LIST_VIOLATION', 'course_code': course['course_code'], 'conflicting_course': other}
                    if violation not in violations:
                        violations.append(violation)
        timeline.append({**course, 'errors': errors})
    has_issues = bool(violations or any(e['errors'] for e in timeline))
    earned = sum(completed.values())
    return {'student_id': student_id,
        'status': ('failed' if strict else 'warning') if has_issues else 'passed',
        'timeline_validation': timeline, 'cross_list_violations': violations,
        'credit_summary': {'total_earned': earned, 'total_planned': planned_credits,
            'total_remaining_for_graduation': max(0, 120 - earned - planned_credits)}}
