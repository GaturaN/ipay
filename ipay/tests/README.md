# iPay tests

- `test_payment_core` — money-path unit tests for the functions behind the
  money-safety fixes: phone normalisation (charge the right number), amount
  matching + status resolution (classify a payment), and the reconcile search
  (never abandon a paid request).
- `test_desk_collect_links` — the role branch behind the desk's Collect Payments
  button, and structural guards on the iPay dashboard fixture.
- `test_charged_amount` — the amount an M-Pesa prompt charges is derived from the
  invoice's live outstanding server-side, never taken from the caller.

## Running

The bench-wide `run-tests` is currently broken by an unrelated app (`hrms`'s
`before_tests` hook imports a symbol not present in this Frappe version), so run
the modules directly:

```bash
cd frappe-bench
printf 'import unittest\nunittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(["ipay.tests.test_payment_core", "ipay.tests.test_payment_guards", "ipay.tests.test_desk_collect_links", "ipay.tests.test_charged_amount"]))\n' | bench --site <site> console
```

These tests are pure/mock (no DB writes), so they are fast and deterministic. That
means they write no rows — not that they run without a bench: every class subclasses
`FrappeTestCase`, whose `setUpClass` needs a live site.

The Vue app has its own suite: `yarn test` from `apps/ipay`.
