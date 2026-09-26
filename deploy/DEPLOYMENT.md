# Backend release gate

`hetzner-deploy.yml` runs only after the main-branch Cloud Readiness workflow
succeeds and separately verifies CI success for that exact commit. The SSH key is
restricted to a root-owned forced command: no interactive shell, forwarding or
PTY. Host key checking is mandatory. Secrets remain in GitHub Secrets and protected
server files; the source/image is built from the public commit archive, never from
the live directory containing secrets. Server source scripts are installed by an
operator, not replaced by a repository release.

The server verifies the current main SHA, obtains a deployment lock, builds an image
tagged with the full commit and runs Compose using its immutable image ID. A
Recovery-State predeploy backup is required. Writers stop before migration; API,
monitor, scanner, Telegram and backup start sequentially with readiness gates.
No old/new writers overlap. This is a brief stop/start deployment, not zero downtime.

On readiness failure the previous Compose file/image is restored, preserving the
current database (never rewind fills). Automatic schema-version changes are blocked
until an operator has reviewed compatibility and rollback; same-schema migrations
run idempotently on every deployment. A failed rollback requires operator recovery.
The last release records commit/new/previous image IDs. Keep previous images and
source temporarily; review disk use before pruning. CI and host locks prevent
concurrent releases. Production remains provisional until live-market validation.
