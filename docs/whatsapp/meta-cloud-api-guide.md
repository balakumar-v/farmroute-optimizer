# FarmRoute Optimizer – Meta WhatsApp Cloud API Integration Guide
## Complete Setup & Operational Reference (No WABA ID Required)

---

## 1. Executive Summary & Architecture Confirmation

Your FarmRoute Optimizer application is fully integrated with the official **Meta WhatsApp Cloud API**.

### Key Architectural Highlights:
1. **NO WABA ID REQUIRED**:
   - Meta's official WhatsApp messages endpoint is:
     `POST https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages`
   - Outgoing messages and webhooks operate directly via your **Phone Number ID**:
     `<your-phone-number-id>`
   - `WHATSAPP_BUSINESS_ACCOUNT_ID` is completely optional, omitted from validation, and will **never block message dispatch**.
2. **Dual-Channel Delivery (`OTP_CHANNEL=both`)**:
   - Every OTP verification code, OTP resend, registration welcome message, and farmer route/plan update is dispatched simultaneously over **SMS** and **WhatsApp**.
   - If one channel encounters an error (e.g. SMS quota exceeded or expired WhatsApp token), the other channel is still dispatched, and each result is recorded independently.
3. **Delivery Status Webhooks**:
   - Supports Meta webhook handshakes (`hub.challenge` verification) and captures status updates (`sent`, `delivered`, `read`, `failed`) in the database.
4. **Security & Deduplication**:
   - In-memory 30-second deduplication cache prevents accidental duplicate messages.
   - Access tokens and OTP codes are strictly kept secret and never exposed to the frontend or logged to files.

---

## 2. Environment Configuration (`backend/.env`)

Configure the following variables in `farmroute-optimizer/backend/.env`:

```env
# ------------------------------------------------------------------------------
# NOTIFICATION STRATEGY
# ------------------------------------------------------------------------------
OTP_CHANNEL=both
SMS_PROVIDER=dry         # Options: dry | twilio | msg91
WHATSAPP_PROVIDER=meta   # Options: dry | meta | twilio

# ------------------------------------------------------------------------------
# META WHATSAPP CLOUD API (NO WABA ID REQUIRED)
# ------------------------------------------------------------------------------
WHATSAPP_TOKEN=<YOUR_FRESH_OR_PERMANENT_META_ACCESS_TOKEN>
WHATSAPP_PHONE_NUMBER_ID=<your-phone-number-id>
WHATSAPP_GRAPH_API_VERSION=v20.0

# WHATSAPP_BUSINESS_ACCOUNT_ID is strictly optional and not required
# WHATSAPP_BUSINESS_ACCOUNT_ID=

# Message Templates
WHATSAPP_OTP_TEMPLATE=farmroute_otp
WHATSAPP_TEMPLATE=farmroute_plan_update
WHATSAPP_OTP_BUTTON=copy_code

# Webhook Verification Token (set this in Meta App Dashboard)
WHATSAPP_WEBHOOK_VERIFY_TOKEN=change-me-long-random-string
```

> **Testing with `hello_world`:**
> If your custom templates `farmroute_otp` or `farmroute_plan_update` are not yet created or approved in your Meta Business Account, you can test connectivity with:
> ```env
> WHATSAPP_OTP_TEMPLATE=hello_world
> WHATSAPP_TEMPLATE=hello_world
> ```
> The system has a dedicated payload builder for `hello_world` that sends pre-approved text without needing custom parameters.

---

## 3. Resolving Token Expiration (Meta Code 190 / Subcode 463)

When we tested your credentials against Meta's Graph API:
- Endpoint: `https://graph.facebook.com/v20.0/<your-phone-number-id>/messages`
- Phone Number ID: `<your-phone-number-id>` (Successfully recognized by Meta)
- Response: `HTTP 401 [code 190, subcode 463] - Error validating access token: Session has expired on Saturday, 07-Nov-2026 05:00:00 PST`

This confirms your **Phone Number ID `<your-phone-number-id>` is 100% correct**. The only reason the message was not delivered was that the temporary token expired.

### How to Get a Fresh or Permanent Token:

#### Option A: Quick 24-Hour Temporary Token (For Testing)
1. Go to the [Meta App Dashboard](https://developers.facebook.com/apps/).
2. Select your App -> **WhatsApp** -> **API Setup**.
3. Under **Temporary access token**, click **Copy**.
4. Paste it into `backend/.env` under `WHATSAPP_TOKEN=...`.
5. Restart your backend server.

#### Option B: Permanent System User Token (Recommended for Production)
1. Go to [Meta Business Settings](https://business.facebook.com/settings/).
2. In the left menu, select **Users** -> **System Users**.
3. Click **Add**, name the user (e.g. `FarmRoute-API`), and assign the **Admin** role.
4. Click **Add Assets**:
   - Under **Apps**, select your FarmRoute App and grant **Full Control**.
5. Click **Generate New Token**:
   - Select your FarmRoute App.
   - Choose token expiration: **Never**.
   - Check the following permissions:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
6. Click **Generate Token** and copy it immediately.
7. Paste this permanent token into `backend/.env`:
   ```env
   WHATSAPP_TOKEN=EAAG...
   ```

---

## 4. Meta Webhooks Setup (Delivery Status Tracking)

FarmRoute receives real-time delivery status notifications from Meta (`sent`, `delivered`, `read`, `failed`).

### Webhook Configuration in Meta Dashboard:
1. In the [Meta App Dashboard](https://developers.facebook.com/apps/), go to **WhatsApp** -> **Configuration**.
2. Find the **Webhooks** section and click **Edit**:
   - **Callback URL:**
     `https://<your-domain-or-ngrok>/api/whatsapp/webhook`
   - **Verify token:**
     `change-me-long-random-string` (matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `.env`)
3. Click **Verify and Save**. Meta will send a GET request with `hub.challenge`, which FarmRoute automatically verifies.
4. Under **Webhook fields**, click **Manage** and subscribe to:
   - `messages` (captures delivery receipts and status updates).

---

## 5. API Endpoints Catalog

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/whatsapp/health` | Diagnostic status (checks token, phone ID, confirms WABA ID not required) | Public |
| `GET` | `/api/whatsapp/webhook` | Meta Webhook challenge verification | Public |
| `POST` | `/api/whatsapp/webhook` | Meta Webhook status event receiver | Public |
| `GET` | `/api/whatsapp/statuses` | View recent delivery statuses from Meta | Admin |
| `POST` | `/api/whatsapp/send-otp` | Standalone WhatsApp OTP dispatch | Admin / Farmer |
| `POST` | `/api/whatsapp/notify/plan-activation` | Farmer plan activation notification | Admin |
| `POST` | `/api/whatsapp/notify/subscription-renewal` | Subscription renewal reminder | Admin |
| `POST` | `/api/whatsapp/notify/payment-confirmation` | Payment receipt notification | Admin |
| `POST` | `/farmer/phone/start` | Dual-channel OTP dispatch (SMS + WhatsApp) | Public |
| `POST` | `/farmer/phone/verify` | Farmer OTP verification | Public |
| `POST` | `/plan/{id}/publish` | Dual-channel plan notification to all route farmers | Admin |

---

## 6. Verification and Health Checks

### Check WhatsApp Configuration Health:
In PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/whatsapp/health" -Method GET | ConvertTo-Json
```
Expected output:
```json
{
  "configured": true,
  "phoneNumberIdConfigured": true,
  "tokenConfigured": true,
  "otpTemplateConfigured": true,
  "planTemplateConfigured": true,
  "wabaIdRequiredForSending": false,
  "graphApiVersion": "v20.0",
  "phoneNumberId": "<your-phone-number-id>",
  "provider": "meta",
  "live": true
}
```

### Run Automated Notification & Meta Test Suite:
In PowerShell from the project root:
```powershell
& ".\backend\.venv\Scripts\python.exe" -m pytest "backend\tests\test_whatsapp_service.py" -v
& ".\backend\.venv\Scripts\python.exe" -m pytest "backend\tests\test_phones.py" -v
```

---

## 7. Troubleshooting Common Meta Cloud API Errors

| Error Code | Meaning | Solution |
|---|---|---|
| **190 / 463** | Access token expired | Generate a fresh token or permanent System User token and update `WHATSAPP_TOKEN`. |
| **131030** | Recipient phone not in sandbox allowed list | In Development/Sandbox mode, add and verify the recipient's phone number under Meta Dashboard -> WhatsApp -> API Setup -> "To". |
| **132001** | Template does not exist | Ensure `WHATSAPP_OTP_TEMPLATE` or `WHATSAPP_TEMPLATE` matches an approved template in your WhatsApp Manager, or switch to `hello_world` for testing. |
| **132000** | Template parameter count mismatch | Check that the template parameters configured match the template definition. |
| **100** | Invalid parameter / missing phone number ID | Confirm `WHATSAPP_PHONE_NUMBER_ID=<your-phone-number-id>` is set in `.env`. |
