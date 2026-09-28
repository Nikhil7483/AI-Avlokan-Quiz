from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now():
    return datetime.now(timezone.utc)

class QuizSession(Base):
    __tablename__ = "quiz_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    teams = relationship("Team", back_populates="session", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_number: Mapped[int] = mapped_column(Integer, unique=True)
    question_text: Mapped[str] = mapped_column(Text)
    option_a: Mapped[str] = mapped_column(String(300))
    option_b: Mapped[str] = mapped_column(String(300))
    option_c: Mapped[str] = mapped_column(String(300))
    option_d: Mapped[str] = mapped_column(String(300))
    correct_option: Mapped[str] = mapped_column(String(1))
    challenge: Mapped[bool] = mapped_column(Boolean, default=False)

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id"))
    team_name: Mapped[str] = mapped_column(String(100))
    score: Mapped[int] = mapped_column(default=0)
    current_question: Mapped[int] = mapped_column(default=1)
    tab_switch_count: Mapped[int] = mapped_column(default=0)
    total_away_seconds: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_remaining_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    session = relationship("QuizSession", back_populates="teams")
    answers = relationship("Answer", back_populates="team", cascade="all, delete-orphan")
    tab_events = relationship("TabSwitchEvent", back_populates="team", cascade="all, delete-orphan")

class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("team_id", "question_number", name="uq_answer_team_question"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    question_number: Mapped[int] = mapped_column(Integer)
    selected_option: Mapped[str | None] = mapped_column(String(1))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    response_seconds: Mapped[float] = mapped_column(Float)
    score: Mapped[int] = mapped_column(default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    team = relationship("Team", back_populates="answers")

class TabSwitchEvent(Base):
    __tablename__ = "tab_switch_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_sessions.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    question_number: Mapped[int] = mapped_column(Integer, default=1)
    activity_type: Mapped[str] = mapped_column(String(32), default="TAB_HIDDEN", index=True)
    hidden_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    visible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    away_seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    team = relationship("Team", back_populates="tab_events")
