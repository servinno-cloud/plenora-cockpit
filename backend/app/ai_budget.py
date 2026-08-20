from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AIMonthlyBudget, AIUsage

AGENT_KEY = "operations_analyst"
PRICING_VERSION = "openai-2026-08-20.v2"
MILLION = Decimal("1000000")
PRICING_USD = {
    ("openai", "gpt-5.6-terra"): {
        "input": Decimal("2.00"),
        "cached_input": Decimal("0.20"),
        "cache_write": Decimal("2.50"),
        "output": Decimal("12.00"),
    }
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    total_tokens: int


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def budget_level(percent: Decimal) -> tuple[str, int | None]:
    if percent >= 100:
        return "exhausted", 100
    if percent >= 90:
        return "critical", 90
    if percent >= 75:
        return "warning", 75
    if percent >= 50:
        return "warning", 50
    return "normal", None


def cost_eur(provider: str, model: str, usage: Usage, rate: Decimal) -> Decimal | None:
    price = PRICING_USD.get((provider, model))
    if not price:
        return None
    regular = max(
        0,
        usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens,
    )
    usd = (Decimal(regular) * price["input"] +
           Decimal(usage.cached_input_tokens) * price["cached_input"] +
           Decimal(usage.cache_write_tokens) * price["cache_write"] +
           Decimal(usage.output_tokens) * price["output"]) / MILLION
    return (usd * rate).quantize(Decimal("0.0000000001"))


def reserve(db: Session, request_id, incident_id, provider: str, model: str,
            input_upper_bound: int, output_upper_bound: int, budget: Decimal,
            rate: Decimal) -> AIUsage | None:
    if (provider, model) not in PRICING_USD:
        return None
    existing = db.scalar(select(AIUsage).where(AIUsage.request_id == request_id))
    if existing:
        return existing
    maximum = cost_eur(provider, model,
        Usage(input_upper_bound, output_upper_bound, 0, input_upper_bound,
              input_upper_bound + output_upper_bound), rate)
    key = month_key()
    monthly = db.scalar(select(AIMonthlyBudget).where(
        AIMonthlyBudget.month == key).with_for_update())
    if monthly is None:
        monthly = AIMonthlyBudget(month=key, spent_eur=Decimal("0"), reserved_eur=Decimal("0"))
        db.add(monthly)
        db.flush()
    if monthly.spent_eur + monthly.reserved_eur + maximum > budget:
        return None
    monthly.reserved_eur += maximum
    usage = AIUsage(agent_key=AGENT_KEY, provider=provider, model=model,
        request_id=request_id, incident_id=incident_id, reserved_cost_eur=maximum,
        pricing_version=PRICING_VERSION, status="RESERVED")
    db.add(usage)
    db.commit()
    return usage


def reconcile(db: Session, record: AIUsage, usage: Usage | None, rate: Decimal,
              status: str = "COMPLETED") -> None:
    monthly = db.scalar(select(AIMonthlyBudget).where(
        AIMonthlyBudget.month == month_key(record.occurred_at)).with_for_update())
    if record.status != "RESERVED":
        return
    monthly.reserved_eur -= record.reserved_cost_eur
    if usage is None:
        record.status = "UNKNOWN"
        monthly.spent_eur += record.reserved_cost_eur
        db.commit()
        return
    actual = cost_eur(record.provider, record.model, usage, rate)
    record.input_tokens = usage.input_tokens
    record.output_tokens = usage.output_tokens
    record.cached_input_tokens = usage.cached_input_tokens
    record.cache_write_tokens = usage.cache_write_tokens
    record.total_tokens = usage.total_tokens
    record.estimated_cost_eur = actual
    record.status = status if actual is not None else "UNKNOWN"
    monthly.spent_eur += actual if actual is not None else record.reserved_cost_eur
    db.commit()


def release(db: Session, record: AIUsage) -> None:
    if record.status != "RESERVED":
        return
    monthly = db.scalar(select(AIMonthlyBudget).where(
        AIMonthlyBudget.month == month_key(record.occurred_at)).with_for_update())
    monthly.reserved_eur -= record.reserved_cost_eur
    db.delete(record)
    db.commit()


def summary(db: Session, budget: Decimal, enabled: bool, configured: bool):
    key = month_key()
    year, month = map(int, key.split("-"))
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
    spent = db.scalar(select(func.coalesce(func.sum(AIUsage.estimated_cost_eur), 0)).where(
        AIUsage.occurred_at >= start, AIUsage.occurred_at < end,
        AIUsage.status.in_(("COMPLETED", "INVALID_RESULT")))) or Decimal("0")
    # UNKNOWN calls conservatively consume their reservation.
    unknown = db.scalar(select(func.coalesce(func.sum(AIUsage.reserved_cost_eur), 0)).where(
        AIUsage.occurred_at >= start, AIUsage.occurred_at < end,
        AIUsage.status == "UNKNOWN")) or Decimal("0")
    spent += unknown
    rows = db.execute(select(AIUsage.agent_key, func.count(AIUsage.id),
        func.coalesce(func.sum(AIUsage.estimated_cost_eur), 0)).where(
        AIUsage.occurred_at >= start, AIUsage.occurred_at < end,
        AIUsage.status.in_(("COMPLETED", "INVALID_RESULT"))
    ).group_by(AIUsage.agent_key)).all()
    percent = (spent / budget * 100) if budget else Decimal("100")
    level, threshold = budget_level(percent)
    state = "disabled" if not enabled else "provider_not_configured" if not configured else level
    return {"status": state, "spent_eur": str(spent.quantize(Decimal("0.01"))),
        "budget_eur": str(budget.quantize(Decimal("0.01"))),
        "percentage": int(min(percent, Decimal("100"))),
        "warning_threshold": threshold,
        "agents": [{"agent_key": row[0], "calls": row[1],
                    "spent_eur": str(Decimal(row[2]).quantize(Decimal("0.01")))} for row in rows]}
