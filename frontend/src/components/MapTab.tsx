/**
 * People, work and time.
 *
 * Both views are built from the raw retrieval context rather than the narrated
 * answer, because the entity, role and relation edges are precisely what the
 * narrator flattens into a sentence. Asking "everything about Prof. Nair" and
 * parsing the graph out of the context gives a structure no amount of prose
 * parsing would.
 */

import { useState } from "react";
import { ApiError, ParsedContext, api } from "../api";
import { Evidence } from "./Evidence";

export function MapTab() {
  const [name, setName] = useState("");
  const [entityCtx, setEntityCtx] = useState<ParsedContext | null>(null);
  const [window, setWindow] = useState("last week");
  const [timelineCtx, setTimelineCtx] = useState<ParsedContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<{ parsed: ParsedContext }>, set: (c: ParsedContext) => void) => {
    setBusy(true);
    setError(null);
    try {
      set((await fn()).parsed);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="card">
        <h2>Who is who</h2>
        <p className="hint">
          Supervisors, teammates, courses, papers — and the roles and relations
          Reeve extracted from your own sentences.
        </p>
        <div className="row">
          <input
            className="grow"
            type="text"
            value={name}
            placeholder="Prof. Nair"
            onChange={(e) => setName(e.target.value)}
          />
          <button
            onClick={() => run(() => api.entity(name), setEntityCtx)}
            disabled={busy || !name.trim()}
          >
            Look up · 1 query
          </button>
        </div>
        {entityCtx && (
          <div style={{ marginTop: "1rem" }}>
            {Object.keys(entityCtx.roles).length > 0 && (
              <div className="row" style={{ marginBottom: "0.6rem" }}>
                {Object.entries(entityCtx.roles).map(([entity, role]) => (
                  <span className="chip" key={entity}>
                    {entity} → {role}
                  </span>
                ))}
              </div>
            )}
            <Evidence ctx={entityCtx} />
          </div>
        )}
      </section>

      <section className="card">
        <h2>What happened when</h2>
        <p className="hint">
          The time phrase is part of the question — the engine parses it out and
          filters on when things actually happened, not when you wrote them down.
        </p>
        <div className="row">
          {["last week", "last month", "in October"].map((w) => (
            <button
              key={w}
              onClick={() => {
                setWindow(w);
                run(() => api.timeline(w), setTimelineCtx);
              }}
              disabled={busy}
              aria-selected={window === w}
            >
              {w}
            </button>
          ))}
        </div>
        {timelineCtx && (
          <div style={{ marginTop: "1rem" }}>
            <Evidence ctx={timelineCtx} />
          </div>
        )}
      </section>

      {error && <div className="error">{error}</div>}
    </>
  );
}
