# Ipay: M-Pesa Payment Integration for Vendors

## Overview

Ipay is a cutting-edge Frappe application that enables vendors to integrate M-Pesa mobile money services into their business systems. It is designed to simplify payment collection, enhance transaction security, and provide a seamless experience for both vendors and customers.

## Prerequisites

### Mandatory Account Requirements

**IMPORTANT**: To use this application, you MUST:

-  Have an active account with [iPay Africa](https://www.ipayafrica.com/)
-  Obtain your unique Vendor ID and API Key from iPay
-  Complete the merchant onboarding process on the iPay platform

Without an iPay account, this application cannot process mobile money transactions.

## Key Features

-  **Seamless M-Pesa Payment Integration**: Effortlessly connect your business system to M-Pesa, enabling a smooth and intuitive payment experience for your customers without additional technical complexity.
-  **Automatic STK Push to Customer's Mobile Phone**: Instantly send a payment request directly to the customer's mobile device, minimizing errors and reducing the steps required to complete a transaction.
-  **Real-Time Payment Verification**: Verify payments as they happen, ensuring immediate confirmation and reducing delays in processing.
-  **Secure Transaction Logging**: Maintain a tamper-proof, detailed record of all payment transactions, including timestamps, amounts, and statuses, for compliance and auditing purposes.

## Payment Workflow

1. **Generate Unique Payment Session**: Each transaction is assigned a unique session ID to prevent duplication and enhance traceability.
2. **Trigger M-Pesa STK Push**: Automatically prompt the customer to authorize the payment on their mobile device, ensuring quick and user-friendly transactions.
3. **Verify Customer Payment**: Real-time integration with M-Pesa ensures that payments are verified immediately upon completion.
4. **Log Transaction Details**: All transaction details, including the payer's information, amount, and time of payment, are securely logged in your system.
5. **Send Payment Confirmation**: Notify customers and other relevant parties with a confirmation message once the payment is successfully processed.

## Requirements

-  **Active iPay Africa Account**: Mandatory for all transactions
-  **Frappe Framework**: Ensure your system is running on the Frappe framework for seamless integration.

## Installation and Setup

1. **Obtain iPay Account**: Register at [iPay Africa](https://www.ipayafrica.com/) and complete merchant onboarding
2. **Install the App**: Use Bench CLI to install the Ipay app in your Frappe instance.
3. **Configure Vendor Credentials**: Set up your iPay merchant account details, including Vendor ID and API Key, in the app settings.
4. **Set Callback URL**: Define a callback URL to receive payment status updates and automate backend processes.
5. **Start Using the App**: Begin processing payments through the integrated interface.

## Security and Compliance

Ipay is built with security at its core. It uses encryption protocols to protect sensitive data during transactions and ensures compliance with payment processing regulations.

## Roles

Five roles decide what someone sees and what they may do. Three are iPay's own; the sales
tiers are ERPNext's stock roles, reused as-is.

| Role | Lands on | Sees | May bundle | May split a bundle |
|---|---|---|---|---|
| **iPay Collector** | `/collect` | Only their own deliveries, collect-on-delivery terms only | No | No |
| **iPay User** | `/collect/internal` | Every customer, all terms | Yes | Yes |
| **iPay Manager** | `/collect/internal` | Every customer, all terms | Yes | Yes |
| **Sales User** | `/collect/sales` | Only their own book, all terms | Yes | No |
| **Sales Manager** | `/collect/sales` | Every member's book + a member filter | Yes | No |

### iPay Collector — the field/delivery role

Prompts and collects **only for their own work**, and only on the payment terms configured in
iPay Settings → Collect Payment Terms (e.g. Cash on Delivery, End of Day). Their work is the
union of two signals:

- **Driver** — invoices on delivery notes whose driver's `user` field is their login. The
  `Driver.user` field is added by the app.
- **Assignment** — iPay Requests assigned to them with Frappe's own *Assign To*.

With neither set they see **nothing** — never everything. They cannot bundle invoices (one
prompt at a time), cannot split a bundle, and cannot open internal or sales collection. In the
desk they can read (not edit) their own iPay Requests.

### iPay User — the operator

The everyday office role: sees every customer across **all** payment terms on
`/collect/internal`, filters by driver, payment term or sales member, prompts anyone, and
bundles several invoices into one payment. Never row-scoped. In the desk they can create and
submit iPay Requests, but cannot cancel or amend them, and cannot open iPay Settings or Logs.

### iPay Manager — the supervisor

Everything iPay User can do, plus **cancel and amend** iPay Requests in the desk, and the only
role besides System Manager that can open **iPay Settings** and **iPay Logs**.

### Sales User — a sales rep

Sees the customers their own **Sales Person** is named on, across all payment terms, on
`/collect/sales`. The login is matched through ERPNext's own chain:

```
User  ->  Employee.user_id  ->  Sales Person.employee
```

An invoice is theirs when the **invoice's** Sales Team names them, **or** the **customer's**
Sales Team does. Both are needed: ERPNext copies the customer's sales team onto an invoice when
it is created and never refreshes it, so a reassigned customer's older invoices still carry the
previous member. If the Employee or Sales Person link is missing they see nothing, and the page
says so. They may bundle their own invoices, but cannot split a bundle or open internal mode.

### Sales Manager — above the reps

Sees **every** member's book on `/collect/sales` and can filter to one member, and may also open
`/collect/internal`. Never row-scoped — unless restricted (below).

Note the tiers are told apart by the *absence* of the manager role: someone holding **both**
Sales User and Sales Manager is treated as a manager. To give a rep their own book, grant
**Sales User without Sales Manager**.

### Restricting sales managers

**iPay Settings → Restrict Sales Managers to Their Own Book.** Tick it and a Sales Manager sees
only the customers their own Sales Person is named on, exactly like a Sales User — the member
filter disappears. Leave it off and they see every member's book.

The setting is about the sales team only: **System Manager, iPay Manager and iPay User are never
restricted by it**, and always see every book on the sales page.

## iPay Collect — mobile app (frontend)

`/collect` is an installable, mobile-first Vue 3 app for delivery teams to prompt
and track payments (single invoices or per-customer bundles). It lives in
`frontend/` (Vite + frappe-ui + Pinia), is served by Frappe at `/collect`, and
reuses the app's existing whitelisted APIs and the logged-in Frappe session.

### Develop

```bash
cd apps/ipay && yarn install   # installs frontend deps (root postinstall)
yarn dev                       # Vite dev server; proxies the API to your bench
```

### Build / deploy

Built assets are not committed — `bench build` builds them automatically (it runs
the frontend's `yarn build`):

```bash
bench build --app ipay
# fresh install:
bench get-app <repo-url> && bench install-app ipay && bench build
```

The build outputs to `ipay/public/frontend` and writes the entry to
`ipay/www/collect.html` (both git-ignored). On a phone, open `/collect` and use
the browser's **Add to Home Screen** to install it.

## License

This application is licensed under the MIT License, ensuring open access and flexibility for customization.

## Contact

For support or inquiries, please reach out to:

Gatura Njenga  
Email: gaturanjenga@gmail.com
