# iPay tests

- `test_payment_core` — money-path unit tests for the functions behind the
  money-safety fixes: phone normalisation (charge the right number), amount
  matching + status resolution (classify a payment), and the reconcile search
  (never abandon a paid request).
- `test_desk_collect_links` — the role branch behind the desk's Collect Payments
  button, and structural guards on the iPay dashboard fixture.
- `test_payment_guards` — the "paid but unrecorded" state, and every charge or
  mutation guard that must refuse a request once its money has arrived.
- `test_reconcile_schedule` — the reconcile backstop's polling schedule: the
  per-request backoff, the due gate, the per-run budget, and the money-at-risk
  alert.

## Running

The bench-wide `run-tests` is currently broken by an unrelated app (`hrms`'s
`before_tests` hook imports a symbol not present in this Frappe version), so run
the modules directly:

```bash
cd frappe-bench
printf 'import unittest\nunittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(["ipay.tests.test_payment_core", "ipay.tests.test_desk_collect_links", "ipay.tests.test_payment_guards", "ipay.tests.test_reconcile_schedule"]))\n' | bench --site <site> console
```

These tests are pure/mock (no DB writes), so they are fast and deterministic.

The Vue app has its own suite: `yarn test` from `apps/ipay`.
