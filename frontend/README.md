# Frontend

React + TypeScript + Vite. The map and simulation engine is MapLibre GL plus deck.gl.

```bash
npm install
npm run dev          # http://localhost:5173 (backend: see ../backend/README.md)
npm run build        # typecheck and production build in dist/
npm test             # vitest (simulation engine)
npm run gen:api      # optional: typed schema from the running backend's OpenAPI
```

## Configuration

- **Backend URL:** the connection chip in the header (saved in the browser), or `VITE_API_BASE` at build time. Default `http://localhost:8000`.
- **Map tiles:** `src/config.ts`. The default is Esri gray canvas (no key). The map always renders a plain limewash background with a lat/lng grid, so it works offline; street tiles load on top when the internet is available.

## Layout

```
src/
  App.tsx              hash router (#start|entry|dash|compare|map); the map tab stays mounted to keep simulation state
  main.tsx             entry point
  state/store.tsx      context + reducer: tables, plan, stale flag, scenario-run progress, toasts
  lib/                 typed API client, types, constants, scenario data (scenarios.ts)
  views/               Scenarios, Data, Plan, Compare, Map
  components/          Shell, Icon sprite
  vis/                 imperative map and simulation engine (MapLibre + deck.gl); typed surface in vis/index.ts, wrapped by MapView.tsx
  styles.css           design tokens and components (see ../docs/DESIGN.md)
  styles-extra.css     additional component styles
```

## Scenarios

`src/lib/scenarios.ts` holds the eight demo scenarios: three synthetic and five built on real mandi data. The backend benchmarks and experiments read the same file (`backend/real_data/bihar_preset.py`), so keep its `key: {` layout. To add a real-data preset, see `../backend/real_data/README.md`.

## Interface behaviour

- Scenario runs show a progress bar and step label; a banner with the start command and a Retry button appears when the backend is down.
- Forms validate inline, results use toasts rather than alerts, and a stale-plan banner appears when data changes after a plan was computed.
- Tables have skeleton, empty and error states; the pools table is sortable.
- Map keyboard shortcuts: Space play/pause, ←/→ scrub, 1 to 7 jump to a stage.
- Speed and reduced-motion settings persist; the default follows the OS reduced-motion setting.
- Layout works down to 390 px wide.
