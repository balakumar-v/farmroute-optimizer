# Farmroute farmer app (PWA)

A phone-first, installable site for farmers: log in with the farmer ID and PIN from the FPO, see the truck time, where the produce goes and an honest payout estimate, listen to it read aloud, and check a trader's offer. English, Telugu, Hindi and Tamil (machine-written translations: have a native speaker review every string in `app.js` before real use). The last card is saved on the phone so it still opens offline; logging out deletes it.

No build step: plain HTML, CSS and JavaScript. It talks only to `POST /farmer/login` and `GET /farmer/me` on the backend.

## Run locally
1. Start the backend with `ADMIN_TOKEN` and `FARMROUTE_SECRET` set (farmer routes refuse to work without `ADMIN_TOKEN`).
2. Edit `config.js` so `FARMER_API` is the backend URL.
3. `python3 -m http.server 8080` in this folder, open http://localhost:8080. Add `http://localhost:8080` to the backend's `ALLOWED_ORIGINS`.

## Deploy on Render (static site)
Root Directory `farmer-app`, Build Command empty, Publish Directory `.`. In Settings > Headers add `/sw.js` with `Cache-Control: no-cache` so updates reach phones. Then add the site's URL to the backend's `ALLOWED_ORIGINS`.

## Rules the app follows
Shows only the logged-in farmer's own card. Times are planned estimates, not tracking (hour 0 of the plan is shown as 00:00). Prices tagged Assumed are estimates, never quotes. A card older than 24 hours while offline is flagged as not to be relied on.

## Installing on a phone
Chrome on Android needs HTTPS, `manifest.json`, icons and a working service worker (`sw.js`); all are in this folder. Open the site in Chrome, then use the in-app **Install app** button or Chrome menu > Install app. On iPhone use Safari > Share > Add to Home Screen. If you still see "can't be installed", clear site data for the site once so the old worker is replaced.

## Read aloud
Uses the phone's own text-to-speech. Telugu, Hindi and Tamil need that voice installed (Android: Settings > System > Languages > Text-to-speech output). If it is missing the app says so instead of staying silent.
