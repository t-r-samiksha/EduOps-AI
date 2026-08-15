import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.scheduler import shutdown_scheduler, start_scheduler
from app.routers import (
    admin_alerts,
    admissions,
    approvals,
    attendance,
    audit,
    auth,
    documents,
    exams,
    fees,
    master_data,
    parent,
    parents,
    reference,
    risk,
    staffing,
    students,
    syllabus,
    teachers,
    timetable,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Real scheduled execution for the 4 previously-manual-only nightly/monthly
    # jobs (see app/scheduler.py's module docstring) - starts automatically
    # whenever this process runs, stops cleanly on shutdown. The manual CLI
    # scripts (`python -m scripts.run_nightly_risk_scoring ...`) keep working
    # unchanged alongside this.
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="EduOps AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(timetable.router)
app.include_router(attendance.router)
app.include_router(staffing.router)
app.include_router(risk.router)
app.include_router(documents.router)
app.include_router(admin_alerts.router)
app.include_router(syllabus.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(fees.router)
app.include_router(admissions.router)
app.include_router(exams.router)
app.include_router(reference.router)
app.include_router(parent.router)
app.include_router(master_data.router)
app.include_router(teachers.router)
app.include_router(students.router)
app.include_router(parents.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
