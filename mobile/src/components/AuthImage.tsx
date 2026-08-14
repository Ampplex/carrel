/**
 * A photo from the API, which means a photo behind a bearer token.
 *
 * `<Image source={{uri, headers}}>` is the documented way to do this and it
 * does not work on Android here — every request arrived at the server without
 * the header and came back 401, which renders as an empty box. It worked on
 * iOS, which is exactly the kind of split that gets shipped by accident.
 *
 * So the bytes are fetched the same way every other authenticated request is
 * made, written to the cache directory, and rendered from a file:// path that
 * needs no headers at all. That also gives real caching: a photo is downloaded
 * once per device, not once per render, and it survives app restarts.
 *
 * The credential stays in a header throughout. Putting the token in the URL
 * would have been two lines shorter and would have written it into every
 * server log on the way.
 *
 * Failure is drawn rather than left blank. A grey rectangle is indistinguish-
 * able from a photo that has not loaded yet, from one that failed, and from a
 * layout bug — so a failed load says so.
 */

import { useEffect, useState } from "react";
import * as FileSystem from "expo-file-system/legacy";
import {
  ActivityIndicator,
  Image,
  ImageStyle,
  StyleProp,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { authHeaders, needsAuth } from "../api";
import { theme as t } from "../theme";

const CACHE_DIR = `${FileSystem.cacheDirectory}carrel-photos/`;

/** One file per remote photo, named after the id already in its URL. */
function cachePathFor(uri: string): string {
  const id = uri.replace(/[^a-zA-Z0-9]/g, "_").slice(-64);
  return `${CACHE_DIR}${id}.img`;
}

export function AuthImage({ uri, style }: { uri: string; style?: StyleProp<ImageStyle> }) {
  const [local, setLocal] = useState<string | null>(needsAuth(uri) ? null : uri);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    // A local file:// or a third-party URL needs none of this.
    if (!needsAuth(uri)) {
      setLocal(uri);
      return;
    }

    (async () => {
      const path = cachePathFor(uri);
      try {
        const existing = await FileSystem.getInfoAsync(path);
        if (existing.exists && existing.size && existing.size > 0) {
          if (!cancelled) setLocal(path);
          return;
        }

        await FileSystem.makeDirectoryAsync(CACHE_DIR, { intermediates: true }).catch(
          () => undefined // already there
        );

        const result = await FileSystem.downloadAsync(uri, path, {
          headers: await authHeaders(),
        });

        if (cancelled) return;
        if (result.status === 200) {
          setLocal(path);
        } else {
          // Delete it: downloadAsync writes the error body to the file, and a
          // cached 401 page would masquerade as a photo forever after.
          await FileSystem.deleteAsync(path, { idempotent: true }).catch(() => undefined);
          setFailed(true);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [uri]);

  if (failed) {
    return (
      <View style={[style, s.placeholder]}>
        <Text style={s.placeholderText}>Photo unavailable</Text>
      </View>
    );
  }

  if (!local) {
    return (
      <View style={[style, s.placeholder]}>
        <ActivityIndicator size="small" color={t.color.inkTertiary} />
      </View>
    );
  }

  return <Image source={{ uri: local }} style={style} onError={() => setFailed(true)} />;
}

const s = StyleSheet.create({
  placeholder: {
    backgroundColor: t.color.card,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.border,
  },
  placeholderText: { color: t.color.inkTertiary, ...t.text.small },
});
