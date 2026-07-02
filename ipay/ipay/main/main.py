import frappe
import logging
from ipay.ipay.main.utils.get_sid import get_sid
from ipay.ipay.main.utils.trigger_stk_push import trigger_stk_push
from ipay.ipay.main.utils.verify_mpesa_payment import verify_mpesa_payment
from ipay.ipay.main.utils.finalize_payment import finalize_payment
from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.constants import clean_oid

logger = logging.getLogger(__name__)


@frappe.whitelist(methods=["POST"])
def lipana_mpesa(
    docid, user_id, phone, amount, oid, customer_email, payment_request_type
):
    # Direct HTTP callers (the desk "Prompt iPay" button — or an attacker) must
    # be an authorised operator acting on their own request. Background calls
    # (enqueued by prompt_mpesa / pay_prompt_mpesa) have no HTTP request and were
    # already authorised upstream, so they skip this gate.
    if getattr(frappe.local, "request", None):
        from ipay.ipay.main.utils.ipay_redirect import _require_operator, _require_request_access

        _require_operator()
        _require_request_access(docid)

    logger.info(
        f"Received doc name: {docid}, Customer Email: {customer_email}, "
        f"User ID: {user_id}, Phone Number: {phone}, Amount: {amount}, "
        f"OID: {oid}, Payment Request Type: {payment_request_type}"
    )

    # Re-validate at execution time: the request may have been cancelled
    # (split/discarded — docstatus 2) or already settled between enqueue and
    # pickup. Never push an STK in that case. The token paths already refuse a
    # cancelled request; this closes the operator/worker path too.
    state = frappe.db.get_value(
        "iPay Request", docid, ["docstatus", "status"], as_dict=True
    ) or {}
    if state.get("docstatus") == 2 or state.get("status") in ("Success", "Underpaid", "Overpaid"):
        create_log_entry(
            "INF",
            f"Skipping STK for {docid}: no longer chargeable "
            f"(docstatus={state.get('docstatus')}, status={state.get('status')})",
        )
        return {"status": "skipped", "message": "This request is no longer chargeable."}

    # Enforce the M-Pesa STK ceiling on EVERY path — the desk button calls this directly,
    # bypassing _enqueue_stk's check. Over the cap M-Pesa can't process the charge.
    if payment_request_type == "Mpesa Express":
        cap = frappe.utils.flt(frappe.db.get_single_value("iPay Settings", "mpesa_max_amount"))
        if cap and frappe.utils.flt(amount) > cap:
            create_log_entry("ERR", f"Amount {amount} exceeds the M-Pesa cap {cap} for {docid}")
            frappe.throw(
                f"M-Pesa isn't available for amounts over KES {cap:,.0f}. Please pay by card or via iPay."
            )

    # Persist the amount we're about to charge (the live outstanding at prompt time) so EVERY
    # finaliser — the in-session worker, the reconcile backstop, and the manual Verify Payment —
    # resolves Success/Under/Overpaid against what was actually charged, not a stale stored
    # amount that would misread a correct payment as Underpaid.
    frappe.db.set_value("iPay Request", docid, "amount", amount)

    # A retry after a terminal failure: clear the old Failed/Abandoned status + reason so any
    # poll shows this attempt as in-flight rather than the previous error. The SPA/token paths
    # already reset in _enqueue_stk (this is a no-op then); this covers the direct desk call.
    if state.get("status") in ("Failed", "Abandoned"):
        frappe.db.set_value("iPay Request", docid, {"status": "Pending", "result_detail": ""})
        frappe.db.commit()

    # set payment request type
    frappe.db.set_value(
        "iPay Request", docid, "payment_request_type", payment_request_type
    )
    frappe.db.commit()

    # log in frappe
    create_log_entry("INF", f"Payment prompt initiated for Ipay Request : {docid}")

    # Keep the Sales Invoice for the Payment Entry, but derive the iPay order id
    # from the iPay Request name so it is unique per request. (A balance/repeat
    # request for the same invoice then gets its own order id instead of a
    # colliding one, and bundles that span several invoices still have one oid.)
    inv = oid
    logger.info(f"Invoice: {inv}")

    oid = clean_oid(docid)
    logger.info(f"Cleaned OID (from request {docid}): {oid}")

    # get vendor details
    vendor = frappe.get_doc("iPay Settings")
    vid = vendor.vendor_id.lower()  # must be lowercase
    secret_key = vendor.api_key

    # check that secret_key & vid are not empty
    if not secret_key or not vid:
        create_log_entry("ERR", "Secret Key or vendor ID not set")
        frappe.throw("Secret key or vendor ID not set")

    # check if payemnt_request_tyoe is Mpesa Paybill
    if payment_request_type == "Mpesa Paybill":
        # get session id
        response = get_sid(vid, secret_key, amount, oid, phone, eml=customer_email, sales_invoice=inv)
        sid = response.get("data", {})

        if not sid:
            create_log_entry("ERR", "Failed to get session id")
            frappe.throw("Failed to get session id")

        # Extract account number
        account_number = sid.get("account", "")

        # Extract paybill number for MPESA
        mpesa_paybill = None
        for channel in sid.get("payment_channels", []):
            if channel.get("name") == "MPESA":
                mpesa_paybill = channel.get("paybill")
                break
        logger.info(f"Account Number: {account_number}, Paybill: {mpesa_paybill}")

        return mpesa_paybill, account_number, amount

    else:

        # The Express STK verify loop can take ~40s; never run it in a web worker.
        # On a direct HTTP call (the desk button), hand off to the long worker and
        # return immediately so the request can't time out (504). The enqueued run
        # has no request and falls through to the synchronous flow below.
        if getattr(frappe.local, "request", None):
            # Same request-scoped dedup as _enqueue_stk so the desk button (which otherwise
            # has no guard) can't fire a second STK while one is already queued/running.
            job = frappe.enqueue(
                "ipay.ipay.main.main.lipana_mpesa",
                queue="long",
                job_id=f"ipay_stk:{docid}",
                deduplicate=True,
                docid=docid,
                user_id=user_id,
                phone=phone,
                amount=amount,
                oid=inv,
                customer_email=customer_email,
                payment_request_type=payment_request_type,
            )
            if job is None:
                return {"status": "error", "message": "An M-Pesa prompt is already in progress for this request — wait for it to finish."}
            return {"status": "processing", "message": "M-Pesa prompt is being sent; it will confirm shortly."}

        try:
            # get session id
            response = get_sid(vid, secret_key, amount, oid, phone, eml=customer_email, sales_invoice=inv)
            sid = response.get("data", {}).get("sid")

            if not sid:
                create_log_entry("ERR", "Failed to get session id")
                frappe.throw("Failed to get session id")

            # After success in getting SID, trigger STK push
            stk_response = trigger_stk_push(phone, sid, vid, secret_key)

            # verify the payment made by the stk push
            if stk_response.get("header_status") == 200:
                create_log_entry("INF", "Verifying Payment")
                logger.info("Verifying Payment...")

                # Verify Payment
                verification_response = verify_mpesa_payment(
                    oid, phone, vid, secret_key
                )

                if not verification_response:
                    # Not confirmed within the verify window — the payment may still be
                    # in flight (the customer can take up to ~60s to enter their PIN).
                    # Leave the request Pending so reconcile_pending_payments finalises
                    # it; marking it Failed here would tell the operator it failed (and
                    # invite a double charge) while the money is still on its way.
                    create_log_entry("INF", "Not yet confirmed; leaving Pending for the reconciler")
                    return

                # Finalise via the shared path: record the Payment Entry, set
                # the request status (Success / Underpaid / Overpaid) and notify
                # the n8n callback exactly once.
                data = verification_response.get("data", {})
                # Allocate against the request's own invoice/amount (read server-
                # side inside finalize_payment), never the client-supplied oid —
                # the STK lookup already used the request's own order id, so the
                # money found is this request's. Resolve Success/Under/Overpaid
                # against the amount the STK actually charged (live outstanding at
                # prompt time), not the request's stored amount which may differ if
                # a member invoice settled separately — else a correct payment reads
                # as Underpaid.
                result = finalize_payment(docid, data, expected_amount=amount)
                response_data = result.get("response_data", {})
                create_log_entry(
                    "INF", f"Payment received with response_data: {response_data}"
                )
                logger.info("response_data: %s", response_data)

                payment_entry = result.get("payment_entry")
                if result.get("status") in ("success", "duplicate"):
                    frappe.msgprint(
                        f"Payment received ({result.get('request_status')}). "
                        f"Payment Entry: <a href='/app/payment-entry/{payment_entry}'>{payment_entry}</a>"
                    )
                else:
                    create_log_entry(
                        "ERR", f"Payment Entry creation failed: {result.get('message')}"
                    )
                    frappe.msgprint(
                        "Payment received, but creating the Payment Entry failed. "
                        "It will be retried automatically."
                    )

                return response_data

            else:
                create_log_entry("ERR", "Failed to initiate payment")
                frappe.db.set_value("iPay Request", docid, "status", "Failed")
                frappe.db.commit()
                frappe.throw("Failed to initiate Payment")

        except Exception as error:
            logger.error("An error occurred during the payment process: %s", error)
            create_log_entry(
                "ERR", f"An error occurred during the payment proces: {error}"
            )
            # set status to Failed and record the reason for the operator
            frappe.db.set_value(
                "iPay Request",
                docid,
                {"status": "Failed", "result_detail": str(error)},
            )
            frappe.db.commit()
            # frappe.throw("An error occurred during the payment process")
