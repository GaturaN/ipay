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
                    create_log_entry("ERR", "Payment Verification Failed")
                    frappe.throw("Payment Verification Failed")

                # Finalise via the shared path: record the Payment Entry, set
                # the request status (Success / Underpaid / Overpaid) and notify
                # the n8n callback exactly once.
                data = verification_response.get("data", {})
                result = finalize_payment(
                    docid, data, amount,
                    sales_invoice=inv, customer=user_id, customer_email=customer_email,
                )
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
