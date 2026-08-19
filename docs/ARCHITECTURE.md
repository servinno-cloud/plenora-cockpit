# Architectuur

## Incidentnotificaties (Sprint 5)

De betrouwbare keten is `Monitoring → Observation → Incident lifecycle → NotificationEvent →
e-maildelivery`. Incidentmutatie en het unieke outboxevent worden in dezelfde PostgreSQL-transactie
geschreven. Een afzonderlijke, non-root `cockpit-notification-worker` claimt pending events en doet
SMTP-I/O buiten ingest. De worker stopt na een begrensd aantal pogingen; providerstoringen veranderen
nooit het ingestresultaat. Ontbrekende configuratie laat events pending en toont e-mail als niet
geconfigureerd. Cockpit observeert en waarschuwt; het repareert, restart of deployt niets.

Sprint 3 gebruikt twee VPS'en. De allowlisted observer-publisher op Plenora VPS 1 verzamelt lokaal vaste
host-, backup-, database- en servicesignalen en pusht `snapshot.v1` uitgaand naar authenticated ingest.
Cockpit VPS 2 bevat geen Plenora-socket, mount of databasecredential. Een tweede collector op VPS 2
meet extern Pilot zodat verlies van VPS 1 zichtbaar blijft. Sequences zijn per collectoridentiteit.

## Doel en grenzen

De Cockpit is een zelfstandig operationsproduct. Zij observeert Plenora via onafhankelijke
technische probes en een klein aantal privacyarme productcontracten. Een defecte Plenora-backend
mag externe availability, containerstatus, databasehealth, diskruimte en backupstatus niet
onzichtbaar maken.

V1 is observe-first en read-only. Remediation, deployment, migrations, restore en wijzigingen aan
gebruikers of productiegegevens vallen buiten scope.

## Aanbevolen stack

| Component | Keuze | Reden |
|---|---|---|
| Web UI | Next.js + TypeScript | Volwassen responsive UI, sluit aan bij teamkennis zonder code te delen |
| API | Python 3.12 + FastAPI | Compact, typed OpenAPI-contract, goede async I/O voor snapshots en historie |
| Collector | Kleine Python 3.12 daemon | Herbruikbare probe-library, eenvoudig systemd-hardening en mTLS |
| Datastore | PostgreSQL 16 | Betrouwbare concurrency, retentiequeries, incidenthistorie en latere multi-hostgroei |
| Scheduling | API-side scheduler met DB-lock | Eén actieve scheduler zonder aparte broker in v1 |
| Deployment | Docker Compose + Caddy; collector als host systemd-service | Zelfstandig deploybaar, collector buiten Docker-socket failure domain |

SQLite wordt niet aanbevolen: polling, incidentupdates, auditlog en meerdere API-processen maken
locking en migratie naar PostgreSQL voorspelbaar duurder dan direct een kleine eigen PostgreSQL.
Geen Redis of message broker in v1; die wordt pas toegevoegd bij aantoonbare schaalbehoefte.

## Componenten

### Web UI

Vraagt uitsluitend Cockpit API-data op. Bevat geen collectorcredentials, Dockerkennis of directe
Plenora-integratie. Desktop-first en responsive met statuskaarten, incidentlijst, backups, mail,
system, release en compacte healthtimeline. Geen terminal, logviewer of actieknoppen.

### Cockpit API

Beheert operatorsessies, products/environments/targets, actuele health, historie, incidenten en
auditlog. De API accepteert collector snapshots via een afzonderlijk ingestvlak. Read- en
ingest-routes krijgen gescheiden authenticatie, rate limits en netwerkbeleid.

### Eigen datastore

Bevat uitsluitend Cockpitconfiguratie en technische observabilitydata. Er is geen database-link,
foreign data wrapper of gedeeld schema met Plenora.

### Collector / probe-runner

Een root-owned hostservice voert een vaste allowlist van probes uit. Hij leest beperkte lokale
statusbronnen, stelt één gesanitized snapshot samen en pusht dit naar de Cockpit API. Er is geen
generieke command-executionroute en geen door de API aangeleverde shellcode.

### Incident engine

Evalueert observations tegen configureerbare policies, dedupliceert fingerprints en beheert
OPEN/ACKNOWLEDGED/RESOLVED. Evaluatie is deterministisch; v1 gebruikt geen AI.

### Auditlog

Append-only applicatielog voor login, logout, mislukte login, acknowledge, configuratiewijziging en
latere acties. Probe-observations zijn geen auditlog.

### Agent Gateway

In v1 alleen een interface en capabilitycatalogus. De enige uitgiftebare capabilities zijn
`observe.health`, `observe.metrics`, `observe.history` en `observe.incidents`. Er is geen LLM- of
agentintegratie.

## Domeinmodel

```text
Product
  └─ Environment
       ├─ Collector
       ├─ Target
       │    └─ SignalDefinition
       ├─ Observation
       ├─ HealthSnapshot
       └─ Incident

Operator ── OperatorRole
Operator ── AuditEvent
```

Belangrijkste entiteiten:

- `Product`: generiek product, aanvankelijk Plenora;
- `Environment`: staging, productie of toekomstige klantomgeving;
- `Target`: web, backend, database, mail, backup, host of concrete service;
- `Collector`: technische identiteit, versie, laatste contact en environment-scope;
- `Observation`: één gemeten signaal met bron en timestamp;
- `HealthSnapshot`: afgeleide toestand per target en environment;
- `Incident`: gededupliceerde operationele afwijking;
- `Operator`: menselijke Cockpitgebruiker, onafhankelijk van Plenora-accounts;
- `AuditEvent`: onveranderbaar beveiligings- of bedieningsmoment.

IDs zijn opaque UUIDs. Namen en labels zijn configuratie, geen klantlogica.

## Datastroom

1. De collector voert lokale host-, Docker-, database-, backup- en mailqueueprobes uit.
2. De Cockpit API of een onafhankelijke HTTP-prober meet publieke HTTPS-health en latency.
3. De collector pusht een ondertekende/versioned snapshot naar het ingestendpoint.
4. De API valideert schema, collectoridentiteit, environmentbinding, timestamp en replaygrens.
5. Observations worden opgeslagen en health policies worden geëvalueerd.
6. De incident engine opent, actualiseert of resolveert incidenten.
7. De UI leest alleen Cockpitdata.

Externe HTTPS-probes moeten uiteindelijk vanaf VPS 2 of een externe monitor draaien; een probe vanaf
dezelfde VPS detecteert geen volledig host- of netwerkverlies.

## Collectorarchitectuur en Docker

Sprint 2 gebruikt lokaal een afzonderlijke fixture-observer zonder Docker socket. In productie wordt
dit contract ingevuld door een hardened host-side helper; collector, API en UI krijgen de socket
nooit. Databaseobservatie gebruikt een dedicated technische monitorrole en gesloten querycatalogus.
Mail gebruikt uitsluitend het privacyarme contract uit `PLENORA-INTEGRATION.md`; brede databaselezing
is geen fallback. De contractgrens blijft identiek wanneer Cockpit naar VPS 2 verhuist.

V1-keuze: een root-owned host-side collector met strikt vaste probes. De Cockpit web- en
API-containers krijgen nooit `/var/run/docker.sock`.

Voor containerobservatie gebruikt de collector bij voorkeur een hardened Docker socket proxy als
aparte lokale service. Alleen read-endpoints voor `/_ping`, `/version`, `/containers/json` en
`/containers/{id}/json` worden toegestaan; alle create/start/stop/exec/images/volumes/networks/events
write-routes worden geweigerd. De proxy luistert uitsluitend op een Unix socket of loopbackpoort die
alleen de collector kan bereiken. Als een voldoende kleine proxy niet aantoonbaar te hardenen is,
mag de hostcollector de socket direct lezen, maar blijft hij root-owned, minimalistisch, zonder
netwerklistener en met dezelfde vaste allowlist. Dit risico staat expliciet in het threat model.

Geen Dockerlabels of containernamen uit een snapshot mogen als commando worden uitgevoerd.

## Pollingfrequenties

| Signaal | Standaard | Timeout |
|---|---:|---:|
| Externe HTTPS `/health/` | 30 s | 5 s |
| Containerstatus | 30 s | 5 s |
| Mailworker/queue | 60 s | 5 s |
| Database connect/read/latency | 60 s | 5 s |
| Migrations/release | 5 min | 10 s |
| Disk/inodes/backupstatus | 5 min | 10 s |
| TLS-expiry | 6 uur | 10 s |
| Restore-verificatiestatus | 15 min | 5 s |

Intervallen, timeouts, jitter en thresholds zijn environmentconfiguratie met veilige
productdefaults. Pollers gebruiken jitter en exponential backoff bij transportfalen.

## Deployment op VPS 1

```text
Internet
  └─ Caddy :80/:443
       ├─ pilot.plenora.nl   → bestaande Plenora frontend/backend
       └─ cockpit.plenora.nl → cockpit-web / cockpit-api

Host systemd
  └─ cockpit-collector → localhost/mTLS ingest

Cockpit Compose network
  ├─ web
  ├─ api
  └─ cockpit-db
```

Cockpit API en database publiceren geen hostpoorten. Caddy krijgt een afzonderlijke host rule; de
bestaande pilotroute wordt niet aangepast behalve door toevoeging van een onafhankelijk siteblok.
Collector- en operator-ingress worden logisch gescheiden, ook als dezelfde API-image wordt gebruikt.

De Cockpit gebruikt een eigen databasevolume, secrets, migrations en release-id. Restart of upgrade
van Cockpit raakt geen Plenora-container of volume.

## Pad naar VPS 2

De collector blijft op de gemonitorde host en pusht via uitgaand HTTPS naar de Cockpit op VPS 2.
De volgende onderdelen hoeven dan niet te wijzigen:

- snapshot schema en environment-scoping;
- collectoridentiteit en certificaten;
- incident- en healthmodel;
- UI/API/datastore.

Wel wijzigen DNS, Caddy, Cockpit Compose-host en collector ingest-URL. Externe HTTPS-probes verhuizen
naar VPS 2, waardoor volledig VPS- of netwerkverlies zichtbaar wordt. Cockpitbackups, alertkanaal en
monitoring krijgen daar een eigen failure domain.

## Cockpit self-monitoring

- `/health/live`: proces leeft, zonder externe dependencies;
- `/health/ready`: datastore bereikbaar en schema actueel;
- container healthchecks voor web/API/database;
- scheduler heartbeat in eigen datastore;
- collector last-seen als afzonderlijk signaal;
- later een externe availabilitycheck vanaf een onafhankelijke locatie.

Collectorobservatie blijft bruikbaar als web-UI tijdelijk uitvalt: ingest en UI zijn logisch
gescheiden, snapshots worden bij tijdelijk transportfalen kort lokaal gebufferd met begrensde opslag.

## UI v1

De startpagina toont één gekozen environment prominent, zonder het domeinmodel tot één environment
te beperken:

1. header met product, environment, overall health en freshness;
2. statuskaarten voor Web, Backend, Database, Mail, Backups en Host;
3. open incidenten, gesorteerd op severity en daarna first-seen;
4. backupkaart met laatste succes, leeftijd, checksum, restore-verificatie en volgende timer-run indien
   betrouwbaar beschikbaar;
5. mailkaart met provider, queued/retryable/failed, oudste queue-item en workerstatus;
6. systemkaart met disk, database en containers;
7. releasekaart met commit, image IDs, migrations en deploymentleeftijd;
8. compacte recente healthtimeline zonder complexe charting.

Elke status toont state, observed-at, freshness en vaste technische code. UNKNOWN is visueel duidelijk
anders dan HEALTHY. De UI bevat geen logs met vrije inhoud, terminal, SSH-console, restart-, deploy- of
restoreknoppen.

## Besluitenoverzicht

1. **Stack:** Next.js/TypeScript, FastAPI/Python en PostgreSQL 16.
2. **Repository:** zelfstandige monorepo met web, API, collector en versioned contracts.
3. **Datastore:** eigen PostgreSQL; geen gedeelde Plenora-database en geen SQLite in productie.
4. **Collector:** root-owned hostservice met vaste allowlisted probes.
5. **Docker:** geen socketmount in web/API; hardened read-only proxy als voorkeursgrens.
6. **Authenticatie collector:** mTLS per collector/environment met sequence- en replaycontrole.
7. **Polling:** 30 seconden voor availability/containers, 60 seconden voor DB/mail en lager frequent
   voor disk, backup, release en TLS.
8. **Health:** HEALTHY, DEGRADED, WARNING, CRITICAL en UNKNOWN met freshness.
9. **Incidentdeduplicatie:** stabiele fingerprint plus één actief incident per fingerprint.
10. **Retentie:** raw 14 dagen, pollhistory 30 dagen, hourly 13 maanden, incidents/audit 3 jaar.
11. **Operatorauth:** eigen Argon2id-auth, secure sessions, CSRF, rate limiting en MFA-ready schema.
12. **Deployment:** eigen Compose/database/secrets en apart Caddy-siteblok op dezelfde VPS.
13. **VPS 2:** collectors blijven bij targets en pushen uitgaand mTLS; externe probes verhuizen mee.
14. **Agents:** capability-based gateway; v1 registreert uitsluitend `observe.*`.
15. **Grootste risico's:** Dockerprivilege, gedeeld VPS-failure domain, collectorcredentialmisbruik,
    privacy leakage, operator takeover en onbegrensde metric cardinaliteit.
