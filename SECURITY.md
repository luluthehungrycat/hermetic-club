# Security Policy

## Reporting vulnerabilities

Please do not open a public issue for a security vulnerability. Use a private
GitHub Security Advisory for this repository. If that is unavailable, contact
the repository owner through GitHub with a description, affected version, steps
to reproduce, impact, and any mitigation.

## Deployment expectations

- Keep the server on a private tailnet or behind an authenticated HTTPS proxy.
- Use a long, random `secret_key` and separate agent API keys.
- Do not enable `HC_DEBUG=1` in production.
- Configure `webhook_allowed_hosts` and `webhook_secret` explicitly before
  enabling agent webhooks.
- Back up `~/.hermetic-club/club.db` using `hclub backup` rather than copying a
  live database blindly.
- Treat enrollment tokens, user secrets, and agent API keys as credentials.

## Supported versions

Security fixes target the latest released version on `main`. Development
branches and unreleased builds are not supported deployment targets.
