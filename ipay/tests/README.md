# iPay tests

Money-path unit tests for the functions behind the money-safety fixes: phone
normalisation (charge the right number), amount matching + status resolution
(classify a payment), and the reconcile search (never abandon a paid request).

## Running

The bench-wide `run-tests` is currently broken by an unrelated app (`hrms`'s
`before_tests` hook imports a symbol not present in this Frappe version), so run
the module directly:

```bash
cd frappe-bench
printf 'import unittest\nunittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromName("ipay.tests.test_payment_core"))\n' | bench --site <site> console
```

These tests are pure/mock (no DB writes), so they are fast and deterministic.
