# Production deployment

Sprint 3 gebruikt twee losse deployments. VPS 2 bevat Cockpit onder `/opt/plenora-cockpit/app` met
`docker-compose.deploy.yml`. VPS 1 bevat de Plenora observer-publisher onder
`/opt/plenora-cockpit-observer/app` met `docker-compose.observer.yml`. Beide env-bestanden zijn
niet-getrackt en mode `0600`. Deze repository voert geen deployment, DNS- of Caddy-mutatie uit.

Initialiseer op VPS 2 de production environment één keer vanuit de repositoryroot:

```bash
cd /opt/plenora-cockpit/app
bash deploy/init-env.sh
```

De helper weigert een bestaande `.env.deploy`. Alleen een bewuste
`bash deploy/init-env.sh --force` vervangt hem. Hij genereert uitsluitend Cockpit-eigen hexsecrets,
stabiele UUIDv4-identifiers, zet mode `0600` en valideert de resulterende production Composeconfig.
Bij een `--force`-upgrade blijven bestaande secrets en monitoringidentifiers behouden; de oude
`COLLECTOR_ID`, `COLLECTOR_ENVIRONMENT_ID` en `COLLECTOR_TOKEN` worden eenmalig naar de canonieke
`COCKPIT_MONITORING_*`-namen gemigreerd. Dezelfde environment-ID bindt hierdoor de seedrecord,
collector en ingest-auth. Plenora observercredentials blijven leeg totdat de afzonderlijke
VPS-1-koppeling wordt geprovisioned.

Upgrade een bestaande VPS-2-config en hermaak daarna de services zodat de canonieke waarden in hun
procesenvironment terechtkomen:

```bash
bash deploy/init-env.sh --force
docker compose --env-file .env.deploy -f docker-compose.deploy.yml up -d --force-recreate
docker compose --env-file .env.deploy -f docker-compose.deploy.yml exec -T \
  cockpit-backend python -m app.cli seed-monitoring
```

Maak na het starten van `cockpit-backend` de eerste OWNER interactief aan zonder de env-file te wijzigen:

```bash
cd /opt/plenora-cockpit/app
bash deploy/bootstrap-owner.sh
```

Het wachtwoord wordt verborgen gelezen en uitsluitend via naamgebaseerde environment-forwarding aan
het eenmalige CLI-proces gegeven. Het verschijnt niet in argv, logs, shell history of `.env.deploy`.

## Collectorcredential roteren

Roteer een gelekte of periodiek te vervangen VPS-2 collectorcredential zonder deze te tonen of in
commandlineargumenten te plaatsen:

```bash
cd /opt/plenora-cockpit/app
bash deploy/rotate-collector-secret.sh
```

De helper controleert eerst de huidige DB-hash, schrijft `.env.deploy` atomisch met mode `0600`,
vernieuwt uitsluitend de verificatiehash onder een row lock en recreëert backend en collector zodat
geen oude credential in een procesenvironment achterblijft. Het named collector-statevolume blijft
gekoppeld, zodat sequence en pending snapshots
behouden blijven. Daarna worden de nieuwe credential en de afwijzing van de oude credential
gecontroleerd. Bij een fout worden env-file en DB-hash teruggezet en wordt de collector opnieuw met
de oude configuratie gerecreëerd. Er wordt geen credentialwaarde gelogd.

## Topologie

- `cockpit-db` staat alleen intern en heeft geen hostpoort.
- backend en frontend delen het externe Caddy-netwerk, zonder hostpoort.
- de VPS-2 collector heeft alleen externe HTTPS-probes en intern ingestverkeer;
- VPS 2 bevat geen Plenora-socket, filesystemmount of databasecredential;
- de root-owned VPS-1 host-helper leest exact het afgeschermde Backup v1 `status.json` en publiceert
  alleen gevalideerde technische velden naar `/run/plenora-cockpit/backup-status.json`;
- de observer-publisher mount exact deze 0644-boundarykopie, exact `host.json`, de socket en de
  least-privilege database-DSN;
- de observer luistert niet op een HTTP-poort en pusht `snapshot.v1` via authenticated HTTPS ingest.

Applicatiecontainers draaien non-root met read-only rootfs, `cap_drop: ALL`, no-new-privileges,
healthchecks en resourcegrenzen. PostgreSQL behoudt uitsluitend zijn datavolume.

## Eerste OWNER

Er is geen registratie en er zijn geen defaultcredentials. Gebruik na het starten van
`cockpit-backend` uitsluitend de interactieve helper:

```bash
bash deploy/bootstrap-owner.sh
```

De helper geeft de bootstrapwaarden alleen door aan `python -m app.cli create-owner`, controleert dat
`.env.deploy` niet is gewijzigd en weigert een tweede OWNER. Productie vereist HTTPS-origin,
Secure/SameSite Strict cookies, CSRF en rate limiting.

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
