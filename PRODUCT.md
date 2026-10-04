# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary (now): professors and course evaluators judging a first-semester "idea thinking" project. They have minutes, not hours; they need to understand the problem, see the idea working, and judge whether the numbers are honest. Secondary: recruiters and interviewers reading it as a portfolio piece. Later, if the project continues: operators of farmer producer organisations (FPOs) pooling produce. The UI is viewed on laptops and also on phones.

## Product Purpose

Farmroute Optimizer is a decision layer for farmer produce pooling and market allocation. Given farmers (location, crop, quantity, ready/deadline hours, refrigeration need), a finite vehicle fleet, and markets (per-crop price and capacity), it groups nearby farmers into shared trips, assigns vehicles, allocates produce across markets, and reports net return, share of produce actually sold, and spoilage. Success: an evaluator opens it, loads a scenario, and within a couple of minutes understands what the algorithm decided and why it beats the naive alternatives.

## Positioning

The algorithm (ILO, Integrated Logistics Optimization) pools farmers, respects refrigeration and pickup windows, and solves market allocation as an LP, so it can reroute overflow when a market fills. The UI's distinguishing job is explaining each decision (the "why" for every pool, route, and market) and being honest about what is real versus derived.

## Operating Context

FastAPI + SQLite backend, plain HTML/CSS/JS frontend, no build step, vendored MapLibre GL, deck.gl and Chart.js. Backend URL defaults to http://localhost:8000. Frontend is opened as static files. Planning clock is hours from start of day, not clock times. Currency is Indian rupees. The basemap needs internet; without it the map must still work on a plain background.

## Capabilities and Constraints

- Four areas exist today: data entry (farmers, vehicles, markets), recommended plan (ILO result: summary stats and pool cards), comparison (ILO vs Individual Transport vs Proximity Pooling, net return and % produce sold), map and simulation (7 presentation stages, timeline, step-by-step story, details panel, compare mode, 3D, chase cam, fullscreen "theater" walkthrough).
- Demo scenarios: three synthetic ones, each isolating one mechanism (cold chain, market arbitrage, fleet scarcity), plus one real-data scenario (7 Bihar mandis, Mar 2026, with synthetic farmers and fleet).
- Fixed vocabularies: 6 crops (tomato, onion, potato, cauliflower, mango, spinach), 7 vehicle types.
- Honesty rules that the UI must preserve: routes are straight lines, never real roads; per-stop times are a reconstruction; per-market received-kg is shown only when exactly derivable; items are tagged exact / derived / aggregate-only; sensor panel shows real ESP32 data or nothing, never simulated data.
- Net return and % produce sold must be read together; a high return with low coverage is misleading.
- Decision (user): keep the legacy three-way comparison for now. The "realistic baselines" (farm-gate, self-haul, neighbour pooling) are work in progress and are not surfaced in the UI yet.
- Every DOM id and vis/*.js hook used by app.js and vis/* must keep working; backend API unchanged.

## Evidence on Hand

Real scenario data in frontend/app.js (Bihar mandis, from Agmarknet via India Data Portal, with sourcing noted in its blurb). Backend results from /plan/compute. No testimonials, customers, or deployment claims exist; none may be invented.

## Product Principles

1. Show the decision, then the reason. Every number on screen should answer "what did it decide" or "why".
2. Honesty is a feature: label what is exact, derived, assumed, or synthetic; never dress an estimate as data.
3. Read the numbers in pairs. Return and coverage always appear together.
4. A first-time evaluator reaches a working result in two clicks, with no manual data entry.
5. It must work offline-ish: the map degrades gracefully, nothing blocks on the internet.

## Accessibility & Inclusion

Phone use is real (evaluators may open it on mobile). Touch targets and text must work at 390px width. Respect prefers-reduced-motion; a reduced-motion switch already exists in the simulation. Colour must never be the only carrier of meaning (vehicle colours are paired with ids).
