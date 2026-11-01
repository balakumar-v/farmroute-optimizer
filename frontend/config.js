// Map tile settings. Edit this file; nothing else needs to change.
//
// Default (leave tileUrl null): Esri "World Light/Dark Gray" raster tiles. No key, no email.
//
// To use CARTO instead (free key, emailed instantly from https://carto.com/basemaps/apikey):
//   tileUrl: "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=YOUR_KEY",
//   tileAttribution: "\u00A9 OpenStreetMap contributors \u00A9 CARTO",
//
// To use any other XYZ raster provider, put its URL template in tileUrl.
// Keys in client-side tile URLs are normal and not secret.
window.FPO_CONFIG = {
  tileUrl: null,
  tileAttribution: null,
  tileMaxZoom: null,
};
