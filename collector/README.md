# Observe-only collector

`src.runner.run_once(config, state_path)` voert vaste Web-, Backup- en Hostprobes uit en pusht
een `snapshot.v1` naar ingest. Niet-afgeleverde snapshots blijven lokaal begrensd tot 50 items.

De Compose-service ontvangt identity, ingestcredential en vaste URLs via environmentvariabelen. Het
enige bronbestand is `/backup/status.json`, als smalle read-only bind mount. State staat in een eigen
volume. De collector heeft geen Docker socket, shell execution, SSH, netwerkdaemon of
remediationmogelijkheden. Productietransport hoort achter mTLS te staan.
