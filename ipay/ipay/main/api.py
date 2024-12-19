import frappe 
import logging
from ipay.ipay.main.utils.get_sid import get_sid



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@frappe.whitelist()
def lipana_mpesa(user_id, phone, amount, oid, type='cart'):
    
    # get vendor details
    vendor = frappe.get_doc("iPay Settings")
    vid = vendor.vendor_id
    secret_key = vendor.api_key
    
    # check that secret_key & vid are not empty
    if not secret_key or not vid:
        frappe.msgprint("Please configure your iPay Settings")
        
    try:
        # get session id
        response = get_sid(vid, secret_key, amount, oid, phone)
        sid = response.get('data', {}).get('sid')
        frappe.msgprint(sid)
        
        if not sid:
            frappe.msgprint("Failed to get session id")
            
            
    except Exception as e:
        frappe.msgprint(str(e))
        logger.error(str(e))