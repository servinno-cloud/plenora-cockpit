import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .ai_budget import Usage, reconcile, release, reserve
from .config import Settings
from .models import (
    AnalysisRequest,
    AnalysisRequestStatus,
    Environment,
    Incident,
    IncidentAnalysis,
    Observation,
    Product,
)

PROMPT_VERSION = "operations-analyst.v1"
SYSTEM_INSTRUCTION = """Je bent Operations Analyst voor Plenora. Gebruik uitsluitend de aangeboden
technische feiten. Scheid feiten van hypotheses, benoem onzekerheid en verzin geen root cause.
Adviseer uitsluitend menselijke controles, nooit acties of remediation. Geef geen uitvoerbare
shellcommando's. Leid geen persoonsgegevens af. Antwoord exact volgens het opgegeven JSON-schema."""
SAFE_SIGNALS = {
    "https.reachable", "https.status_code", "https.latency_ms", "health.status_code",
    "tls.days_remaining", "backup.status", "backup.success_age_seconds",
    "backup.checksum_verified", "backup.database_bytes", "backup.media_bytes",
    "host.uptime_seconds", "host.load_1m", "host.load_5m", "host.load_15m",
    "disk.root.used_percent", "disk.root.inodes_used_percent", "db.reachable",
    "db.version_major", "db.latency_ms", "db.size_bytes", "db.connections_percent",
    "db.migration_current", "mail.provider_state", "mail.worker_running", "mail.queue_count",
    "mail.retryable_count", "mail.failed_count", "service.running", "service.health",
    "service.restart_count", "collector.status",
}
SAFE_TEXT_SIGNALS = {"backup.status", "service.health", "mail.provider_state", "collector.status"}
logger = logging.getLogger("cockpit.analysis")


class ContextObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal: str
    state: str
    value: float | str | bool | None
    observed_at: datetime
    source: str
    message_code: str


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: str
    duration_seconds: int
    resolved_at: datetime


class AnalysisContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str
    component: str
    severity: str
    lifecycle: str
    first_seen: datetime
    last_seen: datetime
    fingerprint: str
    message_code: str
    product: str
    environment: str
    observations: list[ContextObservation]
    history: list[HistoryItem]


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=800)
    probable_cause: str = Field(min_length=1, max_length=800)
    evidence: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(max_length=8)
    impact: str = Field(min_length=1, max_length=800)
    recommended_checks: list[
        Annotated[str, Field(min_length=1, max_length=300)]
    ] = Field(max_length=8)
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    limitations: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(max_length=8)


class AnalysisProvider(Protocol):
    name: str
    model: str

    def analyze(self, context: AnalysisContext) -> "ProviderResult": ...


class ProviderResult(BaseModel):
    result: AnalysisResult
    usage: Usage | None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class OpenAIAnalysisProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.analysis_model

    def analyze(self, context: AnalysisContext) -> ProviderResult:
        schema = AnalysisResult.model_json_schema()
        payload = {
            "model": self.model,
            "store": False,
            "instructions": SYSTEM_INSTRUCTION,
            "input": json.dumps(context.model_dump(mode="json"), separators=(",", ":")),
            "max_output_tokens": self.settings.analysis_max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": "incident_analysis",
                                 "strict": True, "schema": schema}},
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.settings.analysis_api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            request, timeout=self.settings.analysis_timeout_seconds
        ) as response:
            result = json.loads(response.read(262_144))
        output_text = result.get("output_text")
        if not isinstance(output_text, str):
            for item in result.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        raw_usage = result.get("usage")
        usage = None
        if raw_usage and all(key in raw_usage for key in (
            "input_tokens", "output_tokens", "total_tokens"
        )):
            details = raw_usage.get("input_tokens_details") or {}
            try:
                values = {
                    "input_tokens": int(raw_usage["input_tokens"]),
                    "output_tokens": int(raw_usage["output_tokens"]),
                    "cached_input_tokens": int(details.get("cached_tokens", 0)),
                    "cache_write_tokens": int(details["cache_write_tokens"]),
                    "total_tokens": int(raw_usage["total_tokens"]),
                }
                if any(value < 0 for value in values.values()) or (
                    values["cached_input_tokens"] + values["cache_write_tokens"]
                    > values["input_tokens"]
                ):
                    raise ValueError("invalid provider usage")
                usage = Usage(**values)
            except (KeyError, TypeError, ValueError):
                usage = None
        return ProviderResult(result=AnalysisResult.model_validate_json(output_text), usage=usage)


def _value(item: Observation):
    if item.numeric_value is not None:
        return (
            float(item.numeric_value)
            if isinstance(item.numeric_value, Decimal)
            else item.numeric_value
        )
    if item.signal in SAFE_TEXT_SIGNALS:
        return item.text_value
    return None


def build_context(db: Session, incident: Incident, settings: Settings) -> AnalysisContext:
    environment = db.get(Environment, incident.environment_id)
    product = db.get(Product, environment.product_id) if environment else None
    observations = list(db.scalars(
        select(Observation).where(
            Observation.environment_id == incident.environment_id,
            Observation.target_id == incident.target_id,
            Observation.signal.in_(SAFE_SIGNALS),
        ).order_by(Observation.observed_at.desc()).limit(settings.analysis_max_observations)
    ))
    history = list(db.scalars(
        select(Incident).where(
            Incident.fingerprint == incident.fingerprint,
            Incident.id != incident.id,
            Incident.resolved_at.is_not(None),
        ).order_by(Incident.resolved_at.desc()).limit(settings.analysis_max_history)
    ))
    return AnalysisContext(
        incident_id=str(incident.id), component=incident.component,
        severity=incident.severity.value,
        lifecycle=incident.lifecycle.value, first_seen=incident.first_seen_at,
        last_seen=incident.last_seen_at, fingerprint=incident.fingerprint,
        message_code=incident.code, product=product.name if product else "Onbekend",
        environment=environment.name if environment else "Onbekend",
        observations=[ContextObservation(signal=item.signal, state=item.state.value,
            value=_value(item), observed_at=item.observed_at, source=item.source,
            message_code=item.code) for item in observations],
        history=[HistoryItem(severity=item.severity.value,
            duration_seconds=max(0, int((item.resolved_at-item.first_seen_at).total_seconds())),
            resolved_at=item.resolved_at) for item in history],
    )


def process_pending(db: Session, settings: Settings, provider: AnalysisProvider | None = None,
                    limit: int = 5) -> int:
    if not settings.analysis_enabled:
        db.execute(update(AnalysisRequest).where(
            AnalysisRequest.status == AnalysisRequestStatus.PENDING
        ).values(status=AnalysisRequestStatus.DISABLED, safe_error_code="provider_disabled"))
        db.commit()
        return 0
    if provider is None and not settings.analysis_api_key:
        db.execute(update(AnalysisRequest).where(
            AnalysisRequest.status == AnalysisRequestStatus.PENDING
        ).values(status=AnalysisRequestStatus.FAILED,
                 safe_error_code="provider_not_configured"))
        db.commit()
        return 0
    analyzer = provider or OpenAIAnalysisProvider(settings)
    requests = list(db.scalars(select(AnalysisRequest)
        .options(selectinload(AnalysisRequest.incident))
        .where(AnalysisRequest.status == AnalysisRequestStatus.PENDING)
        .order_by(AnalysisRequest.created_at).limit(limit).with_for_update(skip_locked=True)))
    completed = 0
    for request in requests:
        context = build_context(db, request.incident, settings)
        input_bound = len(SYSTEM_INSTRUCTION.encode()) + len(context.model_dump_json().encode())
        reservation = reserve(db, request.id, request.incident_id, analyzer.name, analyzer.model,
            input_bound, settings.analysis_max_output_tokens, settings.ai_monthly_budget_eur,
            settings.ai_usd_to_eur_rate)
        if reservation is None:
            request.status = AnalysisRequestStatus.FAILED
            request.safe_error_code = "budget_exhausted" if (
                analyzer.name, analyzer.model) == ("openai", "gpt-5.6-terra") \
                else "pricing_unknown"
            db.commit()
            continue
        if reservation.status != "RESERVED":
            request.status = AnalysisRequestStatus.FAILED
            request.safe_error_code = "usage_already_recorded"
            db.commit()
            continue
        request.attempt_count += 1
        request.last_attempt_at = datetime.now(UTC)
        call_completed = False
        try:
            raw_result = analyzer.analyze(context)
            call_completed = True
            provider_result = ProviderResult.model_validate(raw_result)
            if provider_result.usage is None:
                raise ValueError("provider usage missing")
            result = provider_result.result
        except (ValidationError, ValueError, TypeError, TimeoutError, urllib.error.URLError):
            if call_completed:
                reconcile(db, reservation, None, settings.ai_usd_to_eur_rate)
                request.status = AnalysisRequestStatus.FAILED
                request.safe_error_code = "provider_usage_invalid"
            else:
                release(db, reservation)
                request.safe_error_code = "provider_response_invalid"
                if request.attempt_count >= settings.analysis_max_attempts:
                    request.status = AnalysisRequestStatus.FAILED
            logger.warning("analysis_attempt_failed", extra={"request_id": str(request.id),
                                                              "attempt": request.attempt_count})
        except Exception:
            release(db, reservation)
            request.safe_error_code = "provider_failed"
            if request.attempt_count >= settings.analysis_max_attempts:
                request.status = AnalysisRequestStatus.FAILED
            logger.warning("analysis_attempt_failed", extra={"request_id": str(request.id),
                                                              "attempt": request.attempt_count})
        else:
            reconcile(db, reservation, provider_result.usage, settings.ai_usd_to_eur_rate)
            db.add(IncidentAnalysis(request_id=request.id, incident_id=request.incident_id,
                summary=result.summary, probable_cause=result.probable_cause, impact=result.impact,
                confidence=result.confidence, evidence=result.evidence,
                recommended_checks=result.recommended_checks, limitations=result.limitations,
                provider=analyzer.name, model=analyzer.model, prompt_version=PROMPT_VERSION))
            request.status = AnalysisRequestStatus.COMPLETED
            request.completed_at = datetime.now(UTC)
            request.safe_error_code = None
            completed += 1
        db.commit()
    return completed
