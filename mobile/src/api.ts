/**
 * The only place that talks to the Carrel backend.
 *
 * Two things differ from a browser client. The base URL cannot be relative or
 * localhost — a phone has its own idea of "localhost", so it must be told the
 * laptop's LAN address. And the token is held in the device keychain rather
 * than anything web-shaped, because it is a credential.
 *
 * The namespace is never sent. The server derives it from the token, which is
 * the entire reason a namespace can be trusted as a boundary: a client that
 * could name one could name someone else's.
 */

import * as SecureStore from "expo-secure-store";
import * as LegacyFileSystem from "expo-file-system/legacy";
import { SaveFormat, manipulateAsync } from "expo-image-manipulator";
import { LEGAL_VERSION } from "./legal";

/**
 * Your laptop's LAN address — `ipconfig getifaddr en0`.
 *
 * If nothing loads, check this first: phone and laptop on the same wifi, and
 * the backend started with `--host 0.0.0.0` rather than the default
 * loopback-only bind.
 */
export const API_BASE = "http://192.168.1.5:8000";

const TOKEN_KEY = "Carrel.session.token";

let token: string | null = null;

export async function loadToken(): Promise<string | null> {
  if (token) return token;
  try {
    token = await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    token = null;
  }
  return token;
}

/**
 * An <Image> source for a photo that may live behind the API's auth.
 *
 * Photos are served from /api/photos/{id}/raw, which requires the session token
 * — it has to, or anyone could read anyone's photographs by guessing ids. But
 * <Image source={{uri}}> sends no Authorization header, so every photo restored
 * from a transcript came back 401 and rendered as an empty grey box. Freshly
 * picked ones looked fine, because those still point at a local file:// path,
 * which is why this only ever showed up after a reload.
 *
 * Local URIs are passed through untouched: attaching a bearer token to a
 * file:// read would be pointless, and to a third-party URL would be a leak.
 */
export function imageSource(uri: string): { uri: string; headers?: Record<string, string> } {
  return uri.startsWith(API_BASE) && token
    ? { uri, headers: { Authorization: `Bearer ${token}` } }
    : { uri };
}

async function setToken(value: string | null): Promise<void> {
  token = value;
  try {
    if (value) await SecureStore.setItemAsync(TOKEN_KEY, value);
    else await SecureStore.deleteItemAsync(TOKEN_KEY);
  } catch {
    /* keychain unavailable — the session simply will not survive a restart */
  }
}

export interface Session {
  token: string;
  email: string;
  name: string;
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
  states: StateFact[];
  entities: string[];
}

export interface ParsedContext {
  raw: string;
  empty: boolean;
  pending: string[];
  episodes: Episode[];
  roles: Record<string, string>;
}

export interface Answer {
  answer: string;
  queries_used: number;
  took_ms: number;
  unsettled_writes: number;
}

export interface PhotoAnswer {
  answer: string;
  mode: string;
  note: string;
  took_ms: number;
}

/** What erasure actually removed — reported back so "deleted" is a fact the
 *  user can see rather than a claim they have to trust. */
export interface ErasureReport {
  memories: number;
  entities: number;
  reeve_images: number;
  local_photos: number;
  conversations: number;
}

export interface ChatSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  preview: string;
}

export interface StoredMessage {
  role: "you" | "Carrel" | "note";
  text: string;
  thumb_url?: string | null;
  meta?: string | null;
  question?: string | null;
  created_at?: number;
}

export interface PendingWrite {
  id: string;
  kind: "note" | "photo";
  status: "indexing" | "likely_indexed" | "indexed" | "failed";
  created_at: number;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as object) };
  const t = await loadToken();
  if (t) headers.Authorization = `Bearer ${t}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (e) {
    // Every fetch rejection used to be reported as "can't reach the server",
    // which was actively misleading: a multipart upload that failed for its own
    // reasons produced a message telling people to check their wifi while other
    // requests to the same host were succeeding. Keep the friendly wording for
    // a genuine connection failure and surface anything else as itself.
    const detail = e instanceof Error ? e.message : String(e);
    const looksOffline =
      /network request failed|connection|refused|timed out|unreachable/i.test(detail);

    console.warn(`[carrel] ${init.method ?? "GET"} ${path} failed:`, detail);

    throw new ApiError(
      looksOffline ? "unreachable" : "request_failed",
      looksOffline
        ? `Can't reach Carrel at ${API_BASE}. Same wifi as the laptop?`
        : `That request failed: ${detail}`,
      0
    );
  }

  if (response.status === 401) {
    await setToken(null); // the session died; the app will fall back to sign-in
    throw new ApiError("unauthorized", "Your session expired. Sign in again.", 401);
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `Something went wrong (${response.status}).`;
    try {
      const body = await response.json();
      code = body.code ?? code;
      message = body.user_message ?? body.detail ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, message, response.status);
  }

  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** A picked image, as much as the picker chose to tell us about it. */
export interface PickedImage {
  uri: string;
  mimeType?: string | null;
  fileName?: string | null;
  width?: number;
  height?: number;
}

/**
 * Longest edge a photo is allowed to keep.
 *
 * Not about the pixels: base64 inflates bytes by a third, and the encoded
 * payload plus JSON-RPC framing has to clear the HTTP body limit on Reeve's
 * server. Full-resolution phone photos came back as
 * `413 Request Entity Too Large` — from Reeve's nginx, before any of its own
 * 4 MB image check was reached. 1600px keeps text on a whiteboard legible while
 * landing comfortably inside that limit.
 */
const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.7;

/**
 * Normalise a picked image, then read it as base64.
 *
 * Every photo is re-encoded as a bounded JPEG rather than uploaded as-is. That
 * one step fixes two unrelated failures:
 *
 *   HEIC — iPhones save photos in a format Reeve does not accept, so choosing
 *   a normal iPhone photo failed with "Unsupported image type 'image/heic'".
 *
 *   Size — a modern phone photo is several megabytes, and base64 makes it
 *   bigger still; Reeve's HTTP layer rejected it outright.
 *
 * Photos go up as JSON rather than multipart because React Native 0.86 rejects
 * the `{uri, name, type}` object that every RN upload example uses. The bytes
 * end up base64 encoded anyway, since that is what Reeve's API takes.
 */
async function readImage(image: PickedImage): Promise<{ base64: string; mediaType: string }> {
  // Constrain the LONGEST edge, and only shrink. Resizing by width alone would
  // leave a tall portrait photo enormous, and would upscale anything already
  // small — spending bytes to add no detail.
  const { width = 0, height = 0 } = image;
  const longest = Math.max(width, height);
  const actions =
    longest > MAX_EDGE
      ? [width >= height ? { resize: { width: MAX_EDGE } } : { resize: { height: MAX_EDGE } }]
      : []; // already small enough: re-encode only, do not resample

  const normalised = await manipulateAsync(image.uri, actions, {
    compress: JPEG_QUALITY,
    format: SaveFormat.JPEG,
  });

  const base64 = await LegacyFileSystem.readAsStringAsync(normalised.uri, {
    encoding: "base64",
  });

  // Always JPEG now, whatever arrived.
  return { base64, mediaType: "image/jpeg" };
}

export const api = {
  // ── account ──────────────────────────────────────────────────────────────
  register: async (email: string, password: string, name: string): Promise<Session> => {
    // The version of the terms this build actually displayed travels with the
    // registration, so the account records what was agreed to rather than
    // whatever the server happens to be shipping later.
    const s = await request<Session>(
      "/api/auth/register",
      json({ email, password, name, terms_version: LEGAL_VERSION })
    );
    await setToken(s.token);
    return s;
  },
  login: async (email: string, password: string): Promise<Session> => {
    const s = await request<Session>("/api/auth/login", json({ email, password }));
    await setToken(s.token);
    return s;
  },
  logout: async (): Promise<void> => {
    try {
      await request("/api/auth/logout", { method: "POST" });
    } catch {
      // Already expired, revoked, or the server is unreachable. None of those
      // are reasons to stay signed in on this device — and without the catch,
      // a 401 here would throw past the caller and leave it on the chat screen.
    } finally {
      await setToken(null);
    }
  },
  me: () => request<Session>("/api/auth/me"),

  // ── memory ───────────────────────────────────────────────────────────────
  storeNote: (text: string) =>
    request<{ pending: PendingWrite[]; chunked: boolean }>(
      "/api/notes",
      json({ text, context_line: "" })
    ),

  storePhoto: async (image: PickedImage, caption: string) => {
    const { base64, mediaType } = await readImage(image);
    return request<{ pending: PendingWrite[]; photo_id: string }>(
      "/api/photos/base64",
      json({ caption, image_base64: base64, media_type: mediaType })
    );
  },

  ask: (question: string) =>
    request<Answer>("/api/ask", json({ question, with_evidence: false })),

  context: (question: string) =>
    request<{ raw: string; parsed: ParsedContext }>("/api/context", json({ question })),

  askWithPhoto: async (image: PickedImage, question: string) => {
    const { base64, mediaType } = await readImage(image);
    return request<PhotoAnswer>(
      "/api/photos/ask-base64",
      json({ question, image_base64: base64, media_type: mediaType })
    );
  },

  pending: () => request<PendingWrite[]>("/api/pending"),

  // ── chat sessions ────────────────────────────────────────────────────────
  // Organisation only. Every session reads and writes the same memory, so a
  // fact mentioned in one conversation is answerable from any other.
  chats: () => request<ChatSummary[]>("/api/chats"),
  createChat: () => request<ChatSummary>("/api/chats", json({ title: "" })),
  chat: (id: string) =>
    request<{ id: string; title: string; messages: StoredMessage[] }>(`/api/chats/${id}`),
  appendMessages: (id: string, messages: StoredMessage[]) =>
    request<{ id: string; title: string }>(`/api/chats/${id}/messages`, json({ messages })),
  deleteChat: (id: string) =>
    request<{ ok: boolean }>(`/api/chats/${id}`, { method: "DELETE" }),

  // ── account ──────────────────────────────────────────────────────────────
  eraseData: (confirm: string) =>
    request<{ ok: boolean; deleted: ErasureReport }>(
      "/api/account/erase",
      json({ confirm })
    ),
  deleteAccount: (confirm: string) =>
    request<{ ok: boolean; deleted: ErasureReport }>("/api/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm }),
    }),
};
