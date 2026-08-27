# Forgejo deployment

This directory provides an optional local Forgejo service for Hermetic Club.

```bash
cd deploy/forgejo
cp .env.example .env
mkdir -p .forgejo/{data,repositories,config}
# Rootless Forgejo expects its service user to own the bind mounts.
chown -R 1000:1000 .forgejo
podman compose up -d --build
# or: docker compose up -d --build
```

Persistent host paths:

- `.forgejo/data`: database, attachments, logs, and service data
- `.forgejo/repositories`: Git repositories
- `.forgejo/config`: Forgejo configuration

Keep the service bound to localhost or a trusted Tailscale address, and put
TLS/authentication in front of it before exposing it beyond the private host.
Configure Hermetic Club with `HC_FORGEJO_ALLOWED_ORIGINS` and
`HC_FORGEJO_WEBHOOK_SECRET`, then configure a Forgejo webhook using the
`/api/integrations/forgejo/webhook` endpoint and an HMAC SHA-256 signature.

Do not delete the `.forgejo` directory when replacing the container. Back it
up as a unit, including the SQLite database and repository directory.
