import frappe
import logging
from ipay.ipay.main.utils.get_sid import get_sid
from ipay.ipay.main.utils.trigger_stk_push import trigger_stk_push
from ipay.ipay.main.utils.verify_mpesa_payment import verify_mpesa_payment
from ipay.ipay.main.utils.make_payment_entry import make_payment_entry
from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.send_callback import deliver_callback
import re

logger = logging.getLogger(__name__)


@frappe.whitelist(methods=["POST"])
def lipana_mpesa(
    docid, user_id, phone, amount, oid, customer_email, payment_request_type
):

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

    unwanted_characters = r"[-/;:~`!%^*<&_]"
    oid = re.sub(unwanted_characters, "", docid)
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

                # Process verification response
                data = verification_response.get("data", {})
                response_data = {
                    "order_id": data.get("oid"),
                    "transaction_amount": data.get("transaction_amount"),
                    "transaction_code": data.get("transaction_code"),
                    "payee": data.get("firstname"),
                    "payment_mode": data.get("payment_mode"),
                    "paid_at": data.get("paid_at"),
                    "telephone": data.get("telephone"),
                }

                create_log_entry(
                    "INF",
                    f"Payment received successfully with response_data: {response_data}",
                )
                logger.info("response_data: %s", response_data)

                # set status to success on the ipay request and show success message
                result_detail = (
                    f"KES {response_data.get('transaction_amount')} received from "
                    f"{response_data.get('payee')} ({response_data.get('telephone')}) — "
                    f"M-Pesa ref {response_data.get('transaction_code')}, {response_data.get('paid_at')}"
                )
                frappe.db.set_value(
                    "iPay Request",
                    docid,
                    {"status": "Success", "result_detail": result_detail},
                )
                frappe.db.commit()
                frappe.msgprint("Payment received successfully")

                # send post request to call back url
                deliver_callback(docid, response_data)

                # call function to create payment entry
                result = make_payment_entry(user_id, customer_email, inv, response_data, ipay_request=docid)

                if isinstance(result, dict):
                    status = result.get("status")
                    payment_entry = result.get("payment_entry")
                    message = result.get("message", "")

                    if status == "success":
                        logger.info(f"Payment Entry: {payment_entry}")
                        frappe.msgprint(
                            f"Payment Entry: <a href='/desk/payment-entry/{payment_entry}'>{payment_entry}</a>"
                        )

                    elif status == "duplicate":
                        logger.warning(
                            f"Duplicate Payment Entry detected: {payment_entry}"
                        )
                        frappe.msgprint(
                            f"Duplicate Payment Entry: <a href='/desk/payment-entry/{payment_entry}'>{payment_entry}</a>"
                        )

                    else:
                        logger.error(f"Payment Entry creation failed: {message}")
                        create_log_entry(
                            "ERR", f"Payment Entry creation failed: {message}"
                        )
                        frappe.msgprint("Failed to create Payment Entry")

                else:
                    logger.error("Unexpected response from make_payment_entry")
                    create_log_entry(
                        "ERR", "Unexpected response from make_payment_entry"
                    )
                    frappe.msgprint("Failed to create Payment Entry")

                return response_data

            else:
                create_log_entry("ERR", "Failed to initiate payment")
                # set status to 'Failed to complete request'
                frappe.db.set_value(
                    "iPay Request", docid, "status", "Failed to complete request"
                )
                frappe.db.commit()
                frappe.throw("Failed to initiate Payment")

        except Exception as error:
            logger.error("An error occurred during the payment process: %s", error)
            create_log_entry(
                "ERR", f"An error occurred during the payment proces: {error}"
            )
            # set status to error and record the reason for the operator
            frappe.db.set_value(
                "iPay Request",
                docid,
                {"status": "Error", "result_detail": str(error)},
            )
            frappe.db.commit()
            # frappe.throw("An error occurred during the payment process")
