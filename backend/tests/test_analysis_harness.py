import uuid
from decimal import Decimal

from sqlalchemy import func, select
from test_analysis import FakeProvider, enabled

from app.analysis import process_pending
from app.cli import cleanup_test_analyses, queue_test_analysis
from app.models import (
    AIUsage,
    AnalysisRequest,
    AnalysisRequestStatus,
    AnalysisTrigger,
    Incident,
    IncidentAnalysis,
    NotificationEvent,
    Observation,
)


def test_synthetic_analysis_uses_real_pipeline_once_and_is_isolated(db):
    run_id = uuid.uuid4()
    request_id = queue_test_analysis(run_id)
    assert queue_test_analysis(run_id) == request_id
    provider = FakeProvider()

    assert process_pending(db, enabled(), provider) == 1
    db.expire_all()
    request = db.get(AnalysisRequest, request_id)
    result = db.scalar(select(IncidentAnalysis).where(
        IncidentAnalysis.request_id == request_id
    ))
    usage = db.scalar(select(AIUsage).where(AIUsage.request_id == request_id))

    assert request.is_test is True
    assert request.trigger_event == AnalysisTrigger.TEST
    assert request.incident_id is None
    assert request.status == AnalysisRequestStatus.COMPLETED
    assert result.incident_id is None
    assert result.summary == "De webrespons is vertraagd."
    assert usage.status == "COMPLETED"
    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 100
    assert usage.cache_write_tokens == 50
    assert usage.output_tokens == 100
    assert usage.estimated_cost_eur > 0
    assert len(provider.contexts) == 1
    context = provider.contexts[0]
    assert context.incident_id.startswith("TEST:")
    assert context.component == "Backups" and context.lifecycle == "RESOLVED"
    assert {item.signal for item in context.observations} == {
        "backup.status", "backup.success_age_seconds", "backup.checksum_verified",
        "host.uptime_seconds", "db.reachable", "https.reachable",
    }
    assert process_pending(db, enabled(), provider) == 0
    assert len(provider.contexts) == 1
    assert db.scalar(select(func.count()).select_from(Incident)) == 0
    assert db.scalar(select(func.count()).select_from(Observation)) == 0
    assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 0


def test_synthetic_malformed_output_fails_without_retry(db):
    request_id = queue_test_analysis(uuid.uuid4())
    provider = FakeProvider(result={"summary": "incomplete"})

    assert process_pending(db, enabled(), provider) == 0
    db.expire_all()
    request = db.get(AnalysisRequest, request_id)
    assert request.status == AnalysisRequestStatus.FAILED
    assert request.safe_error_code == "provider_response_schema_invalid"
    assert len(provider.contexts) == 1
    assert process_pending(db, enabled(), provider) == 0
    assert len(provider.contexts) == 1
    assert db.scalar(select(func.count()).select_from(IncidentAnalysis)) == 0


def test_synthetic_budget_exhaustion_prevents_provider_call(db):
    request_id = queue_test_analysis(uuid.uuid4())
    provider = FakeProvider()

    assert process_pending(
        db, enabled(ai_monthly_budget_eur=Decimal("0.000001")), provider
    ) == 0
    db.expire_all()
    request = db.get(AnalysisRequest, request_id)
    assert request.status == AnalysisRequestStatus.FAILED
    assert request.safe_error_code == "budget_exhausted"
    assert provider.contexts == []
    assert db.scalar(select(func.count()).select_from(AIUsage)) == 0


def test_cleanup_removes_test_result_but_preserves_usage_accounting(db):
    request_id = queue_test_analysis(uuid.uuid4())
    assert process_pending(db, enabled(), FakeProvider()) == 1
    usage_id = db.scalar(select(AIUsage.id).where(AIUsage.request_id == request_id))

    cleanup_test_analyses()
    db.expire_all()
    assert db.scalar(select(IncidentAnalysis).where(
        IncidentAnalysis.request_id == request_id
    )) is None
    assert db.get(AIUsage, usage_id) is not None
    request = db.get(AnalysisRequest, request_id)
    assert request.test_context is None
