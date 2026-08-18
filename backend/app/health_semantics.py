from collections.abc import Iterable, Mapping

from .models import HealthState, Observation

STATE_ORDER = {
    "HEALTHY": 0,
    "DEGRADED": 1,
    "WARNING": 2,
    "UNKNOWN": 3,
    "CRITICAL": 4,
}
OVERALL_COMPONENTS = {"Web", "Backend", "Database", "Backups", "Host", "Services"}


def _effective_state(observation: Observation, stale: Mapping[object, bool]) -> str:
    return "UNKNOWN" if stale.get(observation.id, False) else observation.state.value


def _optional_unknown(observation: Observation) -> bool:
    return (
        observation.signal == "db.migration_current"
        and observation.state == HealthState.UNKNOWN
    ) or (
        observation.signal == "service.health"
        and observation.state == HealthState.UNKNOWN
        and observation.text_value == "none"
    )


def worst_state(states: Iterable[str]) -> str:
    return max(states, key=lambda value: STATE_ORDER[value], default="UNKNOWN")


def aggregate_health(
    observations: list[Observation], stale: Mapping[object, bool], targets: Mapping[object, str]
) -> tuple[dict[str, str], dict[str, str], str]:
    component_items: dict[str, list[Observation]] = {}
    service_items: dict[str, list[Observation]] = {}
    for item in observations:
        component_items.setdefault(item.component, []).append(item)
        if item.signal.startswith("service."):
            service_items.setdefault(targets.get(item.target_id, ""), []).append(item)

    components = {}
    for name, items in component_items.items():
        states = [
            _effective_state(item, stale)
            for item in items
            if not item.signal.startswith("service.") and not _optional_unknown(item)
        ]
        if states:
            components[name] = worst_state(states)
    services = {}
    service_components: dict[str, list[str]] = {}
    for key, items in service_items.items():
        if not key:
            continue
        running = next((item for item in items if item.signal == "service.running"), None)
        states = [_effective_state(running, stale)] if running is not None else ["UNKNOWN"]
        states.extend(
            _effective_state(item, stale)
            for item in items
            if item is not running and not _optional_unknown(item)
        )
        state = worst_state(states)
        services[key] = state
        service_components.setdefault(items[0].component, []).append(state)
    for component, states in service_components.items():
        non_service = components.get(component)
        components[component] = worst_state([*states, *([non_service] if non_service else [])])
    overall = worst_state(
        components.get(component, "UNKNOWN") for component in sorted(OVERALL_COMPONENTS)
    )
    return components, services, overall
