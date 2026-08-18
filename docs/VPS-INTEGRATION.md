# VPS-integratie en acceptatie

## Exacte eerste deployment

1. Clone Cockpit op VPS 2 naar `/opt/plenora-cockpit/app` en checkout een expliciete releasecommit.
2. Maak `.env.deploy` uit het voorbeeld, vul unieke secrets in en zet mode `0600`.
3. Controleer de externe Caddy- en Plenora-netwerknamen.
4. Registreer op VPS 2 twee identities: external collector en Plenora observer-publisher.
5. Start alleen Cockpit DB en controleer `pg_isready`.
6. Draai Alembic upgrade/current/check.
7. Provision de eerste OWNER interactief en verwijder bootstrapconfig.
8. Genereer uniek collectortoken, seed de collectoridentiteit.
9. Clone op VPS 1 naar `/opt/plenora-observer/app`, maak `.env.observer` mode `0600`.
10. Maak daar de monitorrol met psql-variabelen en zonder business-table grants.
11. Installeer op VPS 1 de hostmetrics timer en controleer de vijf vaste containernamen.
12. Valideer/voeg de Caddy-snippet toe zonder Pilot-routing te verwijderen.
13. Controleer DNS naar de huidige OVH VPS en laat Caddy TLS uitgeven.
14. Draai op VPS 2 `bash deploy/deploy.sh`; draai daarna op VPS 1 `bash deploy/observer-deploy.sh`.
15. Login en verifieer echte Web/Backup/Host/Database/Services-observations.
16. Bevestig Mail `UNKNOWN — Integratie nog niet gekoppeld`.

De root-owned timer draait één vast script zonder HTTP-input. Het publiceert alleen filesystembytes,
inodes, load, uptime en timestamp. Geen processen, users, filenames, environment, secrets of vrije
paden. Observer accepteert geen containerparameter en reduceert Dockerinspect tot service key,
`service_key`, running, health, restart count, started-at en gehashte image-ID. Er is in production
geen observer-API of inbound managementpoort. De publisher maakt uitsluitend uitgaand HTTPS-verkeer,
buffert maximaal 50 snapshots en hergebruikt snapshot-ID, sequence, replay- en idempotencysemantiek.
Een latere transporthardening kan scoped bearer vervangen door mTLS zonder payloadwijziging.

Operationeel groen vereist later op VPS: HTTPS 200, OWNER-login, alle Cockpit-services healthy, echte
Pilot/backup/host/database/services-data, Mail UNKNOWN, geen fixtures, geen socket in backend/collector,
geen observerwrites en geen secrets in UI/API.
