import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    clear_rate_limit,
    current_operator,
    current_session,
    digest,
    ip_prefix,
    issue_csrf,
    rate_limited,
    require_csrf,
    subject_digest,
    verify_password,
)
from .config import Settings, get_settings
from .database import get_db
from .logging import configure_logging
from .models import (
    AuditEvent,
    Environment,
    Incident,
    Observation,
    Operator,
    OperatorSession,
    Product,
)

configure_logging()
logger = logging.getLogger("cockpit.api")
settings = get_settings()
app = FastAPI(title="Plenora Operations Cockpit", version="0.1.0", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:64]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("unhandled_request", extra={"request_id": request.state.request_id})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class OperatorPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str


def audit(
    db: Session,
    request: Request,
    action: str,
    success: bool,
    operator: Operator | None = None,
    subject_hash: str | None = None,
    detail_code: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            operator_id=operator.id if operator else None,
            action=action,
            success=success,
            subject_hash=subject_hash,
            request_id=request.state.request_id,
            source_ip_prefix=ip_prefix(request),
            detail_code=detail_code,
        )
    )


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "down"})
    return {"status": "healthy", "database": "up"}


@app.get("/api/auth/csrf")
def csrf(response: Response, settings: Settings = Depends(get_settings)):
    token = issue_csrf(settings)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
        max_age=3600,
        path="/",
    )
    return {"csrf_token": token}


@app.post("/api/auth/login", dependencies=[Depends(require_csrf)])
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = body.email.casefold()
    subject = subject_digest(email, settings)
    key = subject_digest(f"{email}|{ip_prefix(request)}", settings)
    if rate_limited(key, settings):
        audit(db, request, "auth.login", False, subject_hash=subject, detail_code="rate_limited")
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Try again later")
    operator = db.scalar(select(Operator).where(Operator.email == email, Operator.active.is_(True)))
    if not operator or not verify_password(operator.password_hash, body.password):
        audit(
            db,
            request,
            "auth.login",
            False,
            subject_hash=subject,
            detail_code="invalid_credentials",
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    clear_rate_limit(key)
    raw_session = secrets.token_urlsafe(32)
    csrf_token = request.cookies[CSRF_COOKIE]
    db.add(
        OperatorSession(
            operator_id=operator.id,
            token_hash=digest(raw_session),
            csrf_hash=digest(csrf_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    audit(db, request, "auth.login", True, operator=operator)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    return {"operator": OperatorPayload.model_validate(operator)}


@app.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    session: OperatorSession = Depends(current_session),
    db: Session = Depends(get_db),
):
    if session.csrf_hash != digest(request.cookies.get(CSRF_COOKIE, "")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
    session.revoked_at = datetime.now(UTC)
    audit(db, request, "auth.logout", True, operator=session.operator)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


@app.get("/api/me", response_model=OperatorPayload)
def me(operator: Operator = Depends(current_operator)):
    return operator


@app.get("/api/products")
def products(_: Operator = Depends(current_operator), db: Session = Depends(get_db)):
    return [
        {"id": item.id, "code": item.code, "name": item.name}
        for item in db.scalars(select(Product).order_by(Product.name))
    ]


@app.get("/api/environments")
def environments(_: Operator = Depends(current_operator), db: Session = Depends(get_db)):
    query = (
        select(Environment).options(selectinload(Environment.product)).order_by(Environment.name)
    )
    return [
        {"id": item.id, "code": item.code, "name": item.name, "product_id": item.product_id}
        for item in db.scalars(query)
    ]


@app.get("/api/environments/{environment_id}/snapshot")
def snapshot(
    environment_id: uuid.UUID,
    _: Operator = Depends(current_operator),
    db: Session = Depends(get_db),
):
    environment = db.get(Environment, environment_id)
    if not environment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    observations = list(
        db.scalars(
            select(Observation)
            .where(Observation.environment_id == environment_id)
            .order_by(Observation.observed_at.desc())
            .limit(100)
        )
    )
    return {
        "environment_id": environment.id,
        "overall_state": "UNKNOWN" if not observations else observations[0].state.value,
        "observed_at": observations[0].observed_at if observations else None,
        "observations": [
            {
                "id": item.id,
                "target_id": item.target_id,
                "component": item.component,
                "code": item.code,
                "state": item.state.value,
                "observed_at": item.observed_at,
                "numeric_value": item.numeric_value,
                "unit": item.unit,
                "message": item.message,
                "source": item.source,
            }
            for item in observations
        ],
    }


@app.get("/api/incidents")
def incidents(_: Operator = Depends(current_operator), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "environment_id": item.environment_id,
            "target_id": item.target_id,
            "fingerprint": item.fingerprint,
            "component": item.component,
            "code": item.code,
            "title": item.title,
            "severity": item.severity.value,
            "lifecycle": item.lifecycle.value,
            "source": item.source,
            "first_seen_at": item.first_seen_at,
            "last_seen_at": item.last_seen_at,
            "resolved_at": item.resolved_at,
        }
        for item in db.scalars(select(Incident).order_by(Incident.last_seen_at.desc()).limit(100))
    ]
