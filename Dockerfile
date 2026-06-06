# PostgreSQL 16 — single-container image for the ops_agent database.
#
# Build:
#   docker build -t ops-postgres .
#
# Run:
#   docker run -d \
#     --name ops-postgres \
#     --restart unless-stopped \
#     -e POSTGRES_USER=ops_user \
#     -e POSTGRES_PASSWORD=ops_password \
#     -p 5435:5432 \
#     -v ops-pgdata:/var/lib/postgresql/data \
#     ops-postgres
#
# Stop / remove:
#   docker stop ops-postgres && docker rm ops-postgres
#
# Connect (psql):
#   psql postgresql://ops_user:ops_password@localhost:5435/ops_agent

FROM postgres:16

# Default DB name baked into the image — user/password are supplied at runtime
ENV POSTGRES_DB=ops_agent

EXPOSE 5432
