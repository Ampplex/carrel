/**
 * Sign in with Google.
 *
 * ── What has to exist before this works ──────────────────────────────────────
 *
 * This cannot run in Expo Go. Google will not accept the `exp://` redirect URIs
 * Expo Go hands out, and the proxy that used to bridge that gap was removed in
 * SDK 48. It needs a development build:
 *
 *     npx expo run:ios          (or: eas build --profile development)
 *
 * And it needs OAuth clients, created in the Google Cloud Console under the
 * same project as the IDs below:
 *
 *   iOS      — bundle id must match `ios.bundleIdentifier` in app.json
 *   Android  — package name plus the signing certificate's SHA-1 fingerprint
 *   Web      — used by the web target, and as an audience the server accepts
 *
 * Each platform gets its own client id, and the ID token carries whichever one
 * the running build used in its `aud` claim. That is why the backend takes a
 * list (GOOGLE_CLIENT_IDS) rather than a single value: it has to accept the iOS
 * client on an iPhone and the Android one on a phone.
 *
 * ── About the web client id below ────────────────────────────────────────────
 *
 * It is Reeve's, taken from reeve-site, which is what makes it work today
 * without any new setup. The consequence is worth knowing: an ID token minted
 * for reeve.co.in's sign-in page will also be accepted by Carrel's backend,
 * because both name the same audience. For a coursework project sharing one
 * Google Cloud project that is fine. To separate them, create a Carrel-specific
 * client and replace this value here and in backend/.env.
 *
 * Client ids are public — they ship inside every copy of the app and appear in
 * the browser's network tab. They are identifiers, not secrets, which is why
 * this file is committed. A client *secret* would never belong here.
 */

import { useCallback, useEffect, useRef } from "react";
import { Platform } from "react-native";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";

// Closes the browser tab and delivers the result back to the app when the
// redirect lands. Must run at module scope, before any auth request exists.
WebBrowser.maybeCompleteAuthSession();

export const GOOGLE_CLIENT_IDS = {
  ios: "906486716708-1a416qkttft2c72n1abgarr3pic1h02c.apps.googleusercontent.com",
  android: "906486716708-g1qlohftjcgn6fb3njf2bjnqs16e8kk7.apps.googleusercontent.com",
  // Different project number from the Android client above, because this one is
  // Reeve's and the Android client is Carrel's own. Mixing projects works: the
  // server checks each token's audience against the whole list and does not
  // care which project minted it. What does differ is the consent screen —
  // people see the one belonging to whichever project issued their token.
  web: "230344192580-2vkurrmvpnfm74v5e01mmcm13himtd2n.apps.googleusercontent.com",
};

/**
 * Whether *this* platform can sign in with Google.
 *
 * Per-platform, not "is any id set anywhere". `useIdTokenAuthRequest` throws
 * during render — a red screen, not a failed request — when the id for the
 * platform it is running on is missing, and it does not care that one of the
 * others is present. Checking for any id at all let the hook run on iOS with
 * only a Web id configured, which took down the entire sign-in screen.
 *
 * So iOS asks for the iOS id, Android for the Android one, and the button
 * simply does not appear where it could not have worked.
 */
export function googleConfigured(): boolean {
  return Boolean(
    Platform.select({
      ios: GOOGLE_CLIENT_IDS.ios,
      android: GOOGLE_CLIENT_IDS.android,
      default: GOOGLE_CLIENT_IDS.web,
    })
  );
}

/**
 * Ask for an ID token, not an access token.
 *
 * An access token proves a Google session exists; it does not say which app it
 * was issued to, so a server cannot tell one meant for it from one meant for
 * somebody else. An ID token is a signed JWT naming its audience, which is what
 * lets the backend refuse tokens minted for other applications. The whole
 * argument is in backend/app/google_auth.py.
 */
export function useGoogleSignIn(
  onIdToken: (idToken: string) => void,
  onError: (message: string) => void
) {
  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    iosClientId: GOOGLE_CLIENT_IDS.ios || undefined,
    androidClientId: GOOGLE_CLIENT_IDS.android || undefined,
    webClientId: GOOGLE_CLIENT_IDS.web || undefined,
    // openid is what makes the token exchange return an ID token at all;
    // without it we would get an access token and nothing to verify.
    scopes: ["openid", "profile", "email"],
    // Stated outright rather than inferred, because the inference is broken
    // here. The provider builds its native redirect from
    // `Application.applicationId`, which comes from expo-application — a
    // package this project does not have. So it read `undefined`, produced
    // "undefined:/oauthredirect", and makeRedirectUri quietly fell back to the
    // dev server's address: http://localhost:8081. Google refuses that outright
    // ("Access blocked"), because native OAuth clients accept only custom
    // schemes, never http.
    //
    // Android registers the scheme as the package name; iOS as the reversed
    // client id, which is the one already claimed in app.json.
    redirectUri: Platform.select({
      android: "com.ampplex.carrel:/oauthredirect",
      ios: "com.googleusercontent.apps.906486716708-1a416qkttft2c72n1abgarr3pic1h02c:/oauthredirect",
      default: undefined,
    }),
  });

  // Held in refs so the effect below depends on the response alone. With the
  // callbacks in the dependency list, every render of the parent would re-run
  // it and sign the same token in repeatedly.
  const handleToken = useRef(onIdToken);
  const handleError = useRef(onError);
  handleToken.current = onIdToken;
  handleError.current = onError;

  useEffect(() => {
    if (!response) return;
    if (response.type === "success") {
      const idToken = response.params?.id_token;
      if (idToken) handleToken.current(idToken);
      else handleError.current("Google signed you in but sent no identity token.");
    } else if (response.type === "error") {
      handleError.current(response.error?.message ?? "Google sign-in did not complete.");
    }
    // "cancel" and "dismiss" are the user closing the sheet. Saying nothing is
    // the correct response to somebody changing their mind.
  }, [response]);

  const start = useCallback(() => {
    if (!request) {
      handleError.current(
        "Google sign-in is not set up in this build. It needs a development build and the client ids in src/googleAuth.ts."
      );
      return;
    }
    promptAsync();
  }, [request, promptAsync]);

  return { ready: Boolean(request), start };
}
