# Production deployment

## Operations Analyst

Configureer de analyst uitsluitend met de root-only helper. Deze leest de OpenAI API-key verborgen,
schrijft `.env.deploy` atomisch als root-owned mode `0600`, valideert Compose zonder configuratie of
secret naar de terminal te schrijven en laat de analyst standaard uitgeschakeld:

```bash
cd /opt/plenora-cockpit/app
sudo bash deploy/configure-analysis.sh
```

Voer de eerste productioncontrole disabled-first uit; in deze fase doet de worker geen modelcall:

```bash
docker compose --env-file .env.deploy -f docker-compose.deploy.yml config --quiet
docker compose --env-file .env.deploy -f docker-compose.deploy.yml build \
  cockpit-backend cockpit-frontend cockpit-analysis-worker
docker compose --env-file .env.deploy -f docker-compose.deploy.yml run --rm \
  cockpit-backend alembic upgrade head
docker compose --env-file .env.deploy -f docker-compose.deploy.yml up -d \
  cockpit-backend cockpit-frontend cockpit-analysis-worker
docker compose --env-file .env.deploy -f docker-compose.deploy.yml ps cockpit-analysis-worker
docker compose --env-file .env.deploy -f docker-compose.deploy.yml exec -T \
  cockpit-backend alembic current
```

Controleer daarna authenticated incidentdetail, `/incidenten`, `/historie`, ingest en notificaties.
Schakel pas na deze controles expliciet in en recreate uitsluitend de analysis-worker zodat de nieuwe
procesenvironment wordt geladen:

```bash
sudo bash deploy/configure-analysis.sh --enable
docker compose --env-file .env.deploy -f docker-compose.deploy.yml up -d \
  --force-recreate cockpit-analysis-worker
docker compose --env-file .env.deploy -f docker-compose.deploy.yml ps cockpit-analysis-worker
```

Bestaande analysisconfiguratie wordt alleen met `--force` vervangen; dat zet enabled opnieuw op
`false`. Alleen `cockpit-analysis-worker` ontvangt de providerkey. Monitoring, incidenten en
notificaties blijven ook bij disabled provider of providerfailure functioneren.

Het gedeelde AI-budget is standaard `COCKPIT_AI_MONTHLY_BUDGET_EUR=100`. De versioned catalogus
rekent de officiële USD-tokenprijzen reproduceerbaar om met de vaste conservatieve accountingrate
`COCKPIT_AI_USD_TO_EUR_RATE=1.00`; runtime gebruikt geen live wisselkoers. Voer migratie
`0008_ai_usage_budget` uit voordat backend of analysis-worker met Sprint 6B start.

### Veilige end-to-end analyst-test

Na migratie `0010_safe_analysis_test_harness` kan een OWNER-beheerder één synthetische analyse via
de normale budget-, worker-, Responses API-, validatie- en usageketen uitvoeren. De request bevat
uitsluitend vaste technische TEST-feiten, heeft geen incidentkoppeling en maakt geen observations of
notificationevents. De backend-CLI ontvangt geen providerkey; alleen de bestaande analysis-worker
voert de modelcall uit.

```bash
docker compose --env-file .env.deploy -f docker-compose.deploy.yml exec -T \
  cockpit-backend python -m app.cli test-analysis
docker compose --env-file .env.deploy -f docker-compose.deploy.yml exec -T \
  cockpit-backend python -m app.cli show-last-test-analysis
```

De eerste opdracht meldt uitsluitend voltooiing of een veilige foutcode. De tweede toont alleen het
gevalideerde structured resultaat en de usage/kostensamenvatting, nooit prompt, raw providerresponse
of secret. Optionele cleanup verwijdert alleen het structured testresultaat en de opgeslagen
testcontext; de requestidentiteit en werkelijk geboekte usage/kosten blijven behouden:

```bash
docker compose --env-file .env.deploy -f docker-compose.deploy.yml exec -T \
  cockpit-backend python -m app.cli cleanup-test-analyses
```

## Incident-e-mailnotificaties

Configureer op de Cockpit VPS in root-owned `.env.deploy` uitsluitend runtimewaarden:
`COCKPIT_NOTIFICATION_EMAIL_TO`, `COCKPIT_NOTIFICATION_EMAIL_FROM`,
`COCKPIT_NOTIFICATION_SMTP_HOST`, `COCKPIT_NOTIFICATION_SMTP_PORT`, optioneel username/password en
`COCKPIT_NOTIFICATION_SMTP_STARTTLS`. Zonder complete basisconfiguratie blijven Cockpit en ingest
normaal werken en toont de UI `E-mail: niet geconfigureerd`. De afzonderlijke notification-worker
heeft alleen PostgreSQL en SMTP-egress; geen Docker socket, Plenora-netwerk of remediationcapability.

Voor Resend SMTP configureert de root-only helper ontvanger, afzender en verborgen API-key zonder
credentials in shellhistory of argv. Bestaande configuratie wordt alleen met `--force` vervangen:

```bash
cd /opt/plenora-cockpit/app
sudo bash deploy/configure-notifications.sh
```

Upgradevolgorde: maak eerst een databasebackup, haal de release op, bouw de images, voer
`alembic upgrade head` uit en start daarna backend, frontend, collector en notification-worker.

Sprint 3 gebruikt twee losse deployments. VPS 2 bevat Cockpit onder `/opt/plenora-cockpit/app` met
`docker-compose.deploy.yml`. VPS 1 bevat de Plenora observer-publisher onder
`/opt/plenora-observer/app` met `docker-compose.observer.yml`. Beide env-bestanden zijn
niet-getrackt en mode `0600`. Deze repository voert geen deployment, DNS- of Caddy-mutatie uit.

Maak op VPS 2 de observeridentity, registreer en verifieer die in Cockpit, en maak de transferbundle:

```bash
cd /opt/plenora-cockpit/app && sudo bash deploy/provision-observer-identity.sh
```

Draag de bundle via het bestaande beheer-SSH-pad eenmalig over naar root op VPS 1:

```bash
sudo scp -p .observer-identity.provision root@pilot.plenora.nl:/opt/plenora-observer/app/.observer-identity.provision
```

Maak op VPS 1 daarnaast de database-DSN; gebruik nooit de Plenora-applicatiecredential:

```bash
cd /opt/plenora-observer/app && sudo bash deploy/create-monitoring-role.sh
```

De helper genereert zelf een 32-teken hexcredential en bewaart alleen tijdelijk een mode-0600
database-DSN in `.observer-database.provision`. `deploy/init-observer-env.sh` neemt die DSN eenmalig
over in `.env.observer` en verwijdert daarna het provisioningbestand.

Initialiseer daarna op VPS 1 `.env.observer` als root, zonder secrets in shellhistory of editor:

```bash
cd /opt/plenora-observer/app && sudo bash deploy/init-observer-env.sh
```

De helper zet het vaste productionnetwerk, Docker-GID, vijf containernamen en de Cockpit-ingest-URL.
Environment-ID, observer-ID/token en de read-only monitoring-DSN komen uitsluitend uit beide
root-owned mode-0600 provisioningbundles. Na succesvolle Composevalidatie schrijft de helper
`.env.observer` atomisch als mode `0600` en verwijdert hij beide eenmalige bundles.

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
