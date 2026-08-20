import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from test_foundation import login, owner
from test_monitoring import payload, post, setup_monitoring

from app.ai_budget import PRICING_USD, Usage, budget_level, cost_eur, month_key, summary
from app.analysis import (
    AnalysisContext,
    AnalysisResult,
    OpenAIAnalysisProvider,
    ProviderResult,
    build_context,
    process_pending,
)
from app.config import get_settings
from app.models import (
    AIUsage,
    AnalysisRequest,
    AnalysisRequestStatus,
    Incident,
    IncidentAnalysis,
    Observation,
)


class FakeProvider:
    name = "openai"
    model = "gpt-5.6-terra"

    def __init__(self, result=None, error=None):
        self.result = result or AnalysisResult(
            summary="De webrespons is vertraagd.",
            probable_cause="Verhoogde endpointlatency is een waarschijnlijke verklaring.",
            evidence=["https.latency_ms overschrijdt de warninggrens."],
            impact="Gebruikers kunnen tragere responses ervaren.",
            recommended_checks=["Controleer de technische latencytrend."],
            confidence="MEDIUM",
            limitations=["Geen applicatielogs beschikbaar."],
        )
        self.error = error
        self.contexts = []

    def analyze(self, context):
        self.contexts.append(context)
        if self.error:
            raise self.error
        if isinstance(self.result, AnalysisResult):
            return ProviderResult(result=self.result,
                usage=Usage(1000, 100, 100, 50, 1100))
        return self.result


def enabled(**updates):
    values = {"analysis_enabled": True, "analysis_provider": "openai",
              "analysis_model": "test-model", "analysis_api_key": "test-key",
              "analysis_max_attempts": 2}
    values.update(updates)
    return get_settings().model_copy(update=values)


def open_incident(client, db):
    environment, collector = setup_monitoring(db)
    first = payload(environment, collector, 1, 600, signal="https.latency_ms")
    assert post(client, environment, first).status_code == 202
    assert db.scalar(select(func.count()).select_from(AnalysisRequest)) == 0
    assert post(client, environment, payload(environment, collector, 2, 600,
        signal="https.latency_ms")).status_code == 202
    return environment, collector, db.scalar(select(Incident))


def test_analysis_requests_follow_only_open_and_escalation(client, db):
    environment, collector, incident = open_incident(client, db)
    assert incident is not None
    assert db.scalar(select(func.count()).select_from(AnalysisRequest)) == 1
    for sequence in (3, 4):
        post(client, environment, payload(environment, collector, sequence, 600,
             signal="https.latency_ms"))
    assert db.scalar(select(func.count()).select_from(AnalysisRequest)) == 1
    post(client, environment, payload(environment, collector, 5, 2501,
         signal="https.latency_ms"))
    post(client, environment, payload(environment, collector, 6, 2501,
         signal="https.latency_ms"))
    requests = list(db.scalars(select(AnalysisRequest)))
    assert len(requests) == 2
    assert len({item.deduplication_key for item in requests}) == 2


def test_provider_success_stores_only_validated_analysis(client, db):
    environment, collector, incident = open_incident(client, db)
    provider = FakeProvider()
    assert process_pending(db, enabled(), provider) == 1
    analysis = db.scalar(select(IncidentAnalysis))
    request = db.scalar(select(AnalysisRequest))
    assert analysis.incident_id == incident.id
    assert analysis.summary == "De webrespons is vertraagd."
    assert analysis.provider == "openai" and analysis.model == "gpt-5.6-terra"
    assert request.status == AnalysisRequestStatus.COMPLETED
    assert provider.contexts[0].incident_id == str(incident.id)
    # A restarted worker sees no pending work and cannot duplicate the result.
    assert process_pending(db, enabled(), provider) == 0
    assert len(provider.contexts) == 1
    assert db.scalar(select(func.count()).select_from(IncidentAnalysis)) == 1
    usage = db.scalar(select(AIUsage))
    assert usage.status == "COMPLETED" and usage.total_tokens == 1100
    assert usage.cache_write_tokens == 50
    assert str(usage.estimated_cost_eur) == "0.0030450000"
    usage_summary = summary(db, enabled().ai_monthly_budget_eur, True, True)
    assert usage_summary["agents"] == [
        {"agent_key": "operations_analyst", "calls": 1, "spent_eur": "0.00"}
    ]
    assert client.get(f"/api/incidents/{incident.id}").status_code == 401
    owner(db)
    assert login(client).status_code == 200
    exposed = client.get(f"/api/incidents/{incident.id}").json()["analysis"]
    assert exposed["status"] == "available" and exposed["confidence"] == "MEDIUM"
    assert "provider" not in exposed and "model" not in exposed
    for sequence in (3, 4):
        healthy = payload(
            environment, collector, sequence, 100, signal="https.latency_ms"
        )
        assert post(client, environment, healthy).status_code == 202
    db.expire_all()
    assert db.get(Incident, incident.id).lifecycle.value == "RESOLVED"
    retained = client.get(f"/api/incidents/{incident.id}").json()["analysis"]
    assert retained["status"] == "available"


def test_malformed_and_timeout_are_bounded_and_do_not_store(client, db):
    open_incident(client, db)
    malformed = FakeProvider(result={"summary": "onvolledig"})
    assert process_pending(db, enabled(), malformed) == 0
    assert db.scalar(select(func.count()).select_from(IncidentAnalysis)) == 0
    request = db.scalar(select(AnalysisRequest))
    assert request.status == AnalysisRequestStatus.FAILED and request.attempt_count == 1
    assert request.safe_error_code == "provider_usage_invalid"
    db.delete(db.scalar(select(AIUsage)))
    request.status = AnalysisRequestStatus.PENDING
    db.commit()
    timeout = FakeProvider(error=TimeoutError())
    assert process_pending(db, enabled(), timeout) == 0
    assert request.status == AnalysisRequestStatus.FAILED and request.attempt_count == 2
    assert db.scalar(select(func.count()).select_from(Incident)) == 1


def test_disabled_provider_preserves_incident_and_marks_request(client, db):
    open_incident(client, db)
    assert process_pending(db, get_settings().model_copy(update={"analysis_enabled": False})) == 0
    request = db.scalar(select(AnalysisRequest))
    assert request.status == AnalysisRequestStatus.DISABLED
    assert db.scalar(select(func.count()).select_from(Incident)) == 1
    assert db.scalar(select(func.count()).select_from(AIUsage)) == 0


def test_context_is_allowlisted_and_bounded(client, db):
    _, _, incident = open_incident(client, db)
    safe = db.scalar(select(Observation).limit(1))
    for index in range(8):
        db.add(Observation(snapshot_id=None, environment_id=incident.environment_id,
            target_id=incident.target_id, component=incident.component,
            signal="https.latency_ms", code="web_unhealthy", state=safe.state,
            observed_at=datetime.now(UTC), numeric_value=600+index, text_value=None,
            unit="ms", message="safe", source="external_https"))
    db.add(Observation(snapshot_id=None, environment_id=incident.environment_id,
        target_id=incident.target_id, component=incident.component,
        signal="private.employee.email", code="private", state=safe.state,
        observed_at=datetime.now(UTC), numeric_value=None, text_value="secret@example.test",
        unit=None, message="private", source="external_https"))
    db.commit()
    context = build_context(db, incident, enabled(analysis_max_observations=3))
    assert len(context.observations) == 3
    assert all(item.signal == "https.latency_ms" for item in context.observations)
    serialized = context.model_dump_json()
    assert "secret@example.test" not in serialized and "private.employee" not in serialized


def test_openai_request_is_stateless_bounded_and_has_no_tools(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, limit):
            assert limit == 262_144
            result = FakeProvider().result.model_dump_json()
            details = captured.get("usage_details", {
                "cached_tokens": 100, "cache_write_tokens": 50
            })
            return json.dumps({"output": [{"content": [
                {"type": "output_text", "text": result}
            ]}], "usage": {"input_tokens": 1000, "output_tokens": 100,
                "total_tokens": 1100, "input_tokens_details": details}}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.analysis.urllib.request.urlopen", fake_urlopen)
    settings = enabled(analysis_max_output_tokens=700, analysis_timeout_seconds=17)
    context = AnalysisContext(
        incident_id="incident", component="web", severity="WARNING", lifecycle="OPEN",
        first_seen=datetime.now(UTC), last_seen=datetime.now(UTC), fingerprint="fingerprint",
        message_code="web_slow", product="Plenora", environment="production",
        observations=[], history=[],
    )
    provider_result = OpenAIAnalysisProvider(settings).analyze(context)
    request = captured["payload"]
    assert request["store"] is False
    assert request["max_output_tokens"] == 700 and captured["timeout"] == 17
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert "tools" not in request and "tool_choice" not in request
    assert provider_result.usage.cache_write_tokens == 50
    captured["usage_details"] = {"cached_tokens": 100}
    assert OpenAIAnalysisProvider(settings).analyze(context).usage is None


def test_missing_cache_write_usage_consumes_reservation_fail_safe(client, db):
    open_incident(client, db)

    class MissingUsageProvider(FakeProvider):
        def analyze(self, context):
            self.contexts.append(context)
            return ProviderResult(result=self.result, usage=None)

    assert process_pending(db, enabled(), MissingUsageProvider()) == 0
    usage = db.scalar(select(AIUsage))
    request = db.scalar(select(AnalysisRequest))
    assert usage.status == "UNKNOWN" and usage.estimated_cost_eur is None
    assert request.safe_error_code == "provider_usage_invalid"


def test_budget_exhaustion_blocks_provider_without_affecting_incident(client, db):
    _, _, incident = open_incident(client, db)
    provider = FakeProvider()
    # This cap would admit input at $2/M, but not the conservative $2.50/M
    # cache-write reservation plus maximum output.
    settings = enabled(ai_monthly_budget_eur=Decimal("0.012"))
    assert process_pending(db, settings, provider) == 0
    request = db.scalar(select(AnalysisRequest))
    assert request.safe_error_code == "budget_exhausted"
    assert provider.contexts == []
    assert db.get(Incident, incident.id) is not None


def test_decimal_pricing_and_disabled_status(db):
    rate = get_settings().ai_usd_to_eur_rate
    assert PRICING_USD[("openai", "gpt-5.6-terra")]["cache_write"] == Decimal("2.50")
    exact = cost_eur("openai", "gpt-5.6-terra", Usage(1000, 100, 100, 50, 1100), rate)
    assert str(exact) == "0.0030450000"
    conservative = cost_eur(
        "openai", "gpt-5.6-terra", Usage(1000, 100, 0, 1000, 1100), rate
    )
    assert conservative == Decimal("0.0037000000")
    assert cost_eur("openai", "unknown", Usage(1, 1, 0, 0, 2), rate) is None
    result = summary(db, get_settings().ai_monthly_budget_eur, False, True)
    assert result["status"] == "disabled"
    assert [budget_level(value) for value in map(Decimal, ("49", "50", "75", "90", "100"))] == [
        ("normal", None), ("warning", 50), ("warning", 75),
        ("critical", 90), ("exhausted", 100),
    ]
    assert month_key(datetime(2026, 8, 31, tzinfo=UTC)) == "2026-08"
    assert month_key(datetime(2026, 9, 1, tzinfo=UTC)) == "2026-09"
