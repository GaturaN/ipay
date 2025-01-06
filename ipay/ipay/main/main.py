import frappe 
import logging
from ipay.ipay.main.utils.get_sid import get_sid
from ipay.ipay.main.utils.trigger_stk_push import trigger_stk_push
from ipay.ipay.main.utils.verify_mpesa_payment import verify_mpesa_payment
from ipay.ipay.main.utils.make_payment_entry import make_payment_entry
import re
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@frappe.whitelist()
def lipana_mpesa(docid, user_id, phone, amount, oid, customer_email):
    # Log the received parameters
    logger.info(f"Received doc name: {docid}")
    logger.info(f"Customer Email: {customer_email}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Phone Number: {phone}")
    logger.info(f"Amount: {amount}")
    logger.info(f"OID: {oid}")
    
    # Variable to maintain the order id
    inv = oid
    logger.info(f"Invoice: {inv}")
    
    # Remove unwanted characters from oid
    # Expected output for oid: ACC-SINV-2024-00002 is ACCSINV202400002
    unwanted_characters = r'[-/;:~`!%^*<&_]' 
    oid = re.sub(unwanted_characters, '', oid)
    logger.info(f"Cleaned OID: {oid}")
    
    
    # get vendor details
    vendor = frappe.get_doc("iPay Settings")
    vid = vendor.vendor_id
    secret_key = vendor.api_key
    
    
    # check that secret_key & vid are not empty
    if not secret_key or not vid:
        raise ValueError("Secret key or vendor ID not set")
        
    try:
        # get session id
        response = get_sid(vid, secret_key, amount, oid, phone)
        sid = response.get('data', {}).get('sid')
        
        if not sid:
            raise ValueError("Failed to get session id")
            
        # After success in getting SID, trigger STK push 
        stk_response = trigger_stk_push(phone, sid, vid, secret_key)
        
        # verify the payment made by the stk push
        if stk_response.get('header_status') == 200:
            logger.info('Verifying Payment...')
            
            # Verify Payment
            verification_response = verify_mpesa_payment(oid, phone, vid, secret_key)
            
            if not verification_response:
                raise ValueError("Payment Verification Failed")
                
            if verification_response.get('header_status') != 200:
                raise ValueError("Payment Verification Unsuccessful")
                
            # Process verification response
            data = verification_response.get('data', {})
            response_data = {
                'order_id': data.get('oid'),
                'transaction_amount': data.get('transaction_amount'),
                'transaction_code': data.get('transaction_code'),
                'payment_mode': data.get('payment_mode'),
                'paid_at': data.get('paid_at'),
                'telephone': data.get('telephone'),
            }
            
            logger.info("response_data: %s", response_data)
            # set status to success on the ipay request and show success message
            frappe.db.set_value('iPay Request', docid, 'status', "Success")
            frappe.db.commit()
            frappe.msgprint("Payment received successfully")
            
            # send post request to call back url
            call_back_url = frappe.get_doc("iPay Settings").callback_url
            if call_back_url:
                # send post request to call back url
                requests.post(call_back_url, json=response_data)
                
            #TODO: call function to create payment entry
            payment_entry = make_payment_entry(user_id, customer_email, inv, response_data)
            
            if not payment_entry:
                raise ValueError("Failed to create Payment Entry")
                
            # log the payment entry name received from the function
            logger.info(f"Payment Entry: {payment_entry}")
            
            # Show the payment entry to the user and make it clickable to route to the payment entry
            frappe.msgprint(f"Payment Entry: <a href='/desk#Form/Payment Entry/{payment_entry}'>{payment_entry}</a>") 
            
            return response_data
        
        else:
            raise ValueError("Failed to initiate Payment")
            
    except Exception as error:
        logger.error("An error occurred during the payment process: %s", error)
        raise RuntimeError("An error occurred during the payment process")        


# # call the function when the script runs
# if __name__ == "__main__":
#     try:
#         result = lipana_mpesa(user_id, phone, amount, oid)
#         logger.info(f"Payment process completed successfully: {result}")
#     except Exception as e:
#         logger.error(f"Payment process failed: {e}")