"""
notify.py -- phone numbers, one-time codes, message text and SMS / WhatsApp providers. Standard library only, no
database, so every function here is testable on its own (the database side is phones.py).

Providers are chosen by environment variables and default to "dry": messages are logged, never sent. That makes the
whole feature demoable with no account anywhere. Turn real sending on by setting a provider and its credentials.

    SMS_PROVIDER       dry (default) | twilio | msg91
    WHATSAPP_PROVIDER  dry (default) | meta | twilio

    twilio   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM (a number or messaging-service id; SMS),
             TWILIO_WHATSAPP_FROM (e.g. whatsapp:+14155238886, the sandbox number; WhatsApp)
    msg91    MSG91_AUTH_KEY, MSG91_OTP_TEMPLATE_ID, MSG91_UPDATE_TEMPLATE_ID, MSG91_VAR (the variable name in your
             DLT template, default VAR1). Each template body must be a single variable.
    meta     WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_TEMPLATE (default farmroute_plan_update; one body variable
             {{1}}; create it in each of en, ta, te, hi), WHATSAPP_API_VERSION (default v20.0)

    DEFAULT_COUNTRY_CODE  digits added to numbers typed without one (default 91)

The provider adapters were written from the providers' public API descriptions and have NOT been run against the
live services; check them with one real message before relying on them. The code a farmer types is only ever
sent by SMS; plan updates go to both channels.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("farmroute.notify")

LANGS = ("en", "te", "hi", "ta")
OTP_DIGITS = 6
OTP_TTL_S = 10 * 60


# ---------------------------------------------------------------- phone numbers
def default_cc() -> str:
    return re.sub(r"\D", "", os.environ.get("DEFAULT_COUNTRY_CODE", "91")) or "91"


def normalize_phone(raw: str, cc: str = None) -> str:
    """'98765 43210', '+91 98765-43210', '09876543210', '919876543210' -> '+919876543210'. Raises ValueError.
    A number typed with a '+' (or '00') is taken as international and only checked for length; one without is a
    national number for DEFAULT_COUNTRY_CODE (for India: 10 digits starting 6-9)."""
    cc = cc or default_cc()
    s = re.sub(r"[\s\-().]", "", str(raw or ""))
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
        if not digits.isdigit() or not 8 <= len(digits) <= 15 or digits[0] == "0":
            raise ValueError("That does not look like a phone number.")
        return "+" + digits
    if not s.isdigit():
        raise ValueError("That does not look like a phone number.")
    if s.startswith(cc) and len(s) > len(cc) + 6 and not (cc == "91" and len(s) == 10):
        s = s[len(cc):]
    elif s.startswith("0"):
        s = s[1:]
    if cc == "91":
        if not re.fullmatch(r"[6-9]\d{9}", s):
            raise ValueError("Enter a 10-digit mobile number.")
    elif not 6 <= len(s) <= 12:
        raise ValueError("That does not look like a phone number.")
    return f"+{cc}{s}"


def mask_phone(e164: str) -> str:
    """'+919876543210' -> '+91******3210' (what the farmer and the admin console may see)."""
    d = str(e164 or "")
    return d if len(d) <= 7 else d[:3] + "*" * (len(d) - 7) + d[-4:]


# ---------------------------------------------------------------- one-time codes
def new_otp() -> str:
    return f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"


def otp_digest(farmer_id: int, phone: str, code: str, key: bytes) -> str:
    """Only this digest is stored. It is bound to the farmer and the number, so a code cannot be moved to another."""
    return hmac.new(key, f"{farmer_id}|{phone}|{code}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- message text
_CROP = {
    "te": {"tomato": "టమాటా", "onion": "ఉల్లిపాయ", "potato": "బంగాళాదుంప", "cauliflower": "కాలిఫ్లవర్", "mango": "మామిడి", "spinach": "పాలకూర"},
    "hi": {"tomato": "टमाटर", "onion": "प्याज", "potato": "आलू", "cauliflower": "फूलगोभी", "mango": "आम", "spinach": "पालक"},
    "ta": {"tomato": "தக்காளி", "onion": "வெங்காயம்", "potato": "உருளைக்கிழங்கு", "cauliflower": "காலிஃபிளவர்", "mango": "மாம்பழம்", "spinach": "பசலைக்கீரை"},
}
# One line each, no newlines (WhatsApp template variables may not contain them). {v} is rupees, {p} rupees per kg.
_MSG = {
    "en": {
        "hauled": "Farmroute: A truck will come to your farm at {t} to take your {kg} kg of {crop} to Mandi {m}. You will get about Rs {v} (estimate).",
        "farmgate": "Farmroute: No truck needed this time. Selling to a trader at your door pays about Rs {v} (about Rs {p} a kg). If the offer is much lower, call your FPO first.",
        "unserved": "Farmroute: No truck is free for your {crop} this time. Do not wait at your farm. Selling at your door may give about Rs {v}. Ask your FPO what to do.",
        "changed": "Your plan has changed. ", "welcome": "You will get plan updates here. ",
        "otp": "{code} is your Farmroute verification code. Do not share it. Valid for 10 minutes."},
    "te": {
        "hauled": "Farmroute: {t} ట్రక్కు మీ పొలానికి వస్తుంది. అది మీ {kg} కిలోల {crop}ను మండీ {m}కు తీసుకెళ్తుంది. మీకు సుమారు {v} రూపాయలు వస్తాయి (అంచనా).",
        "farmgate": "Farmroute: ఈసారి ట్రక్కు అవసరం లేదు. ఇంటి వద్ద వ్యాపారికి అమ్మితే సుమారు {v} రూపాయలు వస్తాయి (కిలోకు సుమారు {p}). ఆఫర్ చాలా తక్కువగా ఉంటే, ముందు మీ FPOకు ఫోన్ చేయండి.",
        "unserved": "Farmroute: ఈసారి మీ {crop}కు ట్రక్కు ఖాళీ లేదు. పొలం దగ్గర ఎదురు చూడకండి. ఇంటి వద్ద అమ్మితే సుమారు {v} రూపాయలు రావచ్చు. ఏం చేయాలో మీ FPOను అడగండి.",
        "changed": "మీ ప్లాన్ మారింది. ", "welcome": "ఇకపై ప్లాన్ అప్‌డేట్‌లు ఇక్కడ వస్తాయి. ",
        "otp": "{code} మీ Farmroute ధృవీకరణ కోడ్. ఎవరితోనూ పంచుకోవద్దు. 10 నిమిషాలు చెల్లుతుంది."},
    "hi": {
        "hauled": "Farmroute: {t} आपके खेत पर ट्रक आएगा। वह आपके {kg} किलो {crop} को मंडी {m} ले जाएगा। आपको लगभग {v} रुपये मिलेंगे (अनुमान)।",
        "farmgate": "Farmroute: इस बार ट्रक की ज़रूरत नहीं है। दरवाज़े पर व्यापारी को बेचने पर लगभग {v} रुपये मिलेंगे (लगभग {p} रुपये किलो)। ऑफर बहुत कम हो तो पहले अपने FPO को फ़ोन करें।",
        "unserved": "Farmroute: इस बार आपके {crop} के लिए ट्रक खाली नहीं है। खेत पर इंतज़ार न करें। दरवाज़े पर बेचने पर लगभग {v} रुपये मिल सकते हैं। आगे क्या करें, अपने FPO से पूछें।",
        "changed": "आपका प्लान बदल गया है। ", "welcome": "अब प्लान अपडेट यहाँ मिलेंगे। ",
        "otp": "{code} आपका Farmroute सत्यापन कोड है। किसी को न बताएँ। 10 मिनट मान्य।"},
    "ta": {
        "hauled": "Farmroute: {t} லாரி உங்கள் வயலுக்கு வரும். அது உங்கள் {kg} கிலோ {crop}-ஐ மண்டி {m}-க்கு கொண்டு செல்லும். உங்களுக்கு சுமார் {v} ரூபாய் கிடைக்கும் (மதிப்பீடு).",
        "farmgate": "Farmroute: இந்த முறை லாரி தேவையில்லை. வீட்டில் வியாபாரிக்கு விற்றால் சுமார் {v} ரூபாய் கிடைக்கும் (கிலோவுக்கு சுமார் {p}). விலை மிகக் குறைவாக இருந்தால், முதலில் உங்கள் FPO-வுக்கு அழையுங்கள்.",
        "unserved": "Farmroute: இந்த முறை உங்கள் {crop}-க்கு லாரி இல்லை. வயலில் காத்திருக்க வேண்டாம். வீட்டில் விற்றால் சுமார் {v} ரூபாய் கிடைக்கலாம். என்ன செய்வது என்று உங்கள் FPO-விடம் கேளுங்கள்.",
        "changed": "உங்கள் திட்டம் மாறியுள்ளது. ", "welcome": "இனி திட்ட அறிவிப்புகள் இங்கே வரும். ",
        "otp": "{code} உங்கள் Farmroute சரிபார்ப்பு குறியீடு. யாருடனும் பகிர வேண்டாம். 10 நிமிடம் செல்லுபடியாகும்."},
}


def _indian(n: int) -> str:
    """1234567 -> '12,34,567' (Indian digit grouping)."""
    s = str(abs(int(n)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if n < 0 else "") + ",".join(groups + [tail])


def _about(n: float) -> str:
    """'about 4,200', not '4,201' (same rounding the farmer app reads aloud)."""
    n = round(n)
    return _indian(round(n / 10) * 10 if n >= 1000 else round(n / 5) * 5 if n >= 100 else n)


def _clock12(hhmm) -> str:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hhmm or ""))
    if not m:
        return str(hhmm or "")
    h = int(m.group(1)) % 24
    return f"{h % 12 or 12}:{m.group(2)} {'AM' if h < 12 else 'PM'}"


def _lang(lang) -> str:
    return lang if lang in _MSG else "en"


def compose_plan_message(card: dict, lang: str, kind: str = "update") -> str:
    """The farmer's current plan as one short line. kind: 'update' (plain), 'changed' (the re-plan touched them),
    'welcome' (just registered their number). Holds only the farmer's own facts, same as their card."""
    lang = _lang(lang)
    M = _MSG[lang]
    status = card.get("status") if card.get("status") in ("hauled", "farmgate", "unserved") else "unserved"
    trip = card.get("trip") or {}
    mandis = trip.get("mandis") or []
    kg = card.get("qty_kg", 0)
    v = {"t": _clock12(trip.get("pickup_eta")), "kg": int(kg) if float(kg) == int(kg) else round(float(kg), 1),
         "crop": _CROP.get(lang, {}).get(card.get("crop"), card.get("crop", "")),
         "m": mandis[0]["id"] if mandis else "", "v": _about((card.get("payout") or {}).get("total_inr", 0)),
         "p": _indian(round(card.get("doorstep_per_kg") or 0))}
    prefix = M["changed"] if kind == "changed" else M["welcome"] if kind == "welcome" else ""
    body = M[status].format(**v)
    if prefix:       # the prefix goes after the brand tag so the message still starts with "Farmroute:"
        tag, rest = body.split(": ", 1)
        body = f"{tag}: {prefix}{rest}"
    return body


def compose_otp_message(code: str, lang: str) -> str:
    return _MSG[_lang(lang)]["otp"].format(code=code)


# ---------------------------------------------------------------- transport (replaced in tests)
def _http(url: str, headers: dict, data: bytes, timeout: float = 10.0):
    """POST; returns (status, body text). Never raises for an HTTP error status, raises only on network failure."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _short(text: str, n: int = 160) -> str:
    return re.sub(r"\s+", " ", text or "")[:n]


# ---------------------------------------------------------------- providers: send(e164, text, lang, kind) -> (ok, detail)
class DryRun:
    """Logs instead of sending. The default, so nothing is ever sent by accident."""
    def __init__(self, channel):
        self.channel, self.name, self.live = channel, "dry", False

    def send(self, to, text, lang="en", kind="update"):
        log.warning("DRY-RUN %s to %s [%s]: %s", self.channel, mask_phone(to), kind, text)   # logged in full: dev only
        return True, "dry-run (logged, not sent)"


class Misconfigured:
    def __init__(self, channel, name, why):
        self.channel, self.name, self.live, self.why = channel, name, False, why

    def send(self, to, text, lang="en", kind="update"):
        return False, f"{self.name} not configured: {self.why}"


class TwilioSms:
    channel, name, live = "sms", "twilio", True

    def __init__(self, env):
        self.sid, self.token, self.sender = env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"], env["TWILIO_SMS_FROM"]

    def send(self, to, text, lang="en", kind="update"):
        return _twilio(self.sid, self.token, to, self.sender, text)


class TwilioWhatsApp:
    channel, name, live = "whatsapp", "twilio", True

    def __init__(self, env):
        self.sid, self.token, self.sender = env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"], env["TWILIO_WHATSAPP_FROM"]

    def send(self, to, text, lang="en", kind="update"):
        sender = self.sender if self.sender.startswith("whatsapp:") else "whatsapp:" + self.sender
        return _twilio(self.sid, self.token, "whatsapp:" + to, sender, text)


def _twilio(sid, token, to, sender, text):
    # A messaging service id (MG...) goes in MessagingServiceSid, a number or whatsapp: address in From.
    form = {"To": to, "Body": text}
    form["MessagingServiceSid" if sender.startswith("MG") else "From"] = sender
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    status, body = _http(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                         {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                         urllib.parse.urlencode(form).encode())
    return (status < 300, "sent" if status < 300 else f"twilio {status}: {_short(body)}")


class Msg91Sms:
    """MSG91 Flow API. India needs a DLT-approved template; each template here is one variable holding the text."""
    channel, name, live = "sms", "msg91", True

    def __init__(self, env):
        self.key, self.var = env["MSG91_AUTH_KEY"], env.get("MSG91_VAR") or "VAR1"
        self.otp_tpl, self.upd_tpl = env["MSG91_OTP_TEMPLATE_ID"], env["MSG91_UPDATE_TEMPLATE_ID"]

    def send(self, to, text, lang="en", kind="update"):
        payload = {"template_id": self.otp_tpl if kind == "otp" else self.upd_tpl, "short_url": "0",
                   "recipients": [{"mobiles": to.lstrip("+"), self.var: text}]}
        status, body = _http("https://control.msg91.com/api/v5/flow/",
                             {"authkey": self.key, "Content-Type": "application/json", "accept": "application/json"},
                             json.dumps(payload).encode())
        return (status < 300, "sent" if status < 300 else f"msg91 {status}: {_short(body)}")


class MetaWhatsApp:
    """WhatsApp Cloud API. Business-started messages must use an approved template (one body variable {{1}})."""
    channel, name, live = "whatsapp", "meta", True

    def __init__(self, env):
        self.token, self.phone_id = env["WHATSAPP_TOKEN"], env["WHATSAPP_PHONE_ID"]
        self.template = env.get("WHATSAPP_TEMPLATE") or "farmroute_plan_update"
        self.version = env.get("WHATSAPP_API_VERSION") or "v20.0"

    def send(self, to, text, lang="en", kind="update"):
        payload = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "template",
                   "template": {"name": self.template, "language": {"code": _lang(lang)},
                                "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}]}}
        status, body = _http(f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages",
                             {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                             json.dumps(payload).encode())
        return (status < 300, "sent" if status < 300 else f"meta {status}: {_short(body)}")


_NEEDS = {
    ("sms", "twilio"): (TwilioSms, ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM")),
    ("sms", "msg91"): (Msg91Sms, ("MSG91_AUTH_KEY", "MSG91_OTP_TEMPLATE_ID", "MSG91_UPDATE_TEMPLATE_ID")),
    ("whatsapp", "meta"): (MetaWhatsApp, ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID")),
    ("whatsapp", "twilio"): (TwilioWhatsApp, ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM")),
}


def get_provider(channel: str, env=None):
    """The provider for 'sms' or 'whatsapp' from the environment. Unknown name or missing credentials give a
    provider that fails every send with a clear reason (the admin console shows it), never a crash at startup."""
    env = os.environ if env is None else env
    name = (env.get(f"{'SMS' if channel == 'sms' else 'WHATSAPP'}_PROVIDER") or "dry").strip().lower()
    if name == "dry":
        return DryRun(channel)
    if (channel, name) not in _NEEDS:
        return Misconfigured(channel, name, f"unknown provider (choose one of: dry, {', '.join(n for c, n in _NEEDS if c == channel)})")
    cls, needed = _NEEDS[(channel, name)]
    missing = [k for k in needed if not env.get(k)]
    return Misconfigured(channel, name, "missing " + ", ".join(missing)) if missing else cls(env)


def describe_providers(env=None) -> dict:
    out = {}
    for ch in ("sms", "whatsapp"):
        p = get_provider(ch, env)
        out[ch] = {"provider": p.name, "live": p.live, "problem": getattr(p, "why", None)}
    return out
