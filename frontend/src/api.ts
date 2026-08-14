/**
 * The only place that talks to the backend.
 *
 * There is no Reeve client in the browser and there never should be: the API key
 * lives on the server, and the namespace is chosen there too, because a
 * namespace partitions memory without securing it.
 */

export type Status = "indexing" | "likely_indexed" | "indexed" | "failed";

export interface PendingWrite {
  id: string;
  pending_id: string | null;
  kind: "note" | "photo";
  preview: string;
  batch_id: string;
  created_at: number;
  status: Status;
  verified_at: number | null;
}

export interface StateFact {
  entity: string;
  attribute: string;
  value: string;
  superseded: boolean;
}

export interface Episode {
  timestamp: string;
  display: string;
  summary: string | null;
  emotion: string | null;
  importance: number | null;
  metadata: Record<string, string>;
  entities: string[];
  actions: { actor: string; verb: string; object: string | null }[];
  relations: { subject: string; relation: string; object: string }[];
  states: StateFact[];
  locations: string[];
  raw_extra: string[];
}

export interface ParsedContext {
  raw: string;
  empty: boolean;
  has_conflict_rule: boolean;
  pending: string[];
  episodes: Episode[];
  roles: Record<string, string>;
  raw_extra: string[];
}

export interface Answer {
  answer: string;
  evidence: ParsedContext | null;
  queries_used: number;
  took_ms: number;
  unsettled_writes: number;
}

export interface PhotoAnswer {
  answer: string;
  mode: string;
  note: string;
  queries_used: number;
  took_ms: number;
}

export interface Photo {
  photo_id: string;
  caption: string;
  thumb_url: string;
  stored_at: number;
}

export interface Capabilities {
  chat_model?: string;
  vision_enabled?: boolean;
  image_retention_enabled?: boolean;
  multimodal_image_search_enabled?: boolean;
  async_write_enabled?: boolean;
  image_retention_days?: string | number;
  capabilities: {
    photo_questions: boolean;
    photo_reinterrogation: boolean;
    photo_search: boolean;
    async_writes: boolean;
  };
}

/** A classified failure from the backend. Quota exhaustion and model throttling
 *  are normal conditions here, so they carry a usable message rather than a
 *  generic failure. */
export class ApiError extends Error {
  code: string;
  retryable: boolean;
  constructor(code: string, message: string, retryable: boolean) {
    super(message);
    this.code = code;
    this.retryable = retryable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status}).`;
    let retryable = false;
    try {
      const body = await response.json();
      code = body.code ?? code;
      message = body.user_message ?? body.detail ?? message;
      retryable = Boolean(body.retryable);
    } catch {
      /* non-JSON error body; keep the defaults */
    }
    throw new ApiError(code, message, retryable);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  config: () => request<Capabilities>("/api/config"),
  health: () => request<{ ok: boolean; namespace: string; replay_mode: boolean }>("/api/health"),

  storeNote: (text: string, contextLine = "") =>
    request<{ batch_id: string; pending: PendingWrite[]; chunked: boolean }>(
      "/api/notes",
      json({ text, context_line: contextLine })
    ),

  storePhoto: (file: File, caption: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("caption", caption);
    return request<{ pending: PendingWrite[]; photo_id: string; thumb_url: string }>(
      "/api/photos",
      { method: "POST", body: form }
    );
  },

  ask: (question: string, withEvidence: boolean) =>
    request<Answer>("/api/ask", json({ question, with_evidence: withEvidence })),

  /** The raw ranked context behind an answer. Fetched only when the reader asks
   *  to see it, so the second query is spent only when it will be looked at. */
  context: (question: string) =>
    request<{ raw: string; parsed: ParsedContext }>("/api/context", json({ question })),

  entity: (name: string) =>
    request<{ raw: string; parsed: ParsedContext }>("/api/entity", json({ name })),

  timeline: (window: string) =>
    request<{ raw: string; parsed: ParsedContext }>("/api/timeline", json({ window })),

  photos: () => request<Photo[]>("/api/photos"),

  askPhoto: (photoId: string, question: string) =>
    request<PhotoAnswer>("/api/photos/ask", json({ photo_id: photoId, question })),

  askUnattached: (question: string) =>
    request<PhotoAnswer>("/api/photos/ask-unattached", json({ query: question })),

  searchPhotos: (query: string) =>
    request<{ raw: string; found: boolean }>("/api/photos/search", json({ query })),

  pending: () => request<PendingWrite[]>("/api/pending"),

  verify: (id: string) =>
    request<{ status: Status; found: boolean }>(`/api/pending/${id}/verify`, { method: "POST" }),
};
