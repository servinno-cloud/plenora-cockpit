# Plenora Operations Cockpit

Plenora Operations Cockpit is een zelfstandig, read-only controlecentrum voor de technische
gezondheid van Plenora-omgevingen. Het product observeert applicaties en infrastructuur zonder
ervan afhankelijk te zijn om een storing te kunnen vaststellen.

Deze repository bevat voorlopig uitsluitend het v1-ontwerp. Er is nog geen frontend, backend,
collector, deployment of automatische actie geïmplementeerd.

## V1: Observe

V1 toont voor één of meer generiek gemodelleerde environments:

- externe HTTPS-availability en latency;
- container-, database- en hostgezondheid;
- backup- en restore-verificatiestatus;
- mailworker en geaggregeerde transactionele mailqueue;
- release- en migratie-informatie;
- gededupliceerde incidenten en beperkte historie.

V1 kan niets herstarten, deployen, migreren, herstellen of in Plenora wijzigen. De Cockpit
verzamelt standaard geen personeelsgegevens, mailinhoud, documenten, shifts of verlofdetails.

## Documentatie

- [Architectuur](docs/ARCHITECTURE.md)
- [Securitymodel](docs/SECURITY.md)
- [Observabilitycontract](docs/OBSERVABILITY-CONTRACT.md)
- [Incidentmodel](docs/INCIDENT-MODEL.md)
- [Roadmap](docs/ROADMAP.md)

## Kernbeslissingen

- afzonderlijke repository en releasecyclus, zonder imports uit Plenora;
- Next.js/TypeScript UI plus compacte Python/FastAPI API en collector;
- eigen PostgreSQL-datastore;
- host-side least-privilege collector, zonder Docker socket in web/API-containers;
- collectorprotocol is remote-ready met mTLS en environment-scoped identiteit;
- poll-based v1 met configureerbare intervallen en thresholds;
- observe-only capabilities; toekomstige acties zijn deny-by-default en auditplichtig;
- dezelfde VPS is alleen de eerste plaatsing, niet de uiteindelijke failure-domainscheiding.

## Beoogde repositorystructuur

```text
plenora-cockpit/
  README.md
  docs/
  apps/
    web/                 # Next.js UI
    api/                 # FastAPI API, auth en incident engine
    collector/           # host-side probe-runner
  packages/
    contracts/           # versieerbare JSON Schema/OpenAPI-contracten
  deploy/
    compose/
    caddy/
    systemd/
  tests/
```

## Sprint 0 lokale setup

Vereist: Docker Engine met Compose v2. Kopieer de placeholders en genereer een unieke secret:

```sh
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose config --quiet
docker compose up --build -d
```

Docker Compose past `$NAAM` en `${NAAM}` in `.env`-waarden als variabelen toe. Zet lokaal
gegenereerde secrets met een `$` daarom tussen enkelvoudige quotes, bijvoorbeeld
`COCKPIT_SECRET_KEY='letterlijke$secret'`. Gebruik in `COCKPIT_DATABASE_URL` daarnaast de
URL-gecodeerde vorm van gereserveerde wachtwoordtekens (`$` wordt `%24`). Wijzig secrets alleen
in de genegeerde lokale `.env`; commit deze nooit. Controleer na iedere wijziging met
`docker compose config --quiet` dat geen ontbrekende variabelen worden gemeld.

Voer migrations expliciet uit wanneer de backend niet via Compose start:

```sh
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
docker compose run --rm backend alembic check
```

Bootstrap precies één OWNER zonder password op de commandline of in Git:

```sh
read -rsp 'Owner password: ' COCKPIT_BOOTSTRAP_PASSWORD && export COCKPIT_BOOTSTRAP_PASSWORD
export COCKPIT_BOOTSTRAP_EMAIL=owner@example.com
docker compose run --rm backend python -m app.cli create-owner
unset COCKPIT_BOOTSTRAP_PASSWORD COCKPIT_BOOTSTRAP_EMAIL
```

De bootstrap weigert veilig zodra een operator bestaat. Er is geen registratie-endpoint of
standaardcredential.

Lokale URLs:

- frontend: `http://localhost:3100`;
- backendhealth: `http://localhost:8100/health`;
- API-documentatie is production-safe uitgeschakeld.

De containers blijven intern luisteren op frontendpoort `3000` en backendpoort `8000`. PostgreSQL
is alleen via het interne Compose-netwerk bereikbaar en publiceert geen hostpoort.

De lokale Compose-stack bouwt de backend met de `development`-target, waarin pytest en Ruff
aanwezig zijn. De afzonderlijke `production`-target bevat uitsluitend runtime-dependencies. De
frontend installeert met de lockfile tijdens de image-build; de runtimecommand start alleen Next.js.
Lokale `node_modules` en `.next` worden niet naar het image gekopieerd en er zijn geen frontend
bind mounts die de gebouwde dependencies overschrijven.

De backend gebruikt in beide targets `/app` als expliciete Python-module-root. Alleen de
development-target stuurt pytest- en Ruff-caches en de tijdelijke SQLite-testdatabase naar `/tmp`,
zodat de niet-rootgebruiker geen schrijfrechten op de applicatiemap nodig heeft.

## Tests en kwaliteitscontroles

```sh
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec frontend pnpm lint
docker compose exec frontend pnpm typecheck
docker compose exec frontend pnpm test -- --run
docker compose exec frontend pnpm build
PYTHONPATH=collector python -m pytest collector/tests
docker compose config --quiet
git diff --check
```

## Geïmplementeerde structuur

```text
plenora-cockpit/
  backend/       FastAPI, SQLAlchemy, Alembic, auth en tests
  frontend/      Next.js shell, login, UNKNOWN-dashboard en tests
  collector/     snapshot/types/mTLS interfaces en lege fixture
  docs/          goedgekeurde architectuurcontracten
  docker-compose.yml
  .env.example
```

Sprint 0 bevat bewust nog geen probes, Docker socket, incidentengine, agents, remediation, Caddy of
productiedeployment.
