import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import attendance, auth, documents, risk, staffing, timetable

app = FastAPI(title="EduOps AI API")

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


@app.get("/health")
def health_check():
    return {"status": "ok"}
