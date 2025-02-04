import requests
import hmac
import hashlib
import logging
import re
import frappe
from ipay.ipay.main.utils.ipay_logs import create_log_entry


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@frappe.whitelist()
def confirm_payment(docid, user_id, phone, amount, order, customer_email):
    # Log the received parameters
    logger.info(f"Received doc name: {docid}")
    logger.info(f"Customer Email: {customer_email}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Phone Number: {phone}")
    logger.info(f"Amount: {amount}")
    logger.info(f"OID: {order}")
    
    # Get vendor details
    vendor = frappe.get_doc("iPay Settings")
    vid = vendor.vendor_id.lower()   # Must be lowercase
    secret_key = vendor.api_key
    
    # Remove unwanted characters from oid
    unwanted_characters = r'[-/;:~`!%^*<&_]'
    oid = re.sub(unwanted_characters, '', order)
    logger.info(f"Cleaned OID: {oid}")
    
    try:
        # Generate hash for verification
        hash_value = create_hash(oid, vid, secret_key)
        verification_payload = {
            'vid': vid,
            'hash': hash_value,
            'oid': oid
        }
        logger.info(f"Verification Payload: {verification_payload}")
        
        # Make the verification API call
        verification_response = requests.post(
            'https://apis.ipayafrica.com/payments/v2/transaction/search',
            data=verification_payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        # Raise HTTP errors for bad responses
        verification_response.raise_for_status()
        logger.info(f"Verification Response: {verification_response.json()}")
        
        # Check if payment verification was successful
        if verification_response.status_code == 200:
            data = verification_response.json().get('data', {})
            transaction_code = data.get('transaction_code')
            transaction_amount = data.get('transaction_amount')
            
            # Validate payment amount
            try:
                transaction_amount_float = float(transaction_amount)
                amount_float = float(amount)
                if abs(transaction_amount_float - amount_float) < 1e-2:  # Allow small precision differences
                    logger.info("Payment verification successful")
                    # logging the transaction details
                    create_log_entry("INF", f"Payment confirmed for Ipay Request : {docid} - {data}")
                    # change the status of the iPay request
                    frappe.db.set_value("iPay Request", docid, "status", "Success")
                    frappe.db.commit()
                    
                    # parse the response_data
                    data = {
                       'order_id': data.get('oid'),
                       'transaction_amount': data.get('transaction_amount'),
                       'transaction_code': data.get('transaction_code'),
                       'payee': data.get('firstname'),
                       'payment_mode': data.get('payment_mode'),
                       'paid_at': data.get('paid_at'),
                       'telephone': data.get('telephone'),
                      }
                    
                    return {"status": "success", "message": "Payment verified", "data": data}
                  
                else:
                    logger.warning(f"Payment amount mismatch: Expected {amount_float}, Received {transaction_amount_float}")
                    return {"status": "error", "message": "Payment amount mismatch"}
                  
            except ValueError as ve:
                logger.error(f"Error parsing amounts for comparison: {ve}")
                return {"status": "error", "message": "Invalid amount format"}
              
        else:
            logger.warning("Payment not found")
            return {"status": "error", "message": "Payment not found"}
    
    except requests.RequestException as error:
        logger.error(f"Error during payment verification: {error}")
        return {"status": "error", "message": str(error)}
      
    except ValueError as ve:
        logger.error(f"Validation Error: {ve}")
        return {"status": "error", "message": str(ve)}

# Helper function to create HMAC hash
def create_hash(oid, vid, secret_key):
    data_string = f'{oid}{vid}'
    return hmac.new(secret_key.encode(), data_string.encode(), hashlib.sha256).hexdigest()
