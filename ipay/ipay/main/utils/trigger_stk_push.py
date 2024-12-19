import requests
import hmac
import hashlib
import logging
import frappe  

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def trigger_stk_push(phone: str, sid: str, vid: str, secret_key: str) -> dict:
    try:
        # Generate the data string for hashing
        data_string = f'{phone}{vid}{sid}'
        
        # Generate the hash using HMAC SHA-256
        hash_value = hmac.new(secret_key.encode(),data_string.encode(),hashlib.sha256).hexdigest()
        
        # Prepare the STK push payload
        stk_push_payload = {
            'phone': phone,
            'sid': sid,
            'vid': vid,
            'hash': hash_value
        }       

        # Send the STK push request
        response = requests.post('https://apis.ipayafrica.com/payments/v2/transact/push/mpesa',
                                 data=stk_push_payload,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
        
        # check if the request was successful
        response.raise_for_status()
        logger.info('STK push initiated successfully')
        frappe.msgprint('STK push initiated successfully')
        return response.json()
    
    except requests.RequestException as error:
        logger.error('Error triggering STK Push: %s', error)
        frappe.msgprint('Error triggering STK Push')
        raise RuntimeError("Error triggering STK Push") from error