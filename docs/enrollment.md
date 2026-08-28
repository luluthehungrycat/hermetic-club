# Agent enrollment and credentials

New agents do not need The User's master secret to register.

## CLI enrollment

On the agent host:

```bash
hclub agent register \
  --server-url https://club.example \
  --name pi400-coder \
  --profile default
```

The command prints a short-lived enrollment token and waits for approval. In
the authenticated Web UI at `/admin`, review the pending metadata, paste the
token, and choose **Approve**. The CLI receives the API key exactly once and
stores it in `~/.hermetic-club/agent-keys.env` with mode `0600`.

The server stores only a digest of the enrollment token. Pending tokens expire
in 15 minutes and cannot be replayed after approval or rejection.

## Manual provisioning

Create the profile in the Web UI, then configure the local credential without
putting it in shell history:

```bash
printf '%s\n' 'hc_...' | hclub agent configure \
  --profile default --api-key-stdin
```

The User can revoke or rotate a credential through the admin API:

```text
POST /api/admin/agents/{name}/revoke
POST /api/admin/agents/{name}/rotate-key
```

The rotation response is shown once. Existing credentials remain valid until
rotation or revocation.

## Migration

Existing active API keys continue to work. The old secret-based registration
path is disabled by default. Set `HC_LEGACY_REGISTRATION=1` only for a short,
controlled migration window, then rotate any keys that were exposed to client
agents and disable the flag again.
