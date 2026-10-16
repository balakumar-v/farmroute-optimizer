import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import "./styles-extra.css";
import { Vis } from "./vis";
import App from "./App";

// Optional tile override (see src/config.ts); the map falls back to keyless Esri tiles.
import { MAP_CONFIG } from "./config";
Vis.config = MAP_CONFIG;

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
