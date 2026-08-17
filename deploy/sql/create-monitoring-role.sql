\if :{?monitor_password}
\else
\quit
\endif

BEGIN;
CREATE ROLE plenora_cockpit_monitor LOGIN PASSWORD :'monitor_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
REVOKE ALL ON DATABASE :"monitor_database" FROM plenora_cockpit_monitor;
GRANT CONNECT ON DATABASE :"monitor_database" TO plenora_cockpit_monitor;
REVOKE ALL ON SCHEMA public FROM plenora_cockpit_monitor;
GRANT USAGE ON SCHEMA public TO plenora_cockpit_monitor;
GRANT SELECT ON TABLE public.alembic_version TO plenora_cockpit_monitor;
ALTER ROLE plenora_cockpit_monitor SET default_transaction_read_only = on;
COMMIT;

-- Removal (run deliberately as administrator):
-- REVOKE CONNECT ON DATABASE <database> FROM plenora_cockpit_monitor;
-- REVOKE ALL ON TABLE public.alembic_version FROM plenora_cockpit_monitor;
-- DROP ROLE plenora_cockpit_monitor;

