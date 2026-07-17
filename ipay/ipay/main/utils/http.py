import time

import requests

# iPay statuses worth retrying: 429 (rate limited) and transient 5xx. Any other
# 4xx is a request problem — retrying it just wastes time.
RETRYABLE_STATUS = {429, 502, 503, 504}


def _retry_after_seconds(response):
    """Seconds to wait from a numeric Retry-After header, if iPay sent one."""
    value = response.headers.get("Retry-After")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def post_with_backoff(url, *, data, headers=None, timeout=45, retries=2, backoff=(2, 5)):
    """POST that retries a rate-limited / transient iPay response with exponential
    backoff (honouring Retry-After), then raises like a plain request. Only ever
    called from the long STK worker, where a few seconds of wait is safe and beats
    failing a whole payment on a momentary 429."""
    attempt = 0
    while True:
        response = requests.post(url, data=data, headers=headers, timeout=timeout)
        if response.status_code not in RETRYABLE_STATUS or attempt >= retries:
            response.raise_for_status()
            return response
        wait = _retry_after_seconds(response) or backoff[min(attempt, len(backoff) - 1)]
        time.sleep(wait)
        attempt += 1
