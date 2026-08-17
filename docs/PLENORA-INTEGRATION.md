# Plenora integration requirements

Sprint 3 operationaliseert Web, Backup, Host, Database en Services. Mail blijft in productie bewust
uitgeschakeld; `MAIL_INTEGRATION_ENABLED=false` voorkomt fake healthy.

## Doel en grens

Cockpit Sprint 2 wijzigt Plenora niet. De lokale Mail- en Services-data zijn expliciete fixtures en
hebben geen productiefallback. Productie-integratie vereist onderstaande read-only contracten.

## Mail observabilitycontract

Voorkeur: een dedicated host-side of Plenora-intern `GET /internal/observability/v1/mail` endpoint,
alleen bereikbaar voor een unieke collectoridentiteit via mTLS of een kortlevend scoped credential.
Het endpoint accepteert geen parameters en ondersteunt geen andere HTTP-methoden.

```json
{
  "provider_state": "configured",
  "worker_running": true,
  "queue_count": 0,
  "retryable_count": 0,
  "failed_count": 0,
  "oldest_queue_age_seconds": 0,
  "last_accepted_age_seconds": 45
}
```

Verboden: recipient, e-mailadres, subject, body, templatevariabelen, activatie-/resettoken,
providerresponse, provider message ID en vrije fouttekst. Cockpit gebruikt geen brede databaselezing
als workaround. Tot dit contract bestaat blijft production Mail eerlijk `UNKNOWN`.

## Database monitoringrole

De production collector gebruikt een afzonderlijke loginrole met alleen `CONNECT` en expliciet
`SELECT` op de technische migratietabel. De gesloten catalogus:

- `SELECT current_setting('server_version_num')::int / 10000`;
- `SELECT pg_database_size(current_database())`;
- connection percentage uit `pg_stat_activity` en `max_connections`;
- `SELECT version_num FROM alembic_version LIMIT 1`.

Collectorinput kan geen SQL kiezen. Geen rechten op people, shifts, leave, notes, mailtabellen of
andere businessschemas. Credentials zijn hostgebonden en alleen bij de collector aanwezig.

## Services boundary

Een host-side publisher bezit als enige Docker-sockettoegang. Hij verzamelt uitsluitend
`caddy`, `frontend`, `backend`, `db` en `mail-worker` met running, health, restart count, started-at en
een gehashte image-ID. Geen environment, mounts, raw config, logs of inspectpayloads. Hij exposeert
geen production HTTP-API en pusht uitsluitend `snapshot.v1` naar Cockpit. Exec/start/stop/restart/
create/remove zijn structureel afwezig.
