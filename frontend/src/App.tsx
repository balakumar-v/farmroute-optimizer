import { useCallback, useEffect, useState } from "react";
import { IconSprite } from "./components/Icon";
import { BackendBanner, Header, Toasts } from "./components/Shell";
import { VIEWS } from "./lib/constants";
import type { ViewName } from "./lib/types";
import { AppProvider } from "./state/store";
import { CompareView } from "./views/CompareView";
import { DataView } from "./views/DataView";
import { MapView } from "./views/MapView";
import { PlanView } from "./views/PlanView";
import { RequestsView } from "./views/RequestsView";
import { ScenariosView } from "./views/ScenariosView";

const NAMES = VIEWS.map((v) => v.id) as readonly string[];
const fromHash = (): ViewName => {
  const h = location.hash.slice(1);
  return (NAMES.includes(h) ? h : "start") as ViewName;
};

/** Hash routing: back/forward work and each tab is linkable. */
function useView(): [ViewName, (v: ViewName) => void] {
  const [view, setView] = useState<ViewName>(fromHash);
  useEffect(() => {
    const on = () => setView(fromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((v: ViewName) => {
    if (location.hash.slice(1) !== v) location.hash = v;
    else setView(v);
  }, []);
  return [view, go];
}

function Shell() {
  const [view, go] = useView();
  const [mapSeen, setMapSeen] = useState(view === "map");

  useEffect(() => {
    if (view === "map") setMapSeen(true);
    window.scrollTo(0, 0);
    const label = VIEWS.find((v) => v.id === view)?.label ?? "";
    document.title = `${label} · Farmroute Optimizer`;
  }, [view]);

  return (
    <>
      <IconSprite />
      <Header view={view} go={go} />
      <BackendBanner />
      <main>
        {view === "start" && <section id="view-start" className="view active"><ScenariosView go={go} /></section>}
        {view === "entry" && <section id="view-entry" className="view active"><DataView /></section>}
        {view === "dash" && <section id="view-dash" className="view active"><PlanView go={go} /></section>}
        {view === "requests" && <section id="view-requests" className="view active"><RequestsView /></section>}
        {view === "compare" && <section id="view-compare" className="view active"><CompareView go={go} /></section>}
        {/* The map keeps its simulation state across tab switches, so it stays mounted once opened. */}
        {mapSeen && <section id="view-map" className={"view" + (view === "map" ? " active" : "")}><MapView visible={view === "map"} go={go} /></section>}
      </main>
      <Toasts />
    </>
  );
}

export default function App() {
  return <AppProvider><Shell /></AppProvider>;
}
