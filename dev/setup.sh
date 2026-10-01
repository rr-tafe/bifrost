#!/usr/bin/env bash
# Start the local SQL Server container and seed the BifrostDev database.
# Idempotent: re-running keeps existing passwords and data.
set -euo pipefail

DEV_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$DEV_DIR/.env"

gen_password() {
    # Meets SQL Server complexity rules (upper, lower, digit, symbol)
    echo "Bf1!$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
}

if [[ ! -f "$ENV_FILE" ]]; then
    cat >"$ENV_FILE" <<EOF
MSSQL_PORT=1433
MSSQL_SA_PASSWORD=$(gen_password)
BIFROST_DEV_SQL_USER=bifrost_admin
BIFROST_DEV_SQL_PASSWORD=$(gen_password)
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE"
fi

set -a
source "$ENV_FILE"
set +a

docker compose -f "$DEV_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d --wait

docker exec -i bifrost-mssql /opt/mssql-tools18/bin/sqlcmd -C -b \
    -S localhost -U sa -P "$MSSQL_SA_PASSWORD" \
    -v ADMIN_PASSWORD="$BIFROST_DEV_SQL_PASSWORD" <"$DEV_DIR/seed.sql"

echo "BifrostDev ready on localhost,${MSSQL_PORT}. Run the app with:"
echo "  set -a; source dev/.env; set +a; python main.py"
