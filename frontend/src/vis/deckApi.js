// The exact deck.gl classes the map uses, imported from their own packages.
// (The "deck.gl" umbrella package does not re-export MapboxOverlay, which lives in @deck.gl/mapbox.)
export { IconLayer, LineLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
export { PathStyleExtension } from "@deck.gl/extensions";
export { MapboxOverlay } from "@deck.gl/mapbox";
