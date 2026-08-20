# Securitymodel

## Operations Analyst boundary

Het globale AI-budget begrenst uitsluitend modelcalls. Onbekende pricing wordt fail-closed
geblokkeerd; ontbrekende usage houdt conservatief de volledige reservering als verbruik. Budget- of
providerfouten degraderen nooit monitoring, ingest, incidenten of notificaties.

De analysis-worker heeft alleen Cockpit PostgreSQL en provider-egress. Hij krijgt geen Docker socket,
SSH, shell/subprocess, filesystemmount, Plenora-netwerk/database, SMTP-secret, webhook of arbitrary
HTTP-tool. De vaste providerendpoint ontvangt uitsluitend het gesloten AnalysisContext. API-key en
modelconfiguratie staan alleen in de workeromgeving; logs, API en UI tonen die niet. Raw responses
worden gevalideerd en nooit opgeslagen. De centrale system instruction verbiedt acties, remediation,
persoonsinferentie en verzonnen zekerheid.

Production weigert HTTP-origins, onveilige cookies en fixturemode. VPS 1 exposeert geen observer-API:
de vaste publisher maakt alleen uitgaand HTTPS POST naar snapshot-ingest. Alleen deze VPS-1 container
heeft de lokale socket en technische monitorcredential; VPS 2 bezit geen Plenora-credentials. Ingest
controleert scoped bearer, environment, snapshot-ID en sequence. Secrets komen niet in observations.

## Uitgangspunten

De Cockpit bevat infrastructuurmetadata, incidenten en release-informatie en is daarmee een
hoogwaardig doelwit. Het ontwerp volgt least privilege, deny-by-default, gescheiden menselijke en
machine-identiteiten en volledige auditability. V1 is technisch read-only richting Plenora.

## Trust boundaries

1. Internet naar Caddy en Cockpit UI/API.
2. Operatorbrowser naar sessie- en CSRF-laag.
3. Collector naar het ingestendpoint.
4. Hostcollector naar lokale Docker-, database-, disk- en backupbronnen.
5. Cockpit API naar de eigen PostgreSQL.
6. Toekomstige Agent Gateway naar capabilities.

Plenora en Cockpit delen geen sessies, users, database, signing keys, mailprovidercredentials of
serviceaccounts.

## Operatorauthenticatie

- geen publieke registratie, password reset of uitnodigingsflow in de eerste bootstrap;
- eerste OWNER via een offline managementcommand met secret via stdin;
- Argon2id password hashing met configureerbare memory/time cost;
- secure, HttpOnly, SameSite=Strict sessioncookie met korte idle timeout en absolute timeout;
- CSRF-token op alle muterende Cockpitrequests;
- rate limiting per accountfingerprint en bron-IP, oplopende vertraging en generieke foutmelding;
- sessierotatie na login en privilegewijziging;
- recovery codes en WebAuthn/TOTP-ready credentialtabellen vanaf het domeinmodel;
- geen Plenora-authfallback: een Plenora-storing mag Cockpitlogin niet breken.

V1 ondersteunt OWNER, OPERATOR en VIEWER in het datamodel. De eerste UI mag alleen OWNER activeren.
VIEWER leest status/historie; OPERATOR mag incidenten acknowledge; OWNER beheert operators en
environmentconfiguratie. Geen rol heeft productieremediation in v1.

## Collectoridentiteit en protocolbeveiliging

Aanbevolen authenticatie is mTLS:

- eigen private Cockpit collector-CA;
- uniek clientcertificaat per collector/environment;
- servercertificaat via publieke PKI of interne CA;
- certificaat-subject wordt aan één collector-ID en environment gebonden;
- korte geldigheid, rotation overlap en directe revocationmogelijkheid;
- protocol accepteert uitsluitend TLS 1.2+ met moderne suites.

Daarnaast bevat iedere request een snapshot-ID, `generated_at` en monotone sequence. De API weigert
duplicaten, te oude timestamps, toekomstige timestamps buiten clock-skew en certificaten buiten hun
environment. Een scoped bearer token is alleen een tijdelijke bootstrapoptie en moet hashed-at-rest,
rotatable en nooit via UI uitleesbaar zijn. HMAC is niet de voorkeur omdat gedeelde secrets rotatie
en bronattributie moeilijker maken.

Op VPS 1 mag ingest uitsluitend via loopback/private netwerk bereikbaar zijn, maar mTLS blijft
ingeschakeld om het latere VPS-2-pad nu al te testen.

## Collector least privilege

Sprint 2 concretiseert deze grens met drie gesloten bronnen: een databasequerycatalogus zonder
runtime-SQL, een Mail-contract zonder persoonsgegevens en een Services-contract met vijf vaste
servicekeys. De lokale observer is uitsluitend een fixture, heeft een read-only root filesystem,
geen Docker socket en alleen GET-routes. Productie mag de fixture nooit als fallback gebruiken.

De collector heeft geen generieke shell/exec API. Probes zijn compile-time of lokaal root-owned
geconfigureerd en accepteren alleen bekende identifiers.

- Docker: alleen vaste read-endpoints via hardened proxy of een geïsoleerde hosthelper;
- database: aparte Cockpit probe-role met `CONNECT` en minimale readrechten op expliciete technische
  views/functions; geen applicatietabellen met persoonsgegevens;
- backups: read-only toegang tot `status.json` en optioneel een afzonderlijk
  `restore-verification-status.json`, niet tot dumpinhoud;
- disk: alleen filesystemstatistieken en directorygrootte;
- mail: alleen geaggregeerde counts/status via een technische view of sanitized endpoint;
- release: read-only image metadata en releasebestand.

De Docker socket is praktisch root-equivalent. Hij wordt nooit in web/API gemount en nooit read-write
aan een netwerkbereikbare Cockpitcomponent aangeboden. De gekozen proxyconfiguratie krijgt
regressietests die alle write-endpoints afwijzen.

## Secrets

- uitsluitend host secrets/environment files met 0600 of een latere secret manager;
- geen secretwaarden in databasevelden die via API-serializers bereikbaar zijn;
- API-responses tonen hoogstens `configured: true` en een credential-ID;
- logs redacteren Authorization, Cookie, tokens, DSNs en queryparameters;
- collectorcertificaat/private key is hostgebonden en niet onderdeel van applicatiebackups;
- afzonderlijke secrets per staging/productie/collector;
- geen secrets in images, Git, manifesten, snapshots of auditpayloads.

## Web- en API-hardening

- HTTPS-only, HSTS na gecontroleerde ingebruikname;
- CSP zonder `unsafe-eval`, frame-ancestors `none`, nosniff en strikte referrer policy;
- exacte allowed hosts/origins; geen wildcard-CORS;
- request body limits en schema-validatie met `extra=forbid`;
- output encoding en geen rendering van collector-HTML;
- paginatie en maximale tijdvensters voor historie;
- gescheiden rate limits voor login, UI API en collector ingest;
- dependency pinning, SBOM en image vulnerability scanning in CI;
- containers non-root waar mogelijk, read-only filesystem, dropped capabilities en
  `no-new-privileges`;
- database en API niet publiek gepubliceerd.

## Privacy en logging

Niet verzamelen of opslaan:

- namen, e-mailadressen en accountidentifiers van Plenora-gebruikers;
- mailadressen, onderwerp, body, activatie- of resettokens;
- notities, documenten, shifts en verlofdetails;
- SQL-resultaten met businessdata;
- onbeperkte applicatielogs.

Wel toegestaan: counts, technische service-ID's, versies, timestamps, durations, filesystempercentages,
queueleeftijden en opaque providerstatus. Vrije `message`-velden worden vermeden; codes plus
gestructureerde numerieke waarden hebben de voorkeur.

## Auditlog

Iedere menselijke securityrelevante handeling schrijft een append-only event met operator-ID,
actiecode, targettype/ID, resultaat, timestamp, request-ID en bron-IP-prefix. Geen passwords, tokens of
volledige request bodies. Minimale events:

- login success/failure, logout en sessierevocation;
- operator create/disable en rolwijziging;
- collector registration/rotation/revocation;
- environment- en thresholdwijziging;
- incident acknowledge;
- alle toekomstige capability requests en approvals.

Databasepermissions verhinderen UPDATE/DELETE door de normale applicatierol op auditevents. Latere
tamper evidence kan via hash chaining of externe append-only opslag worden toegevoegd.

## Toekomstige acties en Agent Gateway

Acties worden niet toegevoegd als extra API-knop op bestaande observe-routes. Elke actie vereist
later:

- expliciete capability;
- environment- en targetscope;
- human approval policy;
- korte taskcredential;
- input allowlist en idempotency key;
- dry-run waar mogelijk;
- volledige audittrail en resultaatbewijs;
- deny-by-default gateway die zelf geen root- of Dockercredentials bezit.

V1 registreert alleen `observe.*`; requests voor `restart.service`, `deploy.staging` of
`restore.backup` worden structureel geweigerd.

## Belangrijkste risico's

| Risico | V1-maatregel | Restrisico |
|---|---|---|
| Docker socket compromise | Geen socket in web/API; allowlisted hostcollector/proxy | Hostcollector blijft hoogwaardig doelwit |
| Cockpit en Plenora op VPS 1 vallen samen uit | Remote-ready collector en externe probe-interface | Volledig hostverlies pas na VPS 2 onafhankelijk zichtbaar |
| Gelekte collectorcredential | Uniek mTLS-certificaat, scope en revocation | Aanvaller kan binnen scope valse observations sturen |
| Snapshot bevat persoonsgegevens | Gesloten schema, allowlist, contracttests | Nieuwe probes vereisen privacyreview |
| Cockpitaccount overgenomen | Argon2id, rate limit, secure sessions, MFA-ready | MFA moet vóór brede operatorgroep worden geactiveerd |
| Incident flood/datastoregroei | Deduplicatie, rate limits, retentie en aggregatie | Nieuwe signalen moeten cardinaliteitsbudget respecteren |
| Cockpitdatabase verloren | Eigen backups en later off-site restoretests | Niet onderdeel van Plenora Backup v1 |
