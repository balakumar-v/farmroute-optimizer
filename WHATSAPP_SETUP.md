# WhatsApp OTP + continuous plan updates (Meta WhatsApp Cloud API)

What this adds
- The 6-digit verification code a farmer types can be sent on **WhatsApp** (`OTP_CHANNEL=whatsapp`), SMS (default) or both.
- Every time an operator publishes a plan, farmers with a verified number whose plan changed get a WhatsApp message
  (everyone on the first publish). A farmer who verifies a number also gets the current plan once, straight away.

## 1. Create `backend/.env` (git-ignored; never commit it)
```
DATABASE_URL=...                      # as before
ADMIN_TOKEN=...                       # as before
FARMROUTE_SECRET=...                  # as before

WHATSAPP_PROVIDER=meta
WHATSAPP_TOKEN=<your Meta access token>
WHATSAPP_PHONE_ID=514959798361773
OTP_CHANNEL=whatsapp
WHATSAPP_OTP_TEMPLATE=farmroute_otp
WHATSAPP_TEMPLATE=farmroute_plan_update
```
Start: `uvicorn main:app --reload --port 8000 --env-file .env`
On Render/other hosts, set the same names as environment variables instead of a file.

## 2. Templates (Meta Business Manager > WhatsApp Manager > Message templates)
WhatsApp only lets a business *start* a conversation with an approved template.
| Name | Category | Body | Languages |
|---|---|---|---|
| `farmroute_otp` | Authentication | `{{1}} is your verification code.` + the "Copy code" button | en, ta, te, hi |
| `farmroute_plan_update` | Utility | `{{1}}` (one variable holding the whole line) | en, ta, te, hi |

If your OTP template has no button, set `WHATSAPP_OTP_BUTTON=off`.

## 3. Test numbers
With Meta's free test number you can only message numbers added to the allowed-recipients list
(WhatsApp > API Setup > "To"), and each must confirm a code from Meta first.
To try things before templates are approved, set `WHATSAPP_MODE=text` (plain text; delivered only if that person
messaged your number in the last 24 hours). Switch back to `template` for real use.

## 4. Security
- Access tokens are passwords. If one was pasted anywhere (chat, issue, screenshot), generate a new one and revoke the old.
- Temporary tokens expire after ~24 h; for production create a System User token in Business Settings.
- Logs show only masked numbers (`+91******3210`), never the code.
