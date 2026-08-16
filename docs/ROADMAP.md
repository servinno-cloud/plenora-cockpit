# Roadmap

## Huidige stand — Sprint 0 Foundation

De technische foundation is geïmplementeerd: monorepo, FastAPI/SQLAlchemy/Alembic, PostgreSQL Compose,
Argon2id en server-side sessies, CSRF/rate-limitbasis, audit voor login/logout, read-only API-contract,
Next.js login en UNKNOWN-shell, plus een no-op collectorcontract. Echte observations,
collectorprobes en automatische incidenten starten pas in Sprint 1.

## V1 — Observe

Doel: veilig, zelfstandig en privacyarm inzicht zonder enige productieremediation.

Deliverables:

- zelfstandige repository, CI, dependency pinning en securityscan;
- Product/Environment/Target-configuratie;
- operatorauth met OWNER-bootstrap, secure sessions en auditlog;
- mTLS collector registration en rotation;
- hostcollector met vaste probes en begrensde lokale buffering;
- externe HTTPS-, container-, database-, disk-, backup-, mail- en release-observations;
- configureerbaar healthmodel en freshness;
- gededupliceerde OPEN/ACKNOWLEDGED/RESOLVED incidenten;
- retentie en hourly aggregates;
- responsive read-only UI;
- eigen health/readiness en scheduler heartbeat;
- Docker Compose/Caddy-deployment op VPS 1 zonder impact op Plenora;
- restore- en incident-engine tests;
- expliciete negatieve tests dat write/remediationroutes niet bestaan.

Acceptatie volgt de productspecificatie: HTTPS, veilige login, alle kernsignalen, incident lifecycle,
historie, geen secrets/persoonsdata en Cockpitrestart zonder Plenora-impact.

Niet in v1: logs, notifications via hetzelfde Plenora-mailkanaal, acties, LLM's en multi-region HA.

## V2 — Diagnose

Doel: sneller begrijpen waarom een incident bestaat, nog steeds zonder productiewijzigingen.

- gecorreleerde incidentcontext en dependency graph;
- gesanitized, allowlisted technische logs met korte retentie;
- runbooklinks en menselijke diagnose;
- Diagnostician-interface met capability `diagnose.incident`;
- evidence bundles zonder persoonsgegevens/secrets;
- onafhankelijk Cockpit-alertkanaal met eigen provider/failure domain;
- externe Cockpit-availabilitycheck vanaf tweede locatie;
- explainable policy-evaluatie en trendvergelijking.

AI blijft optioneel en krijgt uitsluitend begrensde incidentdata; output is advies, geen actie.

## V3 — Safe Actions

Doel: kleine, expliciet goedgekeurde operationele acties.

- capability-based Action Gateway;
- human approval, four-eyes voor high-risk acties;
- action plans, dry-run, idempotency en rollbackbewijs;
- kortlevende targetcredentials;
- eerste allowlisted acties zoals veilige test of staging-service restart;
- volledige audittrail en post-action verification;
- productieacties standaard uitgeschakeld.

Restore, migrations en databasewijzigingen blijven afzonderlijke high-risk capabilities en worden niet
impliciet toegestaan door een algemene operatorrol.

## V4 — Agent Team

Doel: gespecialiseerde agents binnen dezelfde capability- en approvalgrenzen.

- Watcher: observeert en prioriteert;
- Diagnostician: correleert evidence;
- Tester: voert goedgekeurde veilige tests uit;
- Developer: maakt change proposals/branches;
- Security: controleert dependencies en configuratie;
- Release: orkestreert expliciet goedgekeurde stagingreleases.

Agents krijgen geen gedeelde superusercredential. Iedere taak heeft een capabilityset, scope, budget,
expiry, approvalstatus en auditcorrelatie. Agentresultaten zijn reproduceerbare artifacts.

## V5 — Multi-product / Multi-host

Doel: meerdere Plenora-omgevingen en toekomstige producten centraal bewaken.

- Cockpit op onafhankelijke VPS/managed platform;
- collectors op meerdere hosts met certificaatrotation;
- environmentgroepen, ownership en tenant-onafhankelijke labels;
- schaalbare ingestpipeline en partitionering;
- per-product contractplugins zonder imports uit productrepositories;
- onafhankelijke off-site Cockpitbackups;
- HA, disaster recovery en externe status/alerting;
- SLO's, error budgets en fleet-wide trendanalyse.

## Implementatievolgorde v1

1. Contracts en threat model bevriezen.
2. Datamodel, migrations en retentie bouwen.
3. Operatorauth en auditlog bouwen en securitytesten.
4. Collector identity/ingest met mTLS bouwen.
5. Probes één voor één toevoegen met privacycontracttests.
6. Health- en incidentengine bouwen met deterministic fixtures.
7. Read-only UI bouwen.
8. Zelfmonitoring en deploymentisolatie toevoegen.
9. Restore-, failure- en VPS-acceptatietest uitvoeren.
10. Pas daarna v2-scope openen.

## Beslissingspoorten

Voor iedere volgende fase moet bewezen zijn:

- geen regressie in read-only grenzen;
- secrets en persoonsgegevens blijven buiten observations;
- datastoregroei voldoet aan budget;
- Cockpitfailure heeft geen Plenora-impact;
- collectorcompromise is begrensd en roteerbaar;
- nieuwe capabilities hebben expliciete threat model- en approvalreview.
