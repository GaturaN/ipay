# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

## Tests

The Python suites in `ipay/tests/` need a real Frappe site — every class subclasses
`frappe.tests.utils.FrappeTestCase`. The README's "pure/mock (no DB writes)" means they
write no rows, NOT that they run without a bench; that line has been misread more than once.
Run them with the command in `ipay/tests/README.md`, which also lists what each module
covers. The Vue app has its own suite (`yarn test` in `frontend/`).

## Branches and PRs

Branches are prefixed `feat/`, `fix/`, `chore/`, `refactor/` or `test/`. PRs target `main`;
`develop` is abandoned (behind `main`, nothing ahead).

## The money path

`ipay/ipay/main/utils/finalize_payment.py` is the single finalisation path — the in-session
STK flow, the hosted-checkout return, the manual Verify Payment action and the scheduled
backstop all end there. Put anything that must happen once per payment in it, not in a caller.

`constants.MONEY_ARRIVED` is the one set of statuses meaning the customer's money has
arrived; every charge, split and cancel guard keys off it. A status added to the doctype but
not to that tuple is how a guard silently stops guarding.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
