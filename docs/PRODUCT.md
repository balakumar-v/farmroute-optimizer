# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary (now): judges and reviewers evaluating the project (hackathon jury, course evaluators). They have minutes, not hours; they need to understand the problem, see the idea working, and judge whether the numbers are honest. Secondary: recruiters and interviewers reading it as a portfolio piece. Later, if the project continues: operators of farmer producer organisations (FPOs) pooling produce. The UI is viewed on laptops and also on phones.

## Product Purpose

Farmroute Optimizer is a decision layer for farmer produce pooling and market allocation. Given farmers (location, crop, quantity, ready/deadline hours, refrigeration need), a finite vehicle fleet, and markets (per-crop price and capacity), it groups nearby farmers into shared trips, assigns vehicles, allocates produce across markets, and reports net return, share of produce actually sold, and spoilage. Success: an evaluator opens it, loads a scenario, and within a couple of minutes understands what the algorithm decided and why it beats the naive alternatives.

## Positioning

The algorithm (ILO, Integrated Logistics Optimization, now v3) pools farmers, respects refrigeration and pickup windows, solves market allocation as an LP so it can reroute overflow when a market fills, hauls only what beats selling at the farm gate, merges farmers heading to the same mandi into full trucks, and picks the trip set with an exact solver. It returns the best of its own plans and the baselines, and says which it chose. The UI's distinguishing job is explaining each decision (the "why" for every pool, route, and market) and being honest about what is real versus derived.

## Operating Context

FastAPI + Postgres backend, React + TypeScript + Vite frontend (MapLibre GL and deck.gl from npm). Backend URL defaults to http://localhost:8000. Planning clock is hours from start of day, not clock times. Currency is Indian rupees. The basemap needs internet; without it the map must still work on a plain background.

## Capabilities and Constraints

- Four areas exist today: data entry (farmers, vehicles, markets), recommended plan (ILO result: summary stats and pool cards), comparison (ILO vs Individual Transport vs Proximity Pooling, net return and % produce sold), map and simulation (7 presentation stages, timeline, step-by-step story, details panel, compare mode, 3D, chase cam, fullscreen "theater" walkthrough).
- Demo scenarios: three synthetic ones, each isolating one mechanism (cold chain, market arbitrage, fleet scarcity), plus five real-data presets (Bihar, Karnataka/Bengaluru, Uttar Pradesh/Aligarh, Maharashtra/Junnar, Madhya Pradesh/Indore), each with real mandi data and synthetic farmers and fleet.
- Fixed vocabularies: 6 crops (tomato, onion, potato, cauliflower, mango, spinach), 7 vehicle types.
- Honesty rules that the UI must preserve: routes are straight lines, never real roads; per-stop times are a reconstruction; per-market received-kg is shown only when exactly derivable; items are tagged exact / derived / aggregate-only; sensor panel shows real ESP32 data or nothing, never simulated data.
- Net return and % produce sold must be read together; a high return with low coverage is misleading.
- Decision (user): the comparison keeps its three rows, but Individual Transport and Proximity Pooling are now the BEHAVIOURAL farmer baselines (hire a spot truck to the nearest mandi if it is within reach and clearly beats the trader; no profit calculation; otherwise sell at the farm gate). The headline is "farmer value" = net return + farm-gate sales, with the farm-gate price labelled as an assumption. Farm-gate sellers get their own colour on the map (slate), never the red used for unserved farmers. The rational variants and the legacy baselines are returned by the API under `realistic_baselines` but not shown.
- Backend API unchanged. The map engine (`src/vis/*.js`) keeps its DOM-id contract, which `MapView.tsx` renders.

## Evidence on Hand

Real scenario data in frontend/src/lib/scenarios.ts (Bihar mandis, Dec 2025 - Feb 2026, from Agmarknet via India Data Portal, rebuilt with backend/real_data/*; sourcing and known data problems are in its blurb). The farmers and fleet in that preset are synthetic; no FPO records exist. Four more real-mandi presets (Karnataka/Bengaluru, Uttar Pradesh/Aligarh, Maharashtra/Junnar, Madhya Pradesh/Indore) are built by backend/real_data/build_regional_presets.py from state-wide CSVs; their blurbs list what was cleaned and which counts are assumptions. Backend results from /plan/compute. No testimonials, customers, or deployment claims exist; none may be invented.

## Product Principles

1. Show the decision, then the reason. Every number on screen should answer "what did it decide" or "why".
2. Honesty is a feature: label what is exact, derived, assumed, or synthetic; never dress an estimate as data.
3. Read the numbers in pairs. Return and coverage always appear together.
4. A first-time evaluator reaches a working result in two clicks, with no manual data entry.
5. It must work offline-ish: the map degrades gracefully, nothing blocks on the internet.

## Accessibility & Inclusion

Phone use is real (evaluators may open it on mobile). Touch targets and text must work at 390px width. Respect prefers-reduced-motion; a reduced-motion switch already exists in the simulation. Colour must never be the only carrier of meaning (vehicle colours are paired with ids).
