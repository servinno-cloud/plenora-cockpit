# Incidentmodel

## Doel

Incidenten vertalen herhaalde observations naar een stabiele operationele lifecycle. Dezelfde storing
mag niet iedere poll een nieuw incident maken en een enkele goede meting mag een langdurige storing
niet onmiddellijk als opgelost markeren.

## Lifecycle

```text
healthy ── failure policy ──> OPEN
OPEN ── operator ───────────> ACKNOWLEDGED
OPEN/ACKNOWLEDGED ── recovery policy ──> RESOLVED
RESOLVED ── nieuwe failure ──> nieuw occurrence of heropend incident
```

- `OPEN`: conditie is actief en niet acknowledged;
- `ACKNOWLEDGED`: operator heeft gezien dat de conditie actief is;
- `RESOLVED`: herstelpolicy is duurzaam gehaald.

Acknowledge verandert severity of health niet. Resolution gebeurt automatisch; handmatig “groen
zetten” bestaat niet. Een operator kan alleen een foutief incident annoteren, waarna policyconfiguratie
afzonderlijk en geaudit moet worden aangepast.

## Velden

- `id`: UUID;
- `environment_id`;
- `target_id` of stabiele target key;
- `component`;
- `severity`: DEGRADED, WARNING of CRITICAL;
- `incident_code`;
- `fingerprint`;
- `title_code` en gerenderde vaste titel;
- `state`;
- `source`;
- `first_seen_at`, `last_seen_at`, `opened_at`;
- `acknowledged_at`, `acknowledged_by`;
- `resolved_at`;
- `occurrence_count`;
- `latest_observation_id`;
- `policy_version`;
- optionele operatornotitie zonder persoonsgegevens.

Onderliggende observations blijven via IDs gekoppeld. Incidenten kopiëren geen raw payloads of logs.

## Deduplicatie

Canonieke fingerprint:

```text
sha256(environment_id + "|" + component + "|" + incident_code + "|" + target_key)
```

Target key komt uit gecontroleerde configuratie. Severity zit niet in de fingerprint zodat escalatie
hetzelfde incident actualiseert. Source zit alleen in de fingerprint wanneer twee bronnen bewust
onafhankelijke incidenten moeten vormen; normaal correleert policy meerdere bronnen tot één conditie.

Er kan maximaal één niet-RESOLVED incident per fingerprint bestaan, afgedwongen met een database-
constraint/transactionele lock. Iedere nieuwe falende evaluatie verhoogt `occurrence_count` en
`last_seen_at`.

## Open- en herstelpolicies

Standaard anti-flapregels:

- CRITICAL availability: open na 2 opeenvolgende failures binnen 90 seconden;
- threshold WARNING: open na 2 evaluaties;
- backup age/disk: direct openen zodra duurzame metriek threshold passeert;
- UNKNOWN: apart incident na freshnessgrens, niet dezelfde code als component failure;
- resolve na 3 opeenvolgende gezonde observaties en minimaal 2 minuten herstel;
- flapping detectie bij 4 statewissels in 15 minuten: incident blijft open als WARNING `signal_flapping`.

Policies zijn configureerbaar per signal definition/environment, met globale veilige defaults. Geen
klantnamen of klantlogica in policycode.

## Severitycorrelatie

Voorbeelden:

- backend extern onbereikbaar én container stopped: één CRITICAL backend incident met beide bronnen;
- mailworker stopped en queue leeg: WARNING;
- mailworker stopped en queue >0: hetzelfde incident escaleert naar CRITICAL;
- backup failed maar laatste succes <26 uur: WARNING;
- backup failed en laatste succes >48 uur: CRITICAL;
- collector offline: collector incident plus afhankelijke signalen UNKNOWN, niet tientallen CRITICALs;
- database unreachable maakt afgeleide mailqueue/migrationprobes UNKNOWN om incidentstorms te voorkomen.

## Reopen en occurrences

Een storing binnen 30 minuten na resolution heropent standaard hetzelfde incident en maakt een nieuwe
occurrence. Na 30 minuten wordt een nieuw incident met dezelfde fingerprint toegestaan, gekoppeld via
`previous_incident_id`. Hierdoor blijven MTTR en incidentfrequentie betekenisvol.

## Observations en timeline

Incidenttimeline-events:

- `incident.opened`;
- `incident.severity_changed`;
- `incident.acknowledged`;
- `incident.observation_attached` met sampling;
- `incident.recovered_pending`;
- `incident.resolved`;
- `incident.reopened`.

Niet iedere poll wordt als timeline-event gekopieerd. Identieke observations worden samengevat met
count, eerste en laatste timestamp.

## Onderhoudsvensters

Een toekomstig configureerbaar maintenance window onderdrukt nieuwe alerts maar niet observations.
V1 kan het model opnemen zonder UI. Onderhoud verandert health naar DEGRADED/MAINTENANCE-presentatie,
wordt geaudit en heeft altijd start/einde, environmentscope en reden. Een onbeperkt mute bestaat niet.

## Retentie

- raw observations: 14 dagen;
- health snapshots op pollniveau: 30 dagen;
- hourly aggregates: 13 maanden;
- incidenten en compacte timeline: minimaal 3 jaar;
- auditlog: minimaal 3 jaar;
- collector ingest requestmetadata: 30 dagen;
- geen raw logs in v1.

Dagelijkse achtergrondtaken verwijderen in batches en maken hourly aggregates vóór raw data verdwijnt.
Per signal geldt een cardinaliteitsbudget; onverwachte groei opent zelf een Cockpit WARNING.

## Concurrency en betrouwbaarheid

Incident evaluation en upsert gebeuren in één databasetransactie. De fingerprintrow wordt gelockt of
met een unieke partial index beschermd. Snapshot ingestion is idempotent op `snapshot_id`; herhaalde
delivery maakt geen extra observations of incidents. Policies dragen een versie zodat historische
beslissingen reproduceerbaar blijven.

