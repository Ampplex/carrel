/**
 * Carrel — a coursework memory built on the Reeve SDK.
 *
 * The capability badges in the header are not decoration. Vision, photo
 * retention and async writes are all controlled on the Reeve side and can be
 * turned off underneath a running app. When that happens nothing errors —
 * answers just quietly stop being grounded in the image. Reading the live
 * config on load turns a silent degradation into a visible red badge.
 */

import { useCallback, useEffect, useState } from "react";
import { Capabilities, PendingWrite, api } from "./api";
import { Desk } from "./components/Desk";
import { Photos } from "./components/Photos";
import { MapTab } from "./components/MapTab";
import { PendingTray } from "./components/PendingTray";

type Tab = "desk" | "photos" | "map";

export default function App() {
  const [tab, setTab] = useState<Tab>("desk");
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingWrite[]>([]);

  const refreshPending = useCallback(() => {
    api.pending().then(setPending).catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .config()
      .then(setCaps)
      .catch((e) => setCapsError(e.message));
    refreshPending();
  }, [refreshPending]);

  // Local tick to keep the tray's elapsed times fresh. `/api/pending` costs
  // nothing — it reads in-process state and makes no call to Reeve.
  useEffect(() => {
    const timer = setInterval(refreshPending, 5000);
    return () => clearInterval(timer);
  }, [refreshPending]);

  const onWrite = (written: PendingWrite[]) => {
    setPending((prev) => [...written, ...prev]);
    refreshPending();
  };

  const unsettled = pending.filter(
    (p) => p.status === "indexing" || p.status === "likely_indexed"
  ).length;

  const badge = (label: string, on: boolean | undefined) => (
    <span className={`badge ${on === undefined ? "" : on ? "on" : "off"}`} key={label}>
      {label}
    </span>
  );

  return (
    <div className="shell">
      <header className="top">
        <h1>Carrel</h1>
        <span className="tagline">coursework you can ask questions of</span>
        <div className="badges">
          {capsError
            ? badge("reeve unreachable", false)
            : caps && [
                badge(caps.chat_model?.split(".").pop() ?? "model", true),
                badge("vision", caps.capabilities.photo_questions),
                badge("photo retention", caps.capabilities.photo_reinterrogation),
                badge("photo search", caps.capabilities.photo_search),
              ]}
        </div>
      </header>

      {capsError && (
        <div className="error">
          Cannot read Reeve's capabilities: {capsError}
        </div>
      )}

      <nav className="tabs">
        <button aria-selected={tab === "desk"} onClick={() => setTab("desk")}>
          Desk
        </button>
        <button aria-selected={tab === "photos"} onClick={() => setTab("photos")}>
          Photos
        </button>
        <button aria-selected={tab === "map"} onClick={() => setTab("map")}>
          People &amp; time
        </button>
      </nav>

      {tab === "desk" && <Desk onWrite={onWrite} unsettled={unsettled} />}
      {tab === "photos" && <Photos onWrite={onWrite} />}
      {tab === "map" && <MapTab />}

      <PendingTray items={pending} onRefresh={refreshPending} />
    </div>
  );
}
