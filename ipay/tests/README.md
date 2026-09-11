# iPay tests

- `test_payment_core` — money-path unit tests for the functions behind the
  money-safety fixes: phone normalisation (charge the right number), amount
  matching + status resolution (classify a payment), and the reconcile search
  (never abandon a paid request).
- `test_desk_collect_links` — the role branch behind the desk's Collect Payments
  button, and structural guards on the iPay dashboard fixture.
- `test_payment_guards` — the paid-but-unrecorded state (#111): that a payment which
  arrived is recorded rather than left looking unpaid, and that every charge and
  mutation guard refuses a request once its money has arrived.

## Running

The bench-wide `run-tests` is currently broken by an unrelated app (`hrms`'s
`before_tests` hook imports a symbol not present in this Frappe version), so run
the modules directly:

```bash
cd frappe-bench
printf 'import unittest\nunittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(["ipay.tests.test_payment_core", "ipay.tests.test_desk_collect_links", "ipay.tests.test_payment_guards"]))\n' | bench --site <site> console
```

These tests write nothing to the database, so they are fast and deterministic — but they
are not site-free. Every class subclasses `FrappeTestCase`, whose `setUpClass` reads the
site config and commits on `frappe.db` before any test body runs, so a site and a live
database are required even though no test uses them. That is why the recipe above goes
through `bench console`, and why CI cannot run these modules.

The Vue app has its own suite: `yarn test` from `apps/ipay`.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request targeting `main`:

- **Collect PWA tests (vitest)** — the Vue suite, the same `yarn test` as above
- **python: compile only — no tests** — `python -m compileall -q ipay`, which proves every
  Python file parses and nothing more

The second job is named for what it is because a green tick must not be read as "the Python
tests passed". **The modules on this page do not run in CI.** A GitHub runner has no bench and
no database, and `FrappeTestCase` needs both, so they remain a local step before opening a pull
request.

Putting them behind the gate takes one of two routes, neither done yet:

- a bench in CI — MariaDB and Redis, `bench init`, ERPNext installed (iPay's doctypes link to
  `Customer`, `Sales Invoice`, `Payment Entry` and `Account`), then a site; upstream's
  equivalent pipeline runs 12–18 minutes
- or splitting the pure assertions onto plain `unittest.TestCase`. Cheaper, but note it does not
  remove frappe entirely: these modules `import frappe` at module scope and import
  `ipay.ipay.main.utils.*`, which do too. It removes the need for a *site and a database*, not
  the need for frappe to be installed.
