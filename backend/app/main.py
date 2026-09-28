import json
import base64
import hashlib
import hmac
import os
import re
import secrets
import socket
import string
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from .models import Answer, Question, QuizSession, TabSwitchEvent, Team, now
from .scoring import QUESTION_SECONDS, score_answer

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="AI Avlokan Quiz API")
app_env = os.getenv("APP_ENV", "development").lower()
frontend_origins = [origin.strip().rstrip("/") for origin in os.getenv("FRONTEND_ORIGIN", os.getenv("FRONTEND_URL", "http://localhost:5173")).split(",") if origin.strip()]
public_app_url = os.getenv("PUBLIC_APP_URL", "").rstrip("/")
lan_frontend_origin = r"https?://(?:localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?::\d+)?"
app.add_middleware(CORSMiddleware, allow_origins=frontend_origins, allow_origin_regex=lan_frontend_origin if app_env != "production" else None, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
allowed_hosts = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()]
if allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
admin_password = os.getenv("ADMIN_PASSWORD", "amruthasin" if app_env != "production" else "")
admin_secret = os.getenv("ADMIN_SECRET", admin_password)

class LoginBody(BaseModel):
    password: str
class JoinBody(BaseModel):
    session_code: str
    team_name: str
class AnswerBody(BaseModel):
    selected_option: str
    question_number: int
class TabBody(BaseModel):
    event: str
    hidden_at: datetime | None = None
class ActivityBody(BaseModel):
    activity_type: str

AWAY_ACTIVITY_TYPES = {"TAB_HIDDEN", "WINDOW_BLUR"}
RETURN_ACTIVITY_TYPES = {"TAB_VISIBLE", "WINDOW_FOCUS"}
POINT_ACTIVITY_TYPES = {"FULLSCREEN_EXIT", "COPY_ATTEMPT", "PASTE_ATTEMPT", "CUT_ATTEMPT"}

@app.on_event("startup")
def startup():
    if app_env == "production":
        configured_admin_secret = os.getenv("ADMIN_SECRET", "")
        if len(admin_password) < 12 or len(configured_admin_secret) < 32 or hmac.compare_digest(configured_admin_secret, admin_password):
            raise RuntimeError("Production requires a strong ADMIN_PASSWORD and a separate ADMIN_SECRET of at least 32 characters")
        if not public_app_url.startswith("https://"):
            raise RuntimeError("Production PUBLIC_APP_URL must use HTTPS")
        if not frontend_origins or any(not origin.startswith("https://") for origin in frontend_origins):
            raise RuntimeError("Production FRONTEND_ORIGIN values must use HTTPS")
        if allowed_hosts == ["*"]:
            raise RuntimeError("Production ALLOWED_HOSTS must list the backend host name(s)")
        if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Production DATABASE_URL must point to PostgreSQL")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    columns = {column["name"] for column in inspect(engine).get_columns("questions")}
    if "challenge" not in columns:
        db.execute(text("ALTER TABLE questions ADD COLUMN challenge BOOLEAN NOT NULL DEFAULT FALSE"))
        db.commit()
    event_columns = {column["name"] for column in inspect(engine).get_columns("tab_switch_events")}
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    activity_migrations = {
        "session_id": "INTEGER REFERENCES quiz_sessions(id)",
        "question_id": "INTEGER REFERENCES questions(id)",
        "question_number": "INTEGER NOT NULL DEFAULT 1",
        "activity_type": "VARCHAR(32) NOT NULL DEFAULT 'TAB_HIDDEN'",
        "created_at": timestamp_type,
    }
    for column_name, column_definition in activity_migrations.items():
        if column_name not in event_columns:
            db.execute(text(f"ALTER TABLE tab_switch_events ADD COLUMN {column_name} {column_definition}"))
    for index_name, column_name in (("ix_tab_switch_events_team_id", "team_id"), ("ix_tab_switch_events_session_id", "session_id"), ("ix_tab_switch_events_activity_type", "activity_type")):
        db.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON tab_switch_events ({column_name})"))
    team_columns = {column["name"] for column in inspect(engine).get_columns("teams")}
    if "paused_remaining_seconds" not in team_columns:
        float_type = "FLOAT" if engine.dialect.name == "postgresql" else "REAL"
        db.execute(text(f"ALTER TABLE teams ADD COLUMN paused_remaining_seconds {float_type}"))
        db.commit()
    session_columns = {column["name"] for column in inspect(engine).get_columns("quiz_sessions")}
    if "paused_at" not in session_columns:
        db.execute(text(f"ALTER TABLE quiz_sessions ADD COLUMN paused_at {timestamp_type}"))
        db.commit()
    duplicate_answer = db.execute(text("SELECT team_id, question_number FROM answers GROUP BY team_id, question_number HAVING COUNT(*) > 1 LIMIT 1")).first()
    if duplicate_answer:
        db.close()
        raise RuntimeError("Duplicate answers exist for a team/question; resolve them before enabling answer uniqueness")
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_answer_team_question ON answers (team_id, question_number)"))
    db.commit()
    seed_path = Path(__file__).resolve().parent.parent / "data" / "questions.json"
    for item in json.loads(seed_path.read_text(encoding="utf-8")):
        question = db.query(Question).filter_by(question_number=item["question_number"]).first()
        if question:
            for key, value in item.items():
                setattr(question, key, value)
        else:
            db.add(Question(**item))
    db.commit()
    db.close()

def require_admin(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ") if authorization else ""
    if not valid_admin_token(token):
        raise HTTPException(status_code=401, detail="Admin authentication required")

def issue_admin_token() -> str:
    issued_at = str(int(time.time()))
    signature = hmac.new(admin_secret.encode(), issued_at.encode(), hashlib.sha256).digest()
    return f"{issued_at}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"

def valid_admin_token(token: str) -> bool:
    try:
        issued_at_text, signature_text = token.split(".", 1)
        issued_at = int(issued_at_text)
    except (AttributeError, ValueError):
        return False
    if issued_at > int(time.time()) or int(time.time()) - issued_at > 12 * 60 * 60:
        return False
    expected = issue_signature(issued_at_text)
    return hmac.compare_digest(signature_text, expected)

def issue_signature(issued_at: str) -> str:
    signature = hmac.new(admin_secret.encode(), issued_at.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip("=")

def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    normalized = origin.rstrip("/")
    return normalized in frontend_origins or (app_env != "production" and re.fullmatch(lan_frontend_origin, normalized) is not None)

def get_session(db: Session, session_id: int) -> QuizSession:
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    return session

def get_team(db: Session, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team

def public_question(question: Question) -> dict[str, Any]:
    return {"number": question.question_number, "text": question.question_text, "options": {"A": question.option_a, "B": question.option_b, "C": question.option_c, "D": question.option_d}, "challenge": question.challenge}

def elapsed(team: Team) -> float:
    if not team.question_started_at:
        return 0
    return max(0, (datetime.now(timezone.utc) - team.question_started_at.replace(tzinfo=timezone.utc)).total_seconds())

def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def complete_or_advance(db: Session, team: Team):
    if team.current_question >= 30:
        team.status = "completed"
        team.completed_at = now()
        team.question_started_at = None
    else:
        team.current_question += 1
        team.question_started_at = now()
    session = team.session
    if session and session.teams and all(member.status == "completed" for member in session.teams):
        session.status = "completed"
        session.completed_at = now()

def process_timeout(db: Session, team: Team):
    if team.status != "active" or elapsed(team) < QUESTION_SECONDS:
        return False
    question_number = team.current_question
    if not db.query(Answer).filter_by(team_id=team.id, question_number=question_number).first():
        db.add(Answer(team_id=team.id, question_number=question_number, selected_option=None, response_seconds=QUESTION_SECONDS, score=0))
        complete_or_advance(db, team)
        db.commit()
        return True
    return False

def team_payload(db: Session, team: Team) -> dict[str, Any]:
    if team.status == "active":
        process_timeout(db, team)
    question = db.query(Question).filter_by(question_number=team.current_question).first()
    if team.status == "active":
        remaining = max(0.0, QUESTION_SECONDS - elapsed(team))
        deadline = team.question_started_at.timestamp() + QUESTION_SECONDS if team.question_started_at else None
    elif team.status == "paused":
        remaining = max(0.0, team.paused_remaining_seconds if team.paused_remaining_seconds is not None else 0.0)
        deadline = None
    else:
        remaining = 0.0
        deadline = None
    payload = {
        "team_id": team.id,
        "team_name": team.team_name,
        "status": team.status,
        "session_status": team.session.status if team.session else team.status,
        "current_question": team.current_question,
        "total_questions": 30,
        "remaining_seconds": round(remaining, 1),
        "is_paused": team.status == "paused" or (team.session and team.session.status == "paused"),
        "question_started_at": team.question_started_at.isoformat() if team.question_started_at else None,
        "question_deadline": datetime.fromtimestamp(deadline, timezone.utc).isoformat() if deadline else None,
        "question": public_question(question) if (team.status in ("active", "paused") and question) else None,
    }
    if team.status == "completed":
        payload["completion"] = {
            "submitted": True,
            "completed_at": team.completed_at.isoformat() if team.completed_at else None,
        }
    return payload

def team_row(db: Session, team: Team) -> dict[str, Any]:
    answers = db.query(Answer).filter_by(team_id=team.id).all()
    activities = [activity for activity in team.tab_events if activity.session_id == team.session_id]
    affected_questions = sorted({activity.question_number for activity in activities if activity.activity_type in AWAY_ACTIVITY_TYPES | POINT_ACTIVITY_TYPES})
    open_away = next((activity for activity in reversed(activities) if activity.activity_type in AWAY_ACTIVITY_TYPES and activity.visible_at is None), None)
    live_away = max(0, (datetime.now(timezone.utc) - as_utc(open_away.hidden_at)).total_seconds()) if open_away else 0
    return {"id": team.id, "team_name": team.team_name, "current_question": team.current_question, "score": team.score, "tab_switches": team.tab_switch_count, "away_seconds": round(team.total_away_seconds + live_away, 1), "affected_questions": affected_questions, "activity_count": len(activities), "current_activity": open_away.activity_type if open_away else None, "correct": sum(a.is_correct for a in answers), "wrong": sum(a.selected_option is not None and not a.is_correct for a in answers), "unanswered": sum(a.selected_option is None for a in answers), "response_seconds": sum(a.response_seconds for a in answers if a.selected_option is not None), "completed_at": team.completed_at.timestamp() if team.completed_at else 32503680000, "status": team.status}

def dashboard_payload(db: Session, session: QuizSession) -> dict[str, Any]:
    teams = [team_row(db, team) for team in session.teams]
    teams.sort(key=lambda item: (-item["score"], item["response_seconds"], item["completed_at"], item["team_name"].lower()))
    for index, team in enumerate(teams, 1):
        team["rank"] = index
    active_questions = [team["current_question"] for team in teams if team["status"] in ("active", "paused")]
    current = max(active_questions or [30 if teams and all(team["status"] == "completed" for team in teams) else 0])
    distribution = {letter: 0 for letter in "ABCD"}
    fastest = []
    for team in session.teams:
        for answer in team.answers:
            if answer.question_number == current and answer.selected_option:
                distribution[answer.selected_option] += 1
                if answer.is_correct:
                    fastest.append({"team_name": team.team_name, "seconds": round(answer.response_seconds, 2)})
    fastest.sort(key=lambda item: item["seconds"])
    distribution["unanswered"] = sum(not any(answer.question_number == current for answer in team.answers) for team in session.teams)
    return {
        "session": {
            "id": session.id,
            "code": session.session_code,
            "status": session.status,
            "current_question": current,
            "total_questions": 30,
            "paused_at": session.paused_at.isoformat() if session.paused_at else None,
        },
        "teams": teams,
        "leaderboard": teams[:10],
        "distribution": distribution,
        "fastest": fastest[:5],
    }

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/admin/login")
def login(body: LoginBody):
    if not admin_password or not hmac.compare_digest(body.password, admin_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": issue_admin_token()}

def make_session(db: Session) -> QuizSession:
    while True:
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if not db.query(QuizSession).filter_by(session_code=code).first():
            break
    session = QuizSession(session_code=code)
    db.add(session)
    db.flush()
    return session

def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def frontend_join_url(request: Request, session_code: str) -> str:
    if app_env == "production" and public_app_url:
        return f"{public_app_url}/join/{session_code}"
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and origin_allowed(origin):
        if "localhost" not in origin and "127.0.0.1" not in origin:
            return f"{origin}/join/{session_code}"
    lan_ip = get_lan_ip()
    if lan_ip and lan_ip != "127.0.0.1":
        return f"http://{lan_ip}:5173/join/{session_code}"
    if public_app_url:
        return f"{public_app_url}/join/{session_code}"
    return f"http://localhost:5173/join/{session_code}"

@app.post("/api/admin/session/create")
def create_session(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = make_session(db)
    db.commit()
    return {"id": session.id, "code": session.session_code, "join_url": frontend_join_url(request, session.session_code), "status": session.status}

@app.get("/api/admin/session/current")
def current_session(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = db.query(QuizSession).filter(QuizSession.status != "archived").order_by(QuizSession.id.desc()).first()
    if not session:
        return None
    info = {"id": session.id, "code": session.session_code, "join_url": frontend_join_url(request, session.session_code), "status": session.status}
    return {"session": info, "dashboard": dashboard_payload(db, session)}

@app.post("/api/admin/session/reset")
def reset_session(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    current = db.query(QuizSession).filter(QuizSession.status != "archived").order_by(QuizSession.id.desc()).first()
    if current:
        current.status = "archived"
        if not current.completed_at:
            current.completed_at = now()
    session = make_session(db)
    db.commit()
    db.refresh(session)
    info = {"id": session.id, "code": session.session_code, "join_url": frontend_join_url(request, session.session_code), "status": session.status}
    return {"message": "New quiz session created successfully.", "session": info, "dashboard": dashboard_payload(db, session)}

@app.get("/api/admin/sessions/history")
def session_history(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    sessions = db.query(QuizSession).filter(QuizSession.status.in_(["completed", "archived"])).order_by(QuizSession.created_at.desc(), QuizSession.id.desc()).all()
    return [{"id": session.id, "code": session.session_code, "created_at": session.created_at.isoformat(), "completed_at": session.completed_at.isoformat() if session.completed_at else None, "team_count": len(session.teams), "status": session.status} for session in sessions]

@app.get("/api/admin/results/{session_id}")
def session_results(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    payload = dashboard_payload(db, session)
    results = [{"rank": team["rank"], "team_name": team["team_name"], "score": team["score"], "tab_switches": team["tab_switches"], "total_away_seconds": team["away_seconds"], "correct": team["correct"], "wrong": team["wrong"], "unanswered": team["unanswered"], "current_question": team["current_question"], "status": team["status"]} for team in payload["teams"]]
    return {"session": {"id": session.id, "code": session.session_code, "created_at": session.created_at.isoformat(), "completed_at": session.completed_at.isoformat() if session.completed_at else None, "status": session.status, "team_count": len(results)}, "leaderboard": results}

@app.post("/api/admin/session/{session_id}/start")
def start_session(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    if session.status == "paused":
        return resume_session(session_id, _, db)
    if session.status != "waiting":
        raise HTTPException(status_code=400, detail=f"Session is already {session.status}")
    if not session.teams:
        raise HTTPException(status_code=400, detail="Cannot start quiz with no teams connected. Please wait for participants to join.")
    session.status = "active"
    session.started_at = now()
    session.paused_at = None
    for team in session.teams:
        team.status = "active"
        team.current_question = 1
        team.question_started_at = now()
        team.paused_remaining_seconds = None
    db.commit()
    return dashboard_payload(db, session)

@app.post("/api/admin/session/{session_id}/pause")
def pause_session(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="Only an active quiz can be paused")
    session.status = "paused"
    session.paused_at = now()
    for team in session.teams:
        if team.status == "active":
            spent = elapsed(team)
            rem = max(0.0, QUESTION_SECONDS - spent)
            team.status = "paused"
            team.paused_remaining_seconds = rem
    db.commit()
    return dashboard_payload(db, session)

@app.post("/api/admin/session/{session_id}/resume")
def resume_session(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    if session.status != "paused":
        raise HTTPException(status_code=400, detail="Only a paused quiz can be resumed")
    session.status = "active"
    session.paused_at = None
    current_time = now()
    for team in session.teams:
        if team.status == "paused":
            team.status = "active"
            rem = team.paused_remaining_seconds if team.paused_remaining_seconds is not None else QUESTION_SECONDS
            spent = max(0.0, QUESTION_SECONDS - rem)
            team.question_started_at = current_time - timedelta(seconds=spent)
            team.paused_remaining_seconds = None
    db.commit()
    return dashboard_payload(db, session)

@app.post("/api/admin/session/{session_id}/stop")
@app.post("/api/admin/session/{session_id}/end")
def stop_session(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    if session.status in ("completed", "archived"):
        return dashboard_payload(db, session)
    session.status = "completed"
    session.completed_at = now()
    session.paused_at = None
    for team in session.teams:
        if team.status != "completed":
            team.status = "completed"
            team.completed_at = now()
            team.paused_remaining_seconds = None
    db.commit()
    return dashboard_payload(db, session)

@app.get("/api/admin/session/{session_id}")
def admin_session(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard_payload(db, get_session(db, session_id))

@app.get("/api/admin/leaderboard/{session_id}")
def leaderboard(session_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard_payload(db, get_session(db, session_id))["leaderboard"]

@app.get("/api/admin/team/{team_id}")
def team_detail(team_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    team = get_team(db, team_id)
    activities = sorted((activity for activity in team.tab_events if activity.session_id == team.session_id), key=lambda activity: activity.hidden_at)
    return {"team": team_row(db, team), "answers": [{"question": a.question_number, "selected": a.selected_option, "correct": a.is_correct, "seconds": a.response_seconds, "score": a.score} for a in team.answers], "activities": [{"question_id": activity.question_id, "question_number": activity.question_number, "activity_type": activity.activity_type, "started_at": activity.hidden_at.isoformat(), "returned_at": activity.visible_at.isoformat() if activity.visible_at else None, "duration_seconds": round(activity.away_seconds, 1) if activity.activity_type in AWAY_ACTIVITY_TYPES and activity.visible_at else None} for activity in activities]}

@app.post("/api/join")
def join(body: JoinBody, db: Session = Depends(get_db)):
    session = db.query(QuizSession).filter(func.upper(QuizSession.session_code) == body.session_code.strip().upper()).first()
    if not session or session.status not in ("waiting", "active", "paused"):
        raise HTTPException(status_code=400, detail="That quiz is not accepting teams")
    name = body.team_name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Enter a team name")
    if db.query(Team).filter_by(session_id=session.id, team_name=name).first():
        raise HTTPException(status_code=409, detail="That team name is already taken")
    team = Team(session_id=session.id, team_name=name)
    if session.status == "active":
        team.status = "active"
        team.current_question = 1
        team.question_started_at = now()
    elif session.status == "paused":
        team.status = "paused"
        team.current_question = 1
        team.paused_remaining_seconds = QUESTION_SECONDS
    db.add(team); db.commit(); db.refresh(team)
    return {"team_id": team.id, "team_name": team.team_name, "status": team.status, "session_code": session.session_code}

@app.get("/api/quiz/{team_id}/status")
def quiz_status(team_id: int, db: Session = Depends(get_db)):
    team = get_team(db, team_id)
    return team_payload(db, team)

@app.post("/api/quiz/{team_id}/answer")
def submit_answer(team_id: int, body: AnswerBody, db: Session = Depends(get_db)):
    team = get_team(db, team_id)
    if team.status == "completed":
        raise HTTPException(status_code=409, detail="Quiz already completed.")
    if team.status == "paused" or (team.session and team.session.status == "paused"):
        raise HTTPException(status_code=400, detail="Quiz is currently paused by host.")
    if team.status != "active":
        raise HTTPException(status_code=400, detail="Quiz is not active")
    if not 1 <= body.question_number <= 30:
        raise HTTPException(status_code=422, detail="Invalid question number")
    if body.question_number != team.current_question:
        raise HTTPException(status_code=409, detail="Question state has changed; refresh quiz status")
    selected = body.selected_option.upper()
    if selected not in "ABCD":
        raise HTTPException(status_code=422, detail="Choose A, B, C, or D")
    question_number = team.current_question
    if db.query(Answer).filter_by(team_id=team.id, question_number=question_number).first():
        raise HTTPException(status_code=409, detail="Question already answered")
    response_seconds = elapsed(team)
    question = db.query(Question).filter_by(question_number=question_number).first()
    if response_seconds > QUESTION_SECONDS:
        db.add(Answer(team_id=team.id, question_number=question_number, selected_option=None, response_seconds=QUESTION_SECONDS, score=0))
        complete_or_advance(db, team)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Question already answered")
        raise HTTPException(status_code=409, detail="Time expired")
    correct = selected == question.correct_option
    points = score_answer(correct, response_seconds)
    db.add(Answer(team_id=team.id, question_number=question_number, selected_option=selected, is_correct=correct, response_seconds=response_seconds, score=points))
    team.score += points
    complete_or_advance(db, team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Question already answered")
    return team_payload(db, team)

@app.post("/api/quiz/{team_id}/tab-switch")
def tab_switch(team_id: int, body: TabBody, db: Session = Depends(get_db)):
    activity_type = {"hidden": "TAB_HIDDEN", "visible": "TAB_VISIBLE"}.get(body.event)
    if not activity_type:
        raise HTTPException(status_code=422, detail="Unsupported tab-switch event")
    return record_activity(team_id, ActivityBody(activity_type=activity_type), db)

@app.post("/api/quiz/{team_id}/activity")
def record_activity(team_id: int, body: ActivityBody, db: Session = Depends(get_db)):
    activity_type = body.activity_type.upper()
    if activity_type not in AWAY_ACTIVITY_TYPES | RETURN_ACTIVITY_TYPES | POINT_ACTIVITY_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported quiz activity type")
    team = get_team(db, team_id)
    if team.status != "active":
        return {"recorded": False, "tab_switches": team.tab_switch_count, "total_away_seconds": round(team.total_away_seconds, 1)}
    timestamp = now()
    question = db.query(Question).filter_by(question_number=team.current_question).first()
    if activity_type in AWAY_ACTIVITY_TYPES:
        open_activity = db.query(TabSwitchEvent).filter(
            TabSwitchEvent.team_id == team.id,
            TabSwitchEvent.session_id == team.session_id,
            TabSwitchEvent.activity_type.in_(AWAY_ACTIVITY_TYPES),
            TabSwitchEvent.visible_at.is_(None),
        ).order_by(TabSwitchEvent.id.desc()).first()
        if not open_activity:
            db.add(TabSwitchEvent(session_id=team.session_id, team_id=team.id, question_id=question.id if question else None, question_number=team.current_question, activity_type=activity_type, hidden_at=timestamp, created_at=timestamp))
            team.tab_switch_count += 1
            db.commit()
        return {"recorded": True, "tab_switches": team.tab_switch_count, "total_away_seconds": round(team.total_away_seconds, 1)}
    if activity_type in RETURN_ACTIVITY_TYPES:
        open_activity = db.query(TabSwitchEvent).filter(
            TabSwitchEvent.team_id == team.id,
            TabSwitchEvent.session_id == team.session_id,
            TabSwitchEvent.activity_type.in_(AWAY_ACTIVITY_TYPES),
            TabSwitchEvent.visible_at.is_(None),
        ).order_by(TabSwitchEvent.id.desc()).first()
        if open_activity:
            open_activity.visible_at = timestamp
            open_activity.away_seconds = max(0, (timestamp - as_utc(open_activity.hidden_at)).total_seconds())
            team.total_away_seconds += open_activity.away_seconds
            db.add(TabSwitchEvent(session_id=team.session_id, team_id=team.id, question_id=question.id if question else None, question_number=team.current_question, activity_type="RETURNED_TO_QUIZ", hidden_at=timestamp, created_at=timestamp))
            db.commit()
        return {"recorded": bool(open_activity), "returned": bool(open_activity), "tab_switches": team.tab_switch_count, "total_away_seconds": round(team.total_away_seconds, 1)}
    db.add(TabSwitchEvent(session_id=team.session_id, team_id=team.id, question_id=question.id if question else None, question_number=team.current_question, activity_type=activity_type, hidden_at=timestamp, created_at=timestamp))
    db.commit()
    return {"recorded": True, "tab_switches": team.tab_switch_count, "total_away_seconds": round(team.total_away_seconds, 1)}

@app.websocket("/ws/admin/{session_id}")
async def admin_socket(websocket: WebSocket, session_id: int):
    if not origin_allowed(websocket.headers.get("origin")) or not valid_admin_token(websocket.query_params.get("token", "")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            db = SessionLocal(); session = db.get(QuizSession, session_id)
            if session:
                await websocket.send_json(dashboard_payload(db, session))
            db.close()
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        return

@app.websocket("/ws/quiz/{team_id}")
async def quiz_socket(websocket: WebSocket, team_id: int):
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    try:
        while True:
            db = SessionLocal(); team = db.get(Team, team_id)
            if team:
                await websocket.send_json(team_payload(db, team))
            db.close()
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        return
