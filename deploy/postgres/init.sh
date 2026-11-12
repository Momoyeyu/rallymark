#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=business_password="$BUSINESS_DB_PASSWORD" --set=algorithm_password="$ALGORITHM_DB_PASSWORD" <<'SQL'
CREATE ROLE business LOGIN PASSWORD :'business_password';
CREATE ROLE algorithm LOGIN PASSWORD :'algorithm_password';
CREATE SCHEMA business AUTHORIZATION business;
CREATE SCHEMA algorithm AUTHORIZATION algorithm;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
