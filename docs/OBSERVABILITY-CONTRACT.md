# Observabilitycontract

Sprint 3 production gebruikt echte Web/Backup/Host/Database/Services-bronnen. Hostoutput is beperkt tot
uptime, root/backup bytes en inodes, load averages en timestamp. Serviceoutput bevat alleen vijf vaste
keys, running, health, restart count, started-at en gehashte image-ID. Uitgeschakelde Mail-integratie
levert expliciet UNKNOWN met `integration_disabled`.

VPS 1 pusht dit als bestaand `snapshot.v1` naar Cockpit. Observer- en externe-webcollector hebben
afzonderlijke identities, monotone sequences en buffers; snapshot-ID en idempotency blijven ongewijzigd.

## Contractprincipes

- versioned JSON, initieel `snapshot.v1`;
- gesloten schema: onbekende velden worden geweigerd;
- UTC RFC 3339 timestamps;
- waarden zijn technisch en privacyarm;
- één snapshot hoort bij precies één collector en environment;
- absence en probe failure worden expliciet als UNKNOWN vastgelegd, niet als gezond;
- thresholds worden door Cockpitbeleid toegepast, niet door klantcode;
- collector levert ruwe technische feiten en eventueel een bronstatus, geen overall health.

## Collectortransport

```http
POST /ingest/v1/environments/{environment_id}/snapshots
Content-Type: application/json
Idempotency-Key: <snapshot_uuid>
```

Authenticatie: uniek mTLS-clientcertificaat. Maximale bodygrootte v1: 256 KiB. De API valideert
environmentbinding, idempotency key, sequence, clock skew en schema vóór opslag. Response bevat alleen
acceptatiestatus, server timestamp en snapshot-ID.

Voor diagnose kan de collector lokaal `GET /v1/snapshot` aanbieden, maar op VPS 1 is push de
standaard. Een lokale endpoint luistert uitsluitend op Unix socket/loopback en gebruikt hetzelfde
schema. VPS 2 vereist geen inkomende collectorpoort op de gemonitorde host.

## Snapshot envelope

```json
{
  "schema": "snapshot.v1",
  "snapshot_id": "018f0000-0000-7000-8000-000000000001",
  "collector_id": "018f0000-0000-7000-8000-000000000002",
  "environment_id": "018f0000-0000-7000-8000-000000000003",
  "sequence": 1842,
  "generated_at": "2026-08-16T14:00:00Z",
  "collector_version": "1.0.0",
  "observations": []
}
```

## Observation

```json
{
  "target": "backend",
  "signal": "http.health",
  "source": "external_https",
  "observed_at": "2026-08-16T14:00:00Z",
  "state": "HEALTHY",
  "code": "http_ok",
  "message": "Health endpoint bereikbaar",
  "value": 84,
  "unit": "ms",
  "threshold": {"warning": 500, "critical": 2000}
}
```

`message` komt uit een vaste catalogus en bevat geen ruwe exception, URL-query, SQL of containerlog.
`value` kan number, boolean of korte enum zijn. High-cardinality labels zijn verboden.

## Healthstatus

- `HEALTHY`: signaal binnen normale grenzen;
- `DEGRADED`: dienst functioneert aantoonbaar, maar met beperkte capaciteit of redundancy;
- `WARNING`: risico of onderhoudsbehoefte zonder directe kernuitval;
- `CRITICAL`: kernfunctie onbeschikbaar, data-integriteitsrisico of urgente capaciteitsgrens;
- `UNKNOWN`: geen verse betrouwbare observatie.

Overall health is de zwaarste actieve toestand, met policy-excepties voor afhankelijkheden. UNKNOWN
wordt nooit stil als HEALTHY behandeld. Bij een korte transporthapering blijft de laatste toestand
zichtbaar met `stale=true`; na de freshnessgrens wordt het signaal UNKNOWN.

## Vereiste signalen

Sprint 2 behoudt `snapshot.v1` en voegt gesloten signalen toe: `db.reachable`, `db.version_major`,
`db.latency_ms`, `db.size_bytes`, `db.connections_percent`, `db.django_migration_count`,
`db.migration_current`, de privacyarme
`mail.*` counts/states, `service.running`, `service.health`, `service.restart_count`,
`service.uptime_seconds`, `service.release_state`, `collector.sequence` en `collector.status`.
Tekstwaarden zijn beperkte enums; onbekende signalen, services, bronnen en tekstwaarden worden
geweigerd.

`db.django_migration_count` telt uitsluitend records in `public.django_migrations`; app- en
migrationnamen worden niet gepubliceerd. Zonder expliciete verwachte releasemarker kan PostgreSQL
niet weten welke Django migration de applicatie verwacht. `db.migration_current` blijft daarom
expliciet `UNKNOWN`; alleen het bestaan of de omvang van de tabel wordt nooit als current behandeld.

Voor component-health telt deze bewust optionele UNKNOWN niet als database-uitval. Database is
HEALTHY wanneer alle beschikbare operationele checks (`reachable`, major version, latency, omvang,
connectionpercentage en migrationcount) gezond zijn. Een expliciete migration-mismatch blijft wel
WARNING. Service `health=none` betekent dat de container draait zonder Docker-healthcheck en wordt
afzonderlijk getoond; alleen `running=false`, `unhealthy` of langdurig `starting` duidt een storing aan.
Overall wordt bepaald door Web, Backend, Database, Backups, Host en Services. Mail en een onbekende
verwachte migratiestatus zijn optioneel totdat hun integratie expliciet is gekoppeld.

### Externe web/backend

| Signal | Waarden | Standaard policy |
|---|---|---|
| `https.reachable` | boolean | false = CRITICAL na 2 opeenvolgende failures |
| `https.status_code` | integer | niet 2xx = CRITICAL |
| `https.latency_ms` | integer | >500 WARNING, >2000 CRITICAL |
| `health.status_code` | integer | niet 200 = CRITICAL |
| `tls.days_remaining` | integer | <30 WARNING, <14 CRITICAL |

Probe-URL's zijn environmentconfiguratie. Responsebody wordt niet opgeslagen; `/health/` mag alleen
een vaste technische status leveren.

### Containers

Voor `caddy`, `frontend`, `backend`, `db`, `mail-worker`:

- `container.running`;
- `container.health` (`healthy|unhealthy|starting|none`);
- `container.restart_count`;
- `container.started_at`;
- `container.image_id` en veilige image-tag;
- `container.release` indien aanwezig.

`running=false` voor backend/database is CRITICAL. Mailworker volgt de gecombineerde mailpolicy.
Containernamen, labels en imagewaarden worden begrensd en als data behandeld.

### Database

- `database.connectable`;
- `database.latency_ms`;
- `database.version`;
- `database.read_probe`;
- `database.size_bytes`;
- `database.migrations_current`;
- `database.latest_migration`.

De read probe is een vaste technische query. Geen tabelsamples of businesswaarden. Niet connectable of
read probe failure is CRITICAL; migrations achter release is WARNING of CRITICAL volgens releasepolicy.

### Backups

Root-only bron: `/var/backups/plenora/status.json`. De production observer leest deze bron niet
rechtstreeks. De systemd host-helper valideert uitsluitend onderstaande Backup v1-velden en
publiceert ze atomisch als `/run/plenora-cockpit/backup-status.json` voor de non-root publisher.

- `backup.last_attempt_at`;
- `backup.last_success_at`;
- `backup.status`;
- `backup.backup_id`;
- `backup.database_bytes`;
- `backup.media_bytes`;
- `backup.checksum_verified`;
- `backup.git_commit`;
- afgeleid `backup.success_age_seconds`.

Standaard: ouder dan 26 uur WARNING, ouder dan 48 uur CRITICAL; laatste status failed is minimaal
WARNING en CRITICAL wanneer geen verse succesvolle set bestaat.

Minimale toekomstige, backwards-compatible restore-extensie, zonder Backup v1 nu te wijzigen:

```json
{
  "restore_verification": {
    "last_verified_at": "2026-08-16T15:00:00Z",
    "backup_id": "2026-08-16T140000Z",
    "result": "success|failed",
    "error_code": ""
  }
}
```

Dit mag ook als apart root-owned `restore-verification-status.json` verschijnen. Geen dumpnamen buiten
backup-ID, databaseinhoud of stderr. Standaard verification age >8 dagen WARNING, >15 dagen CRITICAL.

### Mail

- `mail.provider`: veilige enum, bijvoorbeeld `resend` of `brevo`;
- `mail.queue.queued_count`;
- `mail.queue.retryable_count`;
- `mail.queue.failed_count`;
- `mail.queue.oldest_queued_age_seconds`;
- `mail.last_accepted_at`;
- `mail.worker_running`.

Geen recipient, subject, body, providerpayload, token, URL of provider message ID. Worker down met lege
queue is WARNING; worker down met queue >0 is CRITICAL. Queueleeftijd >10 minuten WARNING en >30
minuten CRITICAL als configureerbare defaults.

### Host en disk

- `host.uptime_seconds`;
- `host.load_1m` optioneel in v1;
- `disk.root.used_percent`;
- `disk.root.inodes_used_percent`;
- `disk.backup.used_percent` indien apart filesystem;
- `backup.directory_bytes`.

Disk >80% WARNING en >90% CRITICAL. Inodes gebruiken dezelfde defaults. Absolute bytes blijven voor
capaciteitsplanning beschikbaar.

### Deployment

- `release.git_commit`;
- `release.release_id`;
- `release.deployed_at` indien beschikbaar;
- `release.age_seconds` afgeleid;
- `release.image_ids` per service;
- `release.migrations_applied`.

Geen repositorycredentials of volledige environment dump.

## Polling en freshness

De standaardintervallen staan in ARCHITECTURE. Freshness is normaal driemaal het interval, met een
minimum van 90 seconden. Daarna wordt een ontbrekend signaal UNKNOWN. Collector last-seen >2 minuten
is WARNING en >5 minuten CRITICAL, behalve tijdens geconfigureerd onderhoud.

## Privacy- en cardinaliteitsbudget

Toegestane dimensies: environment, target, signal, source en een begrensde service-enum. Verboden zijn
person-ID, e-mail, request-ID uit Plenora, mail-ID en vrije padnamen. Nieuwe signalen vereisen contract-,
privacy-, threshold- en retentiereview.
