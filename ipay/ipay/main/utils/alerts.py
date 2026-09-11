import frappe


class iPayDeclined(frappe.ValidationError):
    """An STK prompt the payer declined (cancelled / wrong PIN / insufficient funds).
    A business outcome, not a system fault — logged at INF so real errors stand out."""


def notify_money_at_risk(subject, message):
    """Surface a money-at-risk event (a payment confirmed at iPay but not recorded)
    where a human will see it: always an Error Log, plus an email to the configured
    operations address. Best-effort — alerting must never break the payment path."""
    try:
        # Keyword args on purpose: frappe.log_error is (title, message), and passing them
        # positionally put the long detail in `title` -> Error Log.method, a varchar(140).
        # That overflowed, threw, and was swallowed below, so the "always an Error Log"
        # promise above silently did not hold.
        frappe.log_error(title=f"iPay money-at-risk: {subject}"[:140], message=message)
    except Exception:
        pass

    recipient = frappe.db.get_single_value("iPay Settings", "alert_email")
    if not recipient:
        return
    try:
        frappe.sendmail(recipients=[recipient], subject=f"[iPay] {subject}", message=message)
    except Exception:
        pass
