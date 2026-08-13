/**
 * The bottom strip that shows writes Reeve has accepted but not yet indexed.
 *
 * This component was built before the answer card, deliberately. Reeve
 * acknowledges a write instantly and finishes indexing it seconds later, so
 * there is a window where the app knows something the user does not. Most demos
 * paper over that. Making it structural — a permanent strip, wired into the
 * answer's caveat banner — means the interface cannot quietly overclaim.
 *
 * The status timer runs entirely in the browser and makes no network calls.
 * Background polling for index status is the one pattern that would burn
 * thousands of queries a day, so the only way to reach a confirmed "indexed" is
 * the explicit button, which prints its own cost.
 */

import { useEffect, useState } from "react";
import { api, PendingWrite } from "../api";

const LABEL: Record<PendingWrite["status"], string> = {
  indexing: "indexing",
  likely_indexed: "likely indexed",
  indexed: "indexed",
  failed: "failed",
};

export function PendingTray({
  items,
  onRefresh,
}: {
  items: PendingWrite[];
  onRefresh: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  const [checking, setChecking] = useState<string | null>(null);

  // Local clock only — this deliberately does not touch the network.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (items.length === 0) return null;

  const verify = async (id: string) => {
    setChecking(id);
    try {
      await api.verify(id);
      onRefresh();
    } finally {
      setChecking(null);
    }
  };

  return (
    <div className="tray">
      <strong style={{ fontSize: "0.8rem" }}>Settling</strong>
      {items.map((item) => {
        const elapsed = Math.max(0, Math.round(now / 1000 - item.created_at));
        return (
          <span key={item.id} className={`pill ${item.status}`}>
            <span className="dot" />
            {item.kind === "photo" ? "photo" : "note"} · {LABEL[item.status]} · {elapsed}s
            {item.status !== "indexed" && (
              <button
                style={{ padding: "0 0.3rem", fontSize: "0.68rem", border: "none", background: "none", textDecoration: "underline" }}
                disabled={checking === item.id}
                onClick={() => verify(item.id)}
                title="Runs a real retrieval to see whether this memory is searchable yet. Costs one query."
              >
                {checking === item.id ? "checking…" : "check now (1 query)"}
              </button>
            )}
          </span>
        );
      })}
      <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: "0.74rem" }}>
        Reeve accepted these instantly and is still building the graph.
      </span>
    </div>
  );
}
