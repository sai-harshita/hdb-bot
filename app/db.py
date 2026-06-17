import os

from passlib.context import CryptContext
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

USER = os.getenv("POSTGRES_USER", "hdb")
PWD = os.getenv("POSTGRES_PASSWORD", "hdb")
HOST = os.getenv("POSTGRES_HOST", "postgres")
PORT = os.getenv("POSTGRES_PORT", "5432")
DB = os.getenv("POSTGRES_DB", "hdbbot")

DATABASE_URL = f"postgresql+psycopg2://{USER}:{PWD}@{HOST}:{PORT}/{DB}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)


class ChatLog(Base):
    __tablename__ = "chat_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(64))
    question = Column(Text)
    answer = Column(Text)
    blocked_by = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def hash_password(p: str) -> str:
    return pwd_ctx.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_ctx.verify(p, h)


def init_db() -> None:
    Base.metadata.create_all(engine)
    demo_user = os.getenv("DEMO_USER", "demo")
    demo_pwd = os.getenv("DEMO_PASSWORD", "demo12345")
    with SessionLocal() as s:
        if not s.query(User).filter_by(username=demo_user).first():
            s.add(User(username=demo_user, password_hash=hash_password(demo_pwd)))
            s.commit()
