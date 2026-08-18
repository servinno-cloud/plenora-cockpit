import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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
from .health_semantics import aggregate_health
from .ingest import router as ingest_router
from .logging import configure_logging
from .models import (
    AuditEvent,
    Collector,
    Environment,
    Incident,
    Observation,
    Operator,
    OperatorSession,
    Product,
    Target,
)

configure_logging()
logger = logging.getLogger("cockpit.api")
settings = get_settings()
app = FastAPI(title="Plenora Operations Cockpit", version="0.1.0", docs_url=None, redoc_url=None)
app.include_router(ingest_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )


@app.exception_handler(RequestValidationError)
async def safe_ingest_validation_error(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith("/ingest/v1/"):
        return await request_validation_exception_handler(request, exc)
    locations = [tuple(error.get("loc", ())) for error in exc.errors()]
    field = next((str(location[-1]) for location in locations if location), "")
    codes = {
        "collector_version": "snapshot_invalid.collector_version",
        "signal": "snapshot_invalid.observation_signal",
        "value": "snapshot_invalid.text_value",
        "code": "snapshot_invalid.message_code",
        "source": "snapshot_invalid.source",
        "target": "snapshot_invalid.target",
    }
    return JSONResponse(
        status_code=422,
        content={"error_code": codes.get(field, "snapshot_invalid.field_type")},
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
    return {"status": "healthy", "database": "up", "release": settings.release}


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
        {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "product_id": item.product_id,
            "product_name": item.product.name,
        }
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
    collectors = list(
        db.scalars(select(Collector).where(Collector.environment_id == environment_id))
    )
    collector = max(
        collectors,
        key=lambda item: item.last_seen_at.timestamp() if item.last_seen_at else 0,
        default=None,
    )
    observations = list(
        db.scalars(
            select(Observation)
            .where(Observation.environment_id == environment_id)
            .order_by(Observation.observed_at.desc())
            .limit(100)
        )
    )
    targets = {
        item.id: item.key
        for item in db.scalars(select(Target).where(Target.environment_id == environment_id))
    }
    latest = {}
    for item in observations:
        latest.setdefault((item.target_id, item.signal), item)
    current = list(latest.values())
    now = datetime.now(UTC)
    stale = {
        item.id: now
        - (
            item.observed_at.replace(tzinfo=UTC)
            if item.observed_at.tzinfo is None
            else item.observed_at
        )
        > timedelta(minutes=5)
        for item in current
    }
    component_states, service_states, overall = aggregate_health(current, stale, targets)
    product = db.get(Product, environment.product_id)
    return {
        "environment_id": environment.id,
        "environment": {
            "code": environment.code,
            "name": environment.name,
            "product": {"id": product.id, "name": product.name} if product else None,
        },
        "overall_state": overall,
        "component_states": component_states,
        "service_states": service_states,
        "data_mode": settings.infrastructure_mode,
        "collector": {
            "status": "UNKNOWN" if not collector or not collector.last_seen_at else "ONLINE",
            "sequence": collector.last_sequence if collector else None,
            "last_snapshot_age_seconds": (
                int(
                    (
                        now
                        - (
                            collector.last_seen_at.replace(tzinfo=UTC)
                            if collector.last_seen_at.tzinfo is None
                            else collector.last_seen_at
                        )
                    ).total_seconds()
                )
                if collector and collector.last_seen_at
                else None
            ),
            "identities": len(collectors),
        },
        "observed_at": observations[0].observed_at if observations else None,
        "observations": [
            {
                "id": item.id,
                "target_id": item.target_id,
                "target": targets.get(item.target_id),
                "component": item.component,
                "signal": item.signal,
                "code": item.code,
                "state": item.state.value,
                "observed_at": item.observed_at,
                "numeric_value": item.numeric_value,
                "text_value": item.text_value,
                "unit": item.unit,
                "message": item.message,
                "source": item.source,
                "stale": stale[item.id],
            }
            for item in current
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


@app.get("/api/environments/{environment_id}/observations")
def observation_history(
    environment_id: uuid.UUID,
    _: Operator = Depends(current_operator),
    db: Session = Depends(get_db),
):
    if not db.get(Environment, environment_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    items = db.scalars(
        select(Observation)
        .where(Observation.environment_id == environment_id)
        .order_by(Observation.observed_at.desc())
        .limit(500)
    )
    targets = {
        item.id: item.key
        for item in db.scalars(select(Target).where(Target.environment_id == environment_id))
    }
    return [
        {
            "id": item.id,
            "target_id": item.target_id,
            "target": targets.get(item.target_id),
            "component": item.component,
            "signal": item.signal,
            "code": item.code,
            "state": item.state.value,
            "observed_at": item.observed_at,
            "numeric_value": item.numeric_value,
            "text_value": item.text_value,
            "unit": item.unit,
            "message": item.message,
            "source": item.source,
        }
        for item in items
    ]
