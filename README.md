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

## License

This application is licensed under the MIT License, ensuring open access and flexibility for customization.

## Contact

For support or inquiries, please reach out to:

Gatura Njenga  
Email: gaturanjenga@gmail.com
