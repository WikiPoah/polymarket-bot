<!-- File-Version: 1.0.0 -->
# Security and configuration audit

Date: 2026-08-09

## Scope

Reviewed current environment-variable handling, HTTP clients, provider
authentication, request timeouts, exception and logging behavior, dashboard
exposure, response headers, ignored credentials, and pinned dependencies.

## Validation

Commands were run from the repository root:

```bash
.venv/bin/python -m pip_audit -r requirements.txt
.venv/bin/python -m pip_audit -r requirements-dev.txt
rg -n --hidden --glob '!.git/**' --glob '!.venv/**' \
  '(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})' .
```

Both dependency audits reported no known vulnerabilities. The credential scan
found no matching secrets. `.env` is ignored and `.env.example` contains only
empty placeholders and a public collection identifier.

## Findings

- External HTTP requests use HTTPS and bounded timeouts.
- TLS verification is not disabled.
- GDELT and Media Cloud credentials are sent in authorization headers and are
  not written to logs or stored datasets by the reviewed paths.
- The dashboard binds to `127.0.0.1` by default, is read-only, escapes displayed
  intelligence data, and sets a restrictive content security policy.
- Dashboard responses previously lacked an explicit no-store cache policy and
  exposed the default Python HTTP server signature. Both were corrected.
- No dependency change was required.

## Limitations

This was a source and dependency audit, not a penetration test. Provider-side
security, Git history outside the current working tree, deployment hardening,
and public hosting were not assessed. The dashboard remains intended only as a
local operational interface and has no authentication layer.
