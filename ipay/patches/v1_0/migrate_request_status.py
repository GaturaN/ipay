import frappe

# Map the old, overloaded iPay Request statuses onto the refined taxonomy
# (Pending / Success / Underpaid / Overpaid / Failed / Abandoned).
#
#   ""                          -> Pending   (no explicit pending state before)
#   "Error"                     -> Failed    (merged failure states)
#   "Failed to complete request"-> Failed
#   "Amount Mismatch"           -> Overpaid  (legacy catch-all; treat the
#                                             excess as customer credit. None
#                                             exist in practice, but map it so
#                                             no row keeps an out-of-list value)
STATUS_MAP = {
    "": "Pending",
    "Error": "Failed",
    "Failed to complete request": "Failed",
    "Amount Mismatch": "Overpaid",
}


def execute():
    for old, new in STATUS_MAP.items():
        frappe.db.sql(
            "UPDATE `tabiPay Request` SET status = %s WHERE IFNULL(status, '') = %s",
            (new, old),
        )
