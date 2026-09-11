import frappe


def execute():
    """Give the requests that predate the poll schedule a due time, so the first sweeps
    after this deploys work through the existing backlog oldest-first instead of in
    arbitrary order.

    Stamped to `creation`, which makes a request that is closest to the end of the 24-hour
    reconcile window — and so closest to being abandoned — the most urgent. Idempotent and
    non-destructive: only rows with no next_poll_at are touched, so re-running it never
    resets a request the backstop has already scheduled.

    Correctness does not depend on this having run: the sweep treats an unset next_poll_at
    as due (reconcile_payments._due_or_filters), so an unstamped request is polled anyway.
    """
    rows = frappe.get_all(
        "iPay Request",
        filters={
            "docstatus": 1,
            "callback_delivered": 0,
            "next_poll_at": ["is", "not set"],
        },
        fields=["name", "creation"],
    )
    for row in rows:
        frappe.db.set_value(
            "iPay Request", row.name, "next_poll_at", row.creation, update_modified=False
        )
