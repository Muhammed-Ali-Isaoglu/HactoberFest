#!/bin/sh
# Creates the least-privilege reader role. The password comes from the environment, never from git.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE actiongate_reader LOGIN PASSWORD '${ACTIONGATE_READER_PASSWORD}'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE actiongate_reader SET default_transaction_read_only = on;
ALTER ROLE actiongate_reader SET statement_timeout = '3s';
ALTER ROLE actiongate_reader SET search_path = public;
SQL
