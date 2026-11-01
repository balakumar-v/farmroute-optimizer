# Farmroute frontend (React + TypeScript + Vite)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173  (backend: cd backend && uvicorn main:app --port 8000)
npm run build        # typecheck + production build in dist/
npm test             # vitest (simulation engine)
npm run gen:api      # optional: typed schema from the running backend's OpenAPI
```

Backend URL: header chip (saved in localStorage) or `VITE_API_BASE` at build time. Map tiles: `src/config.ts`.

## Layout
- `src/App.tsx` hash router (`#start|entry|dash|compare|map`), map tab stays mounted to keep simulation state
- `src/state/store.tsx` context + reducer: tables, plan, stale flag, scenario-run progress, toasts
- `src/lib/` typed API client, types, constants, scenario data (`scenarios.ts`)
- `src/views/` Scenarios, Data, Plan, Compare, Map
- `src/vis/` imperative map/simulation engine (MapLibre + deck.gl), ES modules ported from the old `vis/*.js`; typed surface in `vis/index.ts`. `MapView.tsx` wraps it.

## UX changes vs the old frontend
Scenario run shows a progress bar and step label; backend-down banner with start command + Retry; toasts instead of `alert()`; inline form validation; stale-plan banner when data changes after a plan; skeleton/empty/error table states; empty states offer "Compute from current data"; sortable pools table; map auto-loads the new plan, loading overlay, buttons disabled until a plan exists; keyboard: Space play/pause, ←/→ scrub, 1–7 stages; speed and reduced-motion persisted (default follows OS setting); scenarios grouped by category.
