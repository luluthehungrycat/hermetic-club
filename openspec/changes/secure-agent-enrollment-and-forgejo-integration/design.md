## Context

See `proposal.md` for motivation and scope. The current service is a FastAPI application with SQLAlchemy models, SQLite-compatible database initialization, a simple bearer-based User secret, agent API-key authentication, a Jinja Web UI, and a Typer-style CLI. Handoff records already contain optional Git URL and branch fields. No canonical OpenSpec capability specs existed before this change.

## Goals / Non-Goals

**Goals:**

- Add a secure pending-enrollment lifecycle while preserving existing bearer-key authentication for active agents.
- Make approval and lifecycle operations available through authenticated API/Web UI surfaces.
- Provide CLI support for enrollment polling and safe local credential storage.
- Provide an optional Forgejo Compose deployment with host-persistent state.
- Validate and associate repository metadata and Forgejo webhook events without embedding Git storage in Hermetic Club.
- Establish explicit artifact boundaries and review metadata for future synchronization workflows.

**Non-Goals:**

- Replacing the existing User authentication mechanism with a full identity provider.
- Implementing a complete Forgejo clone, Git transport proxy, or in-process Git server.
- Automatically synchronizing arbitrary `~/.hermes` or `~/.hermetic-club` contents.
- Automatically executing or activating imported skills, memories, or policies.
- Building a full browser Git client in this change.

## Decisions

### 1. Enrollment is a pending database record

Add a pending enrollment model with an opaque identifier, token digest, metadata, expiration, state, and delivery marker. Registration creates only this record; approval creates the active Agent and a one-time delivery credential. This keeps the User secret out of agent bootstrap and makes expiry, replay prevention, and audit behavior testable.

A simpler signed-token-only approach was rejected because it would not provide server-side single-use tracking or a reliable approval audit trail.

### 2. API keys remain hash-only in the database

Continue storing only SHA-256 API-key digests. The plaintext credential is generated at approval time, delivered once to the pending client, and never returned by normal agent or admin listing endpoints. Existing active bearer keys remain compatible.

Public-key enrollment is reserved as a future protocol extension; this change keeps the existing credential format while removing the master-secret dependency.

### 3. User-authenticated API is the first Web UI integration boundary

The existing User bearer secret remains the authenticated boundary for admin routes. Add JSON endpoints suitable for the current Jinja UI and document the UI action. This avoids introducing a new session/cookie framework while still allowing a future Web UI session layer.

### 4. Forgejo is an optional external service

Use the official Forgejo image in a repository-owned Compose deployment. Mount separate host directories for `/data`, `/var/lib/gitea`, and `/etc/gitea` (or their supported Forgejo equivalents), and expose configuration through an example environment file. Hermetic Club stores only links and webhook activity metadata.

Bundling a Git server inside the FastAPI image was rejected because it would couple independent upgrade and backup lifecycles and expand the trusted computing base.

### 5. Repository URLs are allowlisted

Repository links and webhook repository identities are accepted only for configured Forgejo origins, with HTTPS and SSH URL forms normalized safely. Generic arbitrary remote URLs are rejected for the new integration metadata, while existing legacy handoff records remain readable for backward compatibility.

### 6. Artifact exchange is manifest-first

Add an artifact manifest/provenance model and API primitives rather than copying files or modifying local agent homes. Activation is deliberately represented as an explicit approved event; actual filesystem installation remains a later integration task.

## Risks / Trade-offs

- [Risk] Existing clients call `/api/agents/register` with the User secret and expect an immediate API key. → Preserve a narrowly scoped legacy compatibility mode behind an explicit configuration flag, defaulting to disabled, and update documentation/tests to use enrollment.
- [Risk] SQLite schema creation does not migrate existing deployments automatically. → Add nullable/defaulted columns and startup-safe table creation; document that production deployments should use a migration tool before future destructive changes.
- [Risk] One-time delivery can fail after approval if the CLI disappears. → Provide User-only credential rotation and a pending delivery status; never re-display the original secret.
- [Risk] Forgejo data ownership and UID/GID mismatches can prevent startup. → Document host directory creation, permissions, and configurable UID/GID; health-check the service after startup.
- [Risk] Webhook payloads can contain prompt injection or misleading commands. → Store structured metadata only, validate signatures, and treat payload text as untrusted data.
- [Risk] Artifact imports can poison agent behavior. → Require manifest/diff review and explicit activation; do not auto-install from Git events.

## Migration Plan

1. Deploy the database/model changes and keep existing active agent keys valid.
2. Set `HC_LEGACY_REGISTRATION=1` only during a controlled migration window if existing automation still needs secret-based registration.
3. Move clients to `hclub agent register` and approve them through the User admin flow.
4. Disable the legacy flag and rotate any credentials that were exposed to client agents.
5. Start Forgejo with the repository Compose files and verify the health endpoint and host-mounted directories.
6. Link repositories to projects/handoffs and configure signed webhooks.
7. Roll back application code by disabling new routes if necessary; do not delete host-mounted Forgejo data during rollback.
