# Production deployment

Sprint 3 gebruikt twee losse deployments. VPS 2 bevat Cockpit onder `/opt/plenora-cockpit/app` met
`docker-compose.deploy.yml`. VPS 1 bevat de Plenora observer-publisher onder
`/opt/plenora-cockpit-observer/app` met `docker-compose.observer.yml`. Beide env-bestanden zijn
niet-getrackt en mode `0600`. Deze repository voert geen deployment, DNS- of Caddy-mutatie uit.

## Topologie

- `cockpit-db` staat alleen intern en heeft geen hostpoort.
- backend en frontend delen het externe Caddy-netwerk, zonder hostpoort.
- de VPS-2 collector heeft alleen externe HTTPS-probes en intern ingestverkeer;
- VPS 2 bevat geen Plenora-socket, filesystemmount of databasecredential;
- de VPS-1 observer-publisher heeft lokaal de socket, exact status.json, exact host.json en de
  least-privilege database-DSN;
- de observer luistert niet op een HTTP-poort en pusht `snapshot.v1` via authenticated HTTPS ingest.

Applicatiecontainers draaien non-root met read-only rootfs, `cap_drop: ALL`, no-new-privileges,
healthchecks en resourcegrenzen. PostgreSQL behoudt uitsluitend zijn datavolume.

## Eerste OWNER

Er is geen registratie en er zijn geen defaultcredentials. Zet alleen tijdelijk de bootstrap-email en
voer interactief uit:

```bash
docker compose --env-file .env.deploy -f docker-compose.deploy.yml run --rm \
  cockpit-backend python -m app.cli create-owner --email owner@example.invalid
```

Voer het wachtwoord via de verborgen prompt in en verwijder bootstrapconfig daarna. Een tweede OWNER
wordt geweigerd. Productie vereist HTTPS-origin, Secure/SameSite Strict cookies, CSRF en rate limiting.

## Caddy, backup en rollback

Voeg `deploy/Caddyfile.cockpit` toe zonder `pilot.plenora.nl` te wijzigen. Caddy levert TLS en HSTS.
De ingestroute is publiek bereikbaar maar accepteert uitsluitend de bestaande scoped collectorbearer,
environmentbinding, idempotency key en monotone sequence.
Het ruwe observer-token wordt alleen aan de eenmalige seedcontainer doorgegeven; de backend-runtime
ontvangt het niet en bewaart uitsluitend de SHA-256-verificatiehash in Cockpit PostgreSQL.
DNS A/AAAA voor `cockpit.plenora.nl` wijst later naar het huidige OVH VPS-adres.

Maak dagelijks een versleutelde custom-format `pg_dump` van Cockpit DB. `.env.deploy` hoort niet in
de dump en wordt apart als secretconfig behandeld. Test restore eerst geïsoleerd. Deze repo wijzigt het
Plenora-backupscript niet. Rollback is handmatig naar een bewezen release na migratiecompatibiliteits-
controle; er is geen automatische downgrade, reset of `down -v`.
