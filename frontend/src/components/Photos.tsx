/**
 * Photo memory.
 *
 * The point of this tab is the side-by-side comparison at the bottom. Ask the
 * same unanticipated question about a whiteboard photo two ways:
 *
 *   attached — the image goes with the question, so the vision model reads the
 *              original again at query time;
 *   lane     — nothing is attached, so the photo has to be found on its own
 *              merits by the image retrieval lane.
 *
 * The first is the capability claim: a caption written once cannot answer
 * questions its author never thought of, but a retained image can. The second is
 * the honest part — the lane is tuned to prefer precision over recall and does
 * not always fire, and showing that is better than hiding it.
 */

import { useEffect, useState } from "react";
import { ApiError, Photo, PhotoAnswer, PendingWrite, api } from "../api";

export function Photos({ onWrite }: { onWrite: (pending: PendingWrite[]) => void }) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [attached, setAttached] = useState<PhotoAnswer | null>(null);
  const [lane, setLane] = useState<PhotoAnswer | null>(null);
  const [busy, setBusy] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState<string | null>(null);

  const refresh = () => api.photos().then(setPhotos).catch(() => undefined);
  useEffect(() => { refresh(); }, []);

  const upload = async () => {
    if (!file || !caption.trim()) return;
    setUploading(true);
    setError(null);
    try {
      const result = await api.storePhoto(file, caption);
      onWrite(result.pending);
      setCaption("");
      setFile(null);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const compare = async () => {
    if (!selected || !question.trim()) return;
    setBusy(true);
    setError(null);
    setAttached(null);
    setLane(null);
    try {
      // Sequential, never concurrent: the SDK keeps one connection, and a
      // reconnect triggered by one call can strand another in flight.
      setAttached(await api.askPhoto(selected, question));
      setLane(await api.askUnattached(question));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (!searchQuery.trim()) return;
    setBusy(true);
    try {
      const result = await api.searchPhotos(searchQuery);
      setSearchResult(result.found ? result.raw : "No matching photo memories found.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="card">
        <h2>Add a photo</h2>
        <p className="hint">
          A whiteboard, a slide, a lab bench. Reeve fuses your caption with what a
          vision model sees into a single memory, and keeps the original — so the
          picture can be re-read later for something the caption never mentioned.
        </p>
        <input
          type="text"
          value={caption}
          placeholder="Whiteboard from the Tuesday lab meeting"
          onChange={(e) => setCaption(e.target.value)}
        />
        <div className="row" style={{ marginTop: "0.6rem" }}>
          <input
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ fontSize: "0.85rem" }}
          />
          <button className="primary" onClick={upload} disabled={uploading || !file || !caption.trim()}>
            {uploading ? "Uploading…" : "Store photo"}
          </button>
        </div>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="card">
        <h2>Photo wall</h2>
        {photos.length === 0 ? (
          <p className="hint">No photos yet.</p>
        ) : (
          <>
            <p className="hint">
              Pick one, then ask it something nobody thought to write down.
              {photos.length < 3 && (
                <> Note: the unattached image lane stays silent below three photos, so store a few more to see it fire.</>
              )}
            </p>
            <div className="wall">
              {photos.map((p) => (
                <figure
                  key={p.photo_id}
                  className={selected === p.photo_id ? "selected" : ""}
                  onClick={() => setSelected(p.photo_id)}
                  style={{ cursor: "pointer" }}
                >
                  <img src={p.thumb_url} alt={p.caption} />
                  <figcaption>{p.caption}</figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
      </section>

      {selected && (
        <section className="card">
          <h2>Ask this photo something new</h2>
          <textarea
            rows={2}
            value={question}
            placeholder="What was written in the top-right corner?"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="row" style={{ marginTop: "0.6rem" }}>
            <button className="primary" onClick={compare} disabled={busy || !question.trim()}>
              Ask both ways · 2 queries
            </button>
          </div>

          {(attached || lane) && (
            <div className="compare" style={{ marginTop: "1rem" }}>
              <div>
                <strong style={{ fontSize: "0.85rem" }}>With the photo attached</strong>
                <p className="answer" style={{ fontSize: "0.95rem" }}>{attached?.answer}</p>
                <p className="hint">{attached?.note}</p>
              </div>
              <div>
                <strong style={{ fontSize: "0.85rem" }}>Without attaching it</strong>
                <p className="answer" style={{ fontSize: "0.95rem" }}>{lane?.answer}</p>
                <p className="hint">{lane?.note}</p>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="card">
        <h2>Find a photo by what it looks like</h2>
        <p className="hint">Searches the image itself, not the caption.</p>
        <div className="row">
          <input
            className="grow"
            type="text"
            value={searchQuery}
            placeholder="whiteboard with a state diagram"
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <button onClick={search} disabled={busy || !searchQuery.trim()}>
            Search · 1 query
          </button>
        </div>
        {searchResult && <pre className="raw" style={{ marginTop: "0.7rem" }}>{searchResult}</pre>}
      </section>
    </>
  );
}
