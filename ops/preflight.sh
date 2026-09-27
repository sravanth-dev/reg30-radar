#!/usr/bin/env bash
# Spike E - VPS preflight (ARCHITECTURE.md §10). READ-ONLY: it lists and inspects, and
# changes nothing. Run on the VPS and paste the output back:
#
#   bash ops/preflight.sh
#
# What it answers: free memory, disk and swap (sets the compose mem/cpu limits); the
# Postgres container's name, image (so its major version) and Docker network (sets
# TRADEBOT_DB_NETWORK, the host in DATABASE_URL and TRADEBOT_PG_MAJOR). It never prints
# container environment variables, which is where n8n's Postgres password lives.
set -u

section() { printf '\n== %s\n' "$1"; }

section "memory (MB)";  free -m
section "disk";         df -h /
section "swap";         swapon --show || echo "no swap"
section "cpus";         nproc
section "docker";       docker version --format 'client {{.Client.Version}} / server {{.Server.Version}}'
                        docker compose version
section "containers";   docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Networks}}'
section "networks";     docker network ls

section "postgres containers (name, image, networks)"
for c in $(docker ps --format '{{.Names}}'); do
  image=$(docker inspect --format '{{.Config.Image}}' "$c")
  case "$image" in
    *postgres*|*postgis*|*pgvector*)
      docker inspect --format '{{.Name}}  image={{.Config.Image}}  networks={{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c"
      ;;
  esac
done

section "memory used per container"
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
