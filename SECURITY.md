# Security Policy

## Supported Versions

Only the latest release on the `master` branch is actively maintained. Please ensure you are running the latest version before reporting a vulnerability.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

To report a security issue, please open a [GitHub Security Advisory](https://github.com/thehapyone/code-interpreter/security/advisories/new) (private disclosure). Include as much detail as possible:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations (optional)

You can expect an acknowledgement within 5 business days and a resolution or status update within 30 days.

## Security Considerations for Deployment

This service executes arbitrary code submitted by clients. Before deploying in a shared or production environment, review the following:

- **API Key authentication** — set `CODE_INTERPRETER_API_KEY` to restrict access to trusted clients only.
- **Network isolation** — run the container in an isolated Docker network; do not expose port 8000 to the public internet without authentication in front of it.
- **Non-root execution** — the container runs as a non-root user by default. Use `APP_UID`/`APP_GID` build args to match your host volume permissions.
- **Capability dropping** — the provided `docker-compose.yml` drops all Linux capabilities (`cap_drop: ALL`) and sets `no-new-privileges`. Keep these in place.
- **Resource limits** — use `SUBPROCESS_MAX_MEMORY_MB`, `SUBPROCESS_MAX_CPU_SECONDS`, and the compose resource limits to prevent runaway processes.
- **Execution timeouts** — `EXECUTION_TIMEOUT` (default 300 s) caps how long any single execution can run.
- **Environment isolation** — the server maintains an environment allowlist; host environment variables are not forwarded to executed code.
- **Package installation** — `pip` is available inside Python sessions. In shared deployments, consider whether arbitrary package installs are acceptable for your threat model.
