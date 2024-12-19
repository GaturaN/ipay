import frappe 
import logging
from ipay.ipay.main.utils.get_sid import get_sid
from ipay.ipay.main.utils.trigger_stk_push import trigger_stk_push
from ipay.ipay.main.utils.verify_mpesa_payment import verify_mpesa_payment



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
            
        # After success in getting SID, trigger STK push 
        stk_response = trigger_stk_push(phone, sid, vid, secret_key)
        
        # verify the payment made by the stk push
        if stk_response.get('header_status') == 200:
            logger.info('Verifying Payment...')
            frappe.msgprint('Verifying Payment...')
            
            # Verify Payment
            verification_response = verify_mpesa_payment(oid, type, phone, vid, secret_key)
            
            if not verification_response:
                frappe.msgprint('Payment Verification Failed')
                
            if verification_response.get('header_status') != 200:
                frappe.msgprint('Payment Verification Unseccessful')
                
                # TODO: Process verification response
            
    except Exception as e:
        frappe.msgprint(str(e))
        logger.error(str(e))