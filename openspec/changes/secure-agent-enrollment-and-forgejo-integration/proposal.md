## Why

Hermetic Club currently requires a newly registering agent to possess The User's master secret, which unnecessarily exposes the highest-privilege credential to client agents and makes enrollment difficult to audit or revoke. Hermetic Club also has project handoff fields for Git remotes, but no supported local collaboration service for versioning skills, memories, projects, and handoff artifacts.

## What Changes

- Replace master-secret-based agent registration with an expiring, one-time pending-enrollment flow approved by The User.
- Add agent lifecycle management for pending registrations, activation, revocation, and API-key rotation.
- Add authenticated Web UI operations for reviewing and approving pending agents and configuring agent profiles.
- Add `hclub agent register` polling and `hclub agent configure` credential-storage workflows without exposing secrets in shell history.
- Persist approved agent credentials through the existing `~/.hermetic-club/agent-keys.env` convention when configured locally.
- Add an optional Forgejo deployment using Containerfile and Compose artifacts with host-side persistent storage.
- Add repository/project integration metadata and webhook handling without making Hermetic Club responsible for Git object storage.
- Add curated artifact export/import boundaries for skills, memories, projects, and handoffs; do not synchronize entire Hermes or Hermetic Club home directories.
- Add tests covering enrollment security, lifecycle behavior, CLI credential handling, repository integration, and Compose configuration.

## Capabilities

### New Capabilities
- `agent-enrollment`: Secure pending registration, User approval, profile provisioning, credential rotation, and revocation.
- `forgejo-integration`: Optional persistent Forgejo deployment and repository/project linkage for collaboration.
- `artifact-collaboration`: Explicitly scoped project, skill, memory, and handoff artifact exchange with reviewable imports.

### Modified Capabilities
- None. The repository currently has no canonical OpenSpec capability specs; authentication and handoff behavior are captured as requirements in the new capability specs.

## Impact

Affected areas include the Agent model and routes, authentication and configuration services, CLI commands, Web UI admin surfaces, database initialization/migrations, handoff/project APIs, webhook processing, documentation, and tests. New deployment files will add an optional Forgejo service with persistent host-mounted data, repository, and configuration directories. Existing programmatic clients using already-issued API keys remain compatible; only the unauthenticated registration contract changes.
