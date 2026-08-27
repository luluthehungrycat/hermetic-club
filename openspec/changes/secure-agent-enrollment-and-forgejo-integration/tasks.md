## 1. Enrollment data model and security primitives

- [x] 1.1 Add the pending enrollment model with token digest, expiry, state, requested metadata, delivery marker, and audit timestamps.
- [x] 1.2 Add secure token/key helpers, constant-time comparisons, expiry checks, and explicit legacy-registration configuration.
- [x] 1.3 Add database startup compatibility for the new tables and fields without invalidating existing active agents.

## 2. Enrollment and lifecycle API

- [x] 2.1 Replace default secret-based registration with pending enrollment creation and validation.
- [x] 2.2 Add pending enrollment status polling and one-time credential delivery.
- [x] 2.3 Add User-authenticated pending-list, approve, reject, revoke, and rotate endpoints.
- [x] 2.4 Preserve active bearer-key verification and add repository-origin validation helpers.

## 3. CLI and Web UI provisioning

- [x] 3.1 Add `hclub agent register` polling workflow that displays a one-time approval code and stores the returned credential safely.
- [x] 3.2 Add `hclub agent configure` with stdin-based credential input and owner-only key-file permissions.
- [x] 3.3 Add admin UI/API integration for reviewing pending agents and configuring profiles.
- [x] 3.4 Document enrollment, manual provisioning, revocation, rotation, and migration behavior.

## 4. Forgejo deployment and integration

- [x] 4.1 Add Forgejo Containerfile, Compose file, environment example, persistent host-volume layout, health check, and operational documentation.
- [x] 4.2 Add repository/project linkage metadata and API support for allowed Forgejo origins.
- [x] 4.3 Add signed Forgejo webhook validation and structured repository/PR activity recording.
- [x] 4.4 Extend Git-backed handoff responses with safe repository metadata while preserving notes-only handoffs.

## 5. Curated artifact collaboration

- [x] 5.1 Add artifact manifest and provenance data structures/API primitives for explicit export/import sets.
- [x] 5.2 Add import preview and explicit activation records without writing into agent homes automatically.
- [x] 5.3 Add repository and artifact permission checks by agent identity.

## 6. Verification

- [x] 6.1 Add unit and API tests for enrollment expiry, replay, approval, rejection, one-time delivery, revocation, and rotation.
- [x] 6.2 Add CLI tests for stdin configuration, permissions, and token polling behavior.
- [x] 6.3 Add Forgejo URL/webhook, handoff, artifact provenance, and permission tests.
- [x] 6.4 Validate OpenSpec artifacts, run targeted tests and compile checks, and validate Compose configuration; record unrelated pre-existing full-suite/lint failures.
