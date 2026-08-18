"""Closed production query catalog; callers cannot supply SQL."""

DATABASE_QUERIES = {
    "version_major": "SELECT current_setting('server_version_num')::int / 10000",
    "size_bytes": "SELECT pg_database_size(current_database())",
    "connections_percent": (
        "SELECT count(*) * 100.0 / current_setting('max_connections')::int "
        "FROM pg_stat_activity WHERE datname = current_database()"
    ),
    "django_migration_count": "SELECT count(*) FROM public.django_migrations",
}


def query_for(metric: str) -> str:
    return DATABASE_QUERIES[metric]
