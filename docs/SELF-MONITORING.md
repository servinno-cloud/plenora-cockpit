# Collector freshness en self-monitoring

Cockpit gebruikt voor self-monitoring dezelfde PostgreSQL-observations, incidenten, fingerprints,
debounce en notification-outbox als voor production targets. De afzonderlijke
`cockpit-self-monitoring-worker` evalueert iedere 30 seconden; er is geen tweede incidentensysteem.

## Production-inventaris

| Component | Runtime / interval | Succes en laatste observation | Retry en persistente state |
|---|---|---|---|
| Externe webcollector | `cockpit-collector`, snapshot iedere 60 s | `collectors.last_seen_at`; laatste observation via `ingest_snapshots` | maximaal 50 snapshots in Docker-volume `cockpit_collector_state` |
| Database-, host-, container- en backupobserver | `plenora-observer`, snapshot iedere 60 s; hostboundary iedere 60 s | eigen collector identity met dezelfde PostgreSQL-velden | maximaal 50 snapshots in Docker-volume `plenora_observer_state`; host/backupboundary in `/run/plenora-cockpit` |
| Notificatieworker | outboxpoll iedere 15 s; DB-heartbeat iedere succesvolle cyclus | `notification.worker_heartbeat` in `observations` | `notification_events` bewaart PENDING/SENT/FAILED, attempts en laatste foutcode |
| Self-monitoringworker | evaluatie iedere 30 s | synthetische freshness-observations in PostgreSQL | Docker-heartbeat in `/tmp`; incidentstate blijft in PostgreSQL |
| Analysisworker | eigen Docker-heartbeat | geen production-observation | valt buiten deze notification/collector-freshnessronde |

De collectorinventaris in het snapshot-API toont per actieve identity naam, laatste succesvolle
ingest, laatste observation, actuele leeftijd, verwacht interval, maximale leeftijd en storage.
Web, database, host, containers en backups zijn probe-families binnen twee collectoridentities en
geen onafhankelijke schedulers.

## Semantiek en thresholds

- Een succesvol geaccepteerde snapshot ververst `Collector.last_seen_at`, ook wanneer een targetprobe
  verse `UNKNOWN` levert. Target-UNKNOWN opent daardoor geen `collector_stale` incident.
- Collectorleeftijd is HEALTHY tot en met 120 s, WARNING boven 120 s en CRITICAL boven 300 s.
- Een geconfigureerde collector of worker die nog nooit succesvol draaide krijgt eerst dezelfde
  bootstrapmarge; daarna gelden dezelfde WARNING/CRITICAL- en debounce-regels.
- Notification-workerheartbeat is HEALTHY tot en met 45 s, WARNING boven 45 s en CRITICAL boven 75 s.
- Oudste PENDING lifecycle-event is WARNING boven 600 s en CRITICAL boven 1800 s.
- Een laatste terminale FAILED delivery is CRITICAL totdat een nieuwere lifecycle-delivery SENT is.
- Niet-geconfigureerde e-mail blijft UNKNOWN en opent geen delivery-incident.

Alle waarden zijn via `COCKPIT_*` settings configureerbaar. Twee opeenvolgende failures openen en
twee opeenvolgende gezonde evaluaties resolven. Een actieve fingerprint wordt niet gedupliceerd;
CRITICAL escaleert hetzelfde incident.

`collector_stale` gebruikt collector-ID plus target in de bestaande fingerprint. De twee
notificationcondities gebruiken `notification_worker_stale` en `notification_delivery_stale` op het
vaste target `cockpit-notifications`.

## Grenzen

`/health` behoudt bewust zijn bestaande database/livenesssemantiek. Collector- of outboxdegradatie
mag de backendcontainer niet laten herstarten. De authenticated snapshot-API en het dashboard bieden
de detail/readinessinformatie zonder het publieke healthcontract te breken.

Self-monitoring kan niet betrouwbaar zijn eigen procesuitval, totale Cockpit-/VPS-uitval of verlies
van databaseconnectiviteit melden. Een defecte notification-worker kan een intern incident en
outboxevent achterlaten, maar niet zelfstandig garanderen dat dit per e-mail aankomt. Commercial GA
vereist daarom nog een onafhankelijke watchdog op `/health`, een periodieke end-to-end alertdelivery-
check met externe ontvangstbevestiging en bij voorkeur een uptimeprovider in een ander failure domain.

Er bestaat nog geen configureerbaar maintenance-windowmodel. De huidige bescherming tijdens korte
restarts/deployments bestaat uit de freshnessmarges en de bestaande twee-failure/twee-recoverydebounce.
