import os
import secrets
from urllib.parse import urlparse

import yt_dlp
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from starlette.middleware.sessions import SessionMiddleware

APP_VERSION = "1.0.0"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jr_audio.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_args = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class AppControl(Base):
    __tablename__ = "app_control"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    maintenance_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    maintenance_message: Mapped[str] = mapped_column(String(500), default="JR Audio está en mantenimiento.")
    maintenance_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    update_available: Mapped[bool] = mapped_column(Boolean, default=False)
    update_version: Mapped[str] = mapped_column(String(40), default="")
    update_url: Mapped[str] = mapped_column(String(1000), default="")
    update_notes: Mapped[str] = mapped_column(Text, default="")
    update_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    preparing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preparing_version: Mapped[str] = mapped_column(String(40), default="")
    preparing_message: Mapped[str] = mapped_column(String(500), default="Estamos preparando una nueva versión.")
    preparing_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow():
    return datetime.now(timezone.utc)


def active(flag: bool, until: Optional[datetime]) -> bool:
    if not flag:
        return False
    if until is None:
        return True
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > utcnow()


def get_control(db: Session) -> AppControl:
    item = db.get(AppControl, 1)
    if item is None:
        item = AppControl(id=1)
        db.add(item)
        db.commit()
        db.refresh(item)
    return item


class StatusPatch(BaseModel):
    maintenance_enabled: Optional[bool] = None
    maintenance_message: Optional[str] = Field(default=None, max_length=500)
    maintenance_until: Optional[datetime] = None
    update_available: Optional[bool] = None
    update_version: Optional[str] = Field(default=None, max_length=40)
    update_url: Optional[str] = Field(default=None, max_length=1000)
    update_notes: Optional[str] = Field(default=None, max_length=5000)
    update_until: Optional[datetime] = None
    preparing_enabled: Optional[bool] = None
    preparing_version: Optional[str] = Field(default=None, max_length=40)
    preparing_message: Optional[str] = Field(default=None, max_length=500)
    preparing_until: Optional[datetime] = None


app = FastAPI(title="JR Audio Control API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "local-only-change-this-secret"),
    session_cookie="jr_admin_session",
    same_site="strict",
    https_only=os.getenv("APP_ENV") == "production",
    max_age=60 * 60 * 8,
)


def require_admin(request: Request):
    if request.session.get("admin") is not True:
        raise HTTPException(status_code=401, detail="No autorizado")
    return True


def require_csrf(request: Request):
    sent = request.headers.get("X-CSRF-Token", "")
    expected = request.session.get("csrf", "")
    if not sent or not expected or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")
    return True



ONLINE_SOURCE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "soundcloud.com", "www.soundcloud.com",
    "vimeo.com", "www.vimeo.com",
    "tiktok.com", "www.tiktok.com",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "fb.watch",
}


def validate_media_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or not any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ONLINE_SOURCE_HOSTS
    ):
        raise HTTPException(status_code=400, detail="Fuente no admitida. Usa un enlace HTTPS público de una plataforma compatible.")
    return value


@app.get("/api/v1/search")
def search_music(q: str):
    query = q.strip()
    if len(query) < 2 or len(query) > 120:
        raise HTTPException(status_code=422, detail="Escribe entre 2 y 120 caracteres.")
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "noplaylist": True, "socket_timeout": 12}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info("ytsearch8:" + query, download=False)
        entries = []
        for item in (data or {}).get("entries") or []:
            if not item:
                continue
            webpage = item.get("webpage_url") or item.get("url") or ""
            if not webpage.startswith("https://"):
                continue
            entries.append({
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "Sin título")[:240],
                "artist": str(item.get("uploader") or item.get("channel") or "Artista desconocido")[:160],
                "duration": item.get("duration"),
                "thumbnail": item.get("thumbnail"),
                "url": webpage,
                "source": str(item.get("extractor_key") or "Online")
            })
        return {"query": query, "count": len(entries), "results": entries}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo buscar ahora. La fuente puede estar temporalmente limitada.") from exc


@app.get("/api/v1/resolve")
def resolve_music(url: str):
    media_url = validate_media_url(url)
    options = {"format": "bestaudio/best", "quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(media_url, download=False)
        if not info or not info.get("url"):
            raise HTTPException(status_code=502, detail="La fuente no entregó un flujo de audio reproducible.")
        return {
            "url": info["url"],
            "title": str(info.get("title") or "Audio")[:240],
            "artist": str(info.get("artist") or info.get("uploader") or info.get("channel") or "")[:160],
            "duration": info.get("duration"),
            "source": str(info.get("extractor_key") or "Online")
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo preparar la reproducción. Puede que el contenido no esté disponible.") from exc


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "jr-audio-control", "version": APP_VERSION}


@app.get("/api/v1/app-status")
def public_status(db: Session = Depends(get_db)):
    c = get_control(db)
    maintenance = active(c.maintenance_enabled, c.maintenance_until)
    update = active(c.update_available, c.update_until)
    preparing = active(c.preparing_enabled, c.preparing_until)
    return {
        "app": "JR Audio",
        "api_version": 1,
        "server_time": utcnow().isoformat(),
        "maintenance": {
            "enabled": maintenance,
            "mode": "local",
            "message": c.maintenance_message if maintenance else "",
            "until": c.maintenance_until.isoformat() if c.maintenance_until else None,
            "online_features_disabled": maintenance
        },
        "update": {
            "available": update,
            "version": c.update_version if update else "",
            "url": c.update_url if update else "",
            "notes": c.update_notes if update else "",
            "until": c.update_until.isoformat() if c.update_until else None
        },
        "preparing": {
            "enabled": preparing,
            "version": c.preparing_version if preparing else "",
            "message": c.preparing_message if preparing else "",
            "until": c.preparing_until.isoformat() if c.preparing_until else None
        },
        "updated_at": c.updated_at.isoformat() if c.updated_at else None
    }


@app.get("/api/admin/csrf")
def csrf_token(request: Request):
    token = secrets.token_urlsafe(32)
    request.session["csrf"] = token
    return {"csrf_token": token}


@app.get("/api/admin/session")
def admin_session(request: Request):
    return {"authenticated": request.session.get("admin") is True}


@app.post("/api/admin/login")
async def login(request: Request, _: bool = Depends(require_csrf)):
    body = await request.json()
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_pass = os.getenv("ADMIN_PASSWORD", "")
    if not expected_pass:
        raise HTTPException(status_code=503, detail="Configura ADMIN_PASSWORD en Render.")
    if not secrets.compare_digest(username, expected_user) or not secrets.compare_digest(password, expected_pass):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    request.session.clear()
    request.session["admin"] = True
    request.session["csrf"] = secrets.token_urlsafe(32)
    return {"ok": True, "csrf_token": request.session["csrf"]}


@app.post("/api/admin/logout")
def logout(request: Request, _: bool = Depends(require_admin), __: bool = Depends(require_csrf)):
    request.session.clear()
    return {"ok": True}


@app.get("/api/admin/status")
def admin_status(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_control(db)
    return {k: getattr(c, k) for k in [
        "maintenance_enabled", "maintenance_message", "maintenance_until",
        "update_available", "update_version", "update_url", "update_notes", "update_until",
        "preparing_enabled", "preparing_version", "preparing_message", "preparing_until",
        "updated_at"
    ]}


@app.patch("/api/admin/status")
def patch_status(payload: StatusPatch, _: bool = Depends(require_admin), __: bool = Depends(require_csrf), db: Session = Depends(get_db)):
    c = get_control(db)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        if key in ("update_url",) and value:
            if not str(value).startswith("https://"):
                raise HTTPException(status_code=422, detail="La URL de actualización debe usar HTTPS.")
        if key.endswith("_until") and value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        setattr(c, key, value)
    c.updated_at = utcnow()
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "updated_at": c.updated_at.isoformat()}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with open("static/admin.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/favicon.ico")
def favicon():
    return JSONResponse({}, status_code=204)
