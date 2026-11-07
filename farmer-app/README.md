# Farmroute farmer app (PWA)

A phone-first, installable site for farmers: log in with the farmer ID and PIN from the FPO, see the truck time, where the produce goes and an honest payout estimate, listen to it read aloud, and check a trader's offer. English, Telugu, Hindi and Tamil (machine-written translations: have a native speaker review every string in `app.js` before real use). The last card is saved on the phone so it still opens offline; logging out deletes it.

No build step: plain HTML, CSS and JavaScript. It talks only to `POST /farmer/login`, `GET /farmer/me`, the `/farmer/phone` routes and the change-request routes (`POST /farmer/chat`, `POST /farmer/requests/{id}/confirm|withdraw`, `GET /farmer/requests`) on the backend.

## Run locally
1. Start the backend with `ADMIN_TOKEN` and `FARMROUTE_SECRET` set (farmer routes refuse to work without `ADMIN_TOKEN`).
2. Edit `config.js` so `FARMER_API` is the backend URL.
3. `python3 -m http.server 8080` in this folder, open http://localhost:8080. Add `http://localhost:8080` to the backend's `ALLOWED_ORIGINS`.

## Deploy on Render (static site)
Root Directory `farmer-app`, Build Command empty, Publish Directory `.`. In Settings > Headers add `/sw.js` with `Cache-Control: no-cache` so updates reach phones. Then add the site's URL to the backend's `ALLOWED_ORIGINS`.

## SMS and WhatsApp updates
After login, a farmer with no stored number is offered to add one ("Not now" hides the offer for 3 days). They type the number (the browser's phone autofill can fill it), get a code by SMS, and type it back. Only then is it stored. The card's footer shows the masked number with "Stop updates", which deletes it. A web page cannot read the SIM number, which is why the number is typed and confirmed rather than picked from the phone. Updates then arrive by SMS and WhatsApp whenever the FPO publishes a plan that changes the farmer's card.

## Asking for a change
On the card screen a round chat button (bottom right) opens a screen where the farmer types what changed ("100 kg less", "ready 2 hours later") or, if the language model is off or unreachable, fills a small form (what, how, value). Either way the app shows what it understood in plain numbers and the farmer taps **Yes, send to my FPO** before anything is sent. The farmer's plan does not change: the FPO approves or rejects, and the farmer sees the answer under "Your requests" (and, once approved, a new card and the usual update message). The button is hidden while offline. The new strings (English, Telugu, Hindi, Tamil) are machine-written like the rest: have a native speaker review the `chat`, `c*`, `f*`, `h*`, `s*`, `r*` and `e*` keys in `app.js`.

Tests (jsdom, not needed to run the app): `cd farmer-app/tests && npm i && npm test`.

## Rules the app follows
Shows only the logged-in farmer's own card. Times are planned estimates, not tracking (hour 0 of the plan is shown as 00:00). Prices tagged Assumed are estimates, never quotes. A card older than 24 hours while offline is flagged as not to be relied on.

## Installing on a phone
Chrome on Android needs HTTPS, `manifest.json`, icons and a working service worker (`sw.js`); all are in this folder. Open the site in Chrome, then use the in-app **Install app** button or Chrome menu > Install app. On iPhone use Safari > Share > Add to Home Screen. If you still see "can't be installed", clear site data for the site once so the old worker is replaced.

## Read aloud
Uses the phone's own text-to-speech. Telugu, Hindi and Tamil need that voice installed (Android: Settings > System > Languages > Text-to-speech output). If it is missing the app says so instead of staying silent.
