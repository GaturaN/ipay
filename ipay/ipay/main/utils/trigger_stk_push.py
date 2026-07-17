import requests
import hmac
import hashlib
import logging
import frappe

from ipay.ipay.main.utils.http import post_with_backoff

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

        # Send the STK push request. A momentary 429/5xx is retried with backoff; a
        # timeout bounds the call so a hung socket can't wedge the worker.
        response = post_with_backoff(
            'https://apis.ipayafrica.com/payments/v2/transact/push/mpesa',
            data=stk_push_payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30,
        )
        logger.info('STK push initiated successfully')
        return response.json()
    
    except requests.RequestException as error:
        logger.error('Error triggering STK Push: %s', error)
        raise RuntimeError("Error triggering STK Push") from error