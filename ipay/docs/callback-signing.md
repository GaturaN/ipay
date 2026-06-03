# Verifying iPay callback signatures (n8n)

When **Callback Signing Secret** is set in iPay Settings, every outbound callback
is signed so the receiver can prove it came from this app and is not a replay.

## What we send

- Body: canonical JSON (the payment result), sent verbatim.
- `Content-Type: application/json`
- `X-iPay-Timestamp: <unix seconds>`
- `X-iPay-Signature: sha256=<hex>` where
  `hex = HMAC_SHA256(secret, "{timestamp}.{rawBody}")`

The secret is the exact value of **Callback Signing Secret** in iPay Settings.
With no secret set, callbacks are sent unsigned (no signature headers).

## Verify in n8n (Code node, before acting on the payload)

```js
const crypto = require('crypto');
const SECRET = $env.IPAY_CALLBACK_SECRET;          // same value as iPay Settings

const raw  = $input.first().json.body ?? '';        // RAW body string (not re-serialized)
const ts   = $input.first().json.headers['x-ipay-timestamp'];
const given = ($input.first().json.headers['x-ipay-signature'] || '').replace('sha256=', '');

// 1) freshness — reject anything older than 5 minutes (replay protection)
if (!ts || Math.abs(Date.now() / 1000 - Number(ts)) > 300) {
  throw new Error('iPay callback timestamp invalid or stale');
}

// 2) signature
const expected = crypto.createHmac('sha256', SECRET).update(`${ts}.${raw}`).digest('hex');
const ok = crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(given));
if (!ok) throw new Error('iPay callback signature mismatch');

return $input.all();
```

> Verify against the **raw** request body — if the webhook node parses and your
> Code node re-serializes the JSON, the bytes (and the hash) will differ. In n8n,
> enable the webhook's raw/binary body or read the unparsed body.

## Rotating the secret

Change it in iPay Settings and in n8n together (briefly accept either during the
overlap, or schedule a short maintenance window). An empty secret disables
signing.
