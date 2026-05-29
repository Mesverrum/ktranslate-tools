# ktranslate-tools

Operational tooling for [ktranslate](https://github.com/kentik/ktranslate/)
deployments — starting with a small admin sidecar and Grafana dashboards that
give SolarWinds/Zabbix-shaped admins a point-and-click interface for managing
SNMP polling groups, credentials, and device lists. No CLI or kubectl required.

Designed to plug into the multi-credential-group deployment pattern from
[KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana)'s
`multicontainer_example` branch, but the sidecar is reusable anywhere that
file layout is followed.

## Status

Pre-release; **thin vertical slice only**. The sidecar exposes:

- `GET  /api/groups` — list of credential groups parsed from `groups/*.env`
- `GET  /api/groups/{name}` — full detail for one group
- `PUT  /api/groups/{name}` — update one or more fields, regenerate configs, SIGUSR2 the matching poller (ktranslate's reload signal — SIGHUP terminates the process)

Grafana dashboards (Infinity-driven list + Volkov Labs Business Forms edit
page) are the next step. Once the backend round-trip is verified against a
running stack, the dashboards become a small JSON commit.

## Architecture

```
┌──────────────────────────┐         ┌─────────────────────────────┐
│   Grafana                │  HTTP   │  ktranslate-tools admin     │
│   - Infinity DS (list)   ├────────►│  - FastAPI (Python)         │
│   - Business Forms (edit)│         │  - /api/groups, /devices    │
└──────────────────────────┘         │  - shells out to existing   │
                                     │    generate-groups.sh +     │
                                     │    docker compose kill USR2 │
                                     └────────────┬────────────────┘
                                                  │
                          bind-mounts groups/, state/, scripts/,
                          compose-base.yaml, compose-groups.generated.yaml
                                                  │
                                                  ▼
                                     ┌─────────────────────────────┐
                                     │   KtransToGrafana checkout  │
                                     │   (the multicontainer_      │
                                     │   example branch layout)    │
                                     └─────────────────────────────┘
```

The sidecar is a typed wrapper around the existing `scripts/generate-groups.sh`
and `scripts/run-discovery.sh`. It never reinvents the generator — it shells
out — which keeps a single source of truth for the file format.

## Quickstart

Assumes you have a KtransToGrafana checkout on the `multicontainer_example`
branch and the stack is running.

```bash
# In your KtransToGrafana checkout
docker compose \
  -f compose-base.yaml \
  -f compose-groups.generated.yaml \
  -f /path/to/ktranslate-tools/examples/compose.yaml \
  up -d ktranslate-admin

# Verify
curl http://localhost:8000/api/groups | jq
curl http://localhost:8000/api/groups/cisco | jq

# Edit a field
curl -X PUT http://localhost:8000/api/groups/cisco \
  -H 'content-type: application/json' \
  -d '{"poll_interval_sec": 120}'

# Side-effects you should see:
#   - groups/cisco.env updated in place (POLL_INTERVAL_SEC=120)
#   - scripts/generate-groups.sh re-runs (config/poller-cisco.yaml regenerated)
#   - docker compose kill -s USR2 ktranslate_snmp_cisco fires (ktranslate's reload signal)
```

## What's coming next

- `POST /api/groups` / `DELETE /api/groups/{name}` — full group lifecycle
- `GET /api/groups/{name}/devices` etc. — device-level CRUD
- `POST /api/groups/{name}/discover` — trigger a discovery run on demand
- `POST /api/groups/{name}/test` — snmpwalk-based credential validation (the
  high-value bit for SolarWinds-comfortable users)
- `GET /api/groups/{name}/status` — last-discovery time, device count, last-poll, error counts
- Grafana dashboards consuming the above
- Auth (basic auth → OAuth via Grafana later)

## Why this exists

ktranslate is a great polling engine, but day-to-day operations (adding a
new credential group, rotating a community string, removing a decommissioned
device) currently require editing files on disk and running shell scripts.
That's fine for SREs but it's a non-starter for network operations teams
coming from SolarWinds, Zabbix, or PRTG, where everything is point-and-click.
This repo closes that gap without reinventing the polling engine.

For shops that already use NetBox as their network source of truth,
KtransToGrafana's `multicontainer_netbox` branch is probably a better fit —
NetBox already provides a polished CRUD UI for devices. This tooling is
aimed at the shops that don't (yet) run NetBox.
