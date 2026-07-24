# Working Time Agent Guide

## Scope

- This is a Frappe/ERPNext v16 app. Do not modify Frappe or ERPNext core.
- Keep project, billing and provisioning changes idempotent.
- External changes require an explicit preview and confirmation; never submit invoices or delete customer data automatically.

## Verification

Run the following checks before a commit:

```bash
docker compose -f ci/compose.yaml run --build --rm quality
docker compose -f ci/compose.yaml run --build --rm integration
docker compose -f ci/compose.yaml down --volumes --remove-orphans
```

The integration check creates a disposable Frappe v16 bench, installs ERPNext
and this app, migrates all DocTypes and custom fields, builds assets and runs
the app tests.
