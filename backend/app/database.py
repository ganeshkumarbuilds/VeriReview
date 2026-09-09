import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, Text, DateTime, JSON, String, Boolean
from sqlalchemy import text as sa_text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task = Column(Text, nullable=False)
    owner_email = Column(Text, index=True)
    status = Column(String, default="completed")
    product_spec = Column(Text)
    architecture = Column(Text)
    database_design = Column(Text)
    backend_code = Column(Text)
    frontend_code = Column(Text)
    qa_notes = Column(Text)
    test_report = Column(Text)
    test_passed = Column(Boolean, default=False)
    verification_report = Column(Text)
    requirements_met = Column(Boolean, default=False)
    documentation = Column(Text)
    deployment_config = Column(Text)
    verified_findings = Column(JSON)
    revision_count = Column(Integer, default=0)
    revision_history = Column(JSON)
    phase_state = Column(JSON)
    tech_stack = Column(Text)
    db_url = Column(Text)
    api_keys = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Backfill columns for databases created before these fields existed.
    # create_all() creates missing tables but never alters existing ones.
    for ddl in (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS test_report TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS test_passed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS verification_report TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS requirements_met BOOLEAN DEFAULT FALSE",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_email TEXT",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(sa_text(ddl))
        except Exception as e:
            print(f"[db] migration skipped ({ddl}): {e}")
    # JSON column for paused approval-gate state (SQLAlchemy JSON -> postgres JSON).
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS phase_state JSON"))
    except Exception as e:
        print(f"[db] migration skipped (phase_state): {e}")
    for ddl in (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tech_stack TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS db_url TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS api_keys JSON",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(sa_text(ddl))
        except Exception as e:
            print(f"[db] migration skipped ({ddl}): {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()