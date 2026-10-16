// Map tile settings. Edit this file; nothing else needs to change.
//
// Default (leave tileUrl null): Esri "World Light/Dark Gray" raster tiles. No key, no email.
//
// To use CARTO instead (free key from https://carto.com/basemaps/apikey):
//   tileUrl: "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=YOUR_KEY",
//   tileAttribution: "© OpenStreetMap contributors © CARTO",
//
// Any other XYZ raster provider works too. Keys in client-side tile URLs are normal and not secret.
export const MAP_CONFIG: { tileUrl: string | null; tileAttribution: string | null; tileMaxZoom: number | null } = {
  tileUrl: null,
  tileAttribution: null,
  tileMaxZoom: null,
};
