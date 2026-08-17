/**
 * Carrel — onboarding, sign in, chat. Nothing else.
 *
 * The navigator itself is trivial; the part worth reading is the boot gate.
 * Before anything renders, two questions are answered: has this person seen the
 * intro, and is their stored session still good. Without that, a returning user
 * walks through onboarding and a login form every single launch, which is the
 * fastest way to make an app feel broken.
 *
 * The token is *validated against the server* rather than trusted for being
 * present. Tokens expire, get revoked, or belong to a backend that has since
 * been wiped — and discovering that at launch is far better than showing a chat
 * screen that fails on the first message.
 *
 * An unreachable server is deliberately NOT treated as being signed out. Those
 * are different problems with different fixes, and conflating them would send
 * someone hunting for their password when the real answer is "wrong wifi".
 */

import { useEffect, useMemo, useState } from "react";
import { createStaticNavigation } from "@react-navigation/native";
import { createStackNavigator, createStackScreen } from "@react-navigation/stack";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, Image, StyleSheet, Text, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { Session, api, loadToken } from "./src/api";
import { hasSeenIntro } from "./src/intro";
import { HomeScreen } from "./src/screens/HomeScreen";
import { LoginScreen } from "./src/screens/LoginScreen";
import { OnboardingScreen } from "./src/screens/OnboardingScreen";
import { theme as t } from "./src/theme";

type Boot =
  | { stage: "loading" }
  | { stage: "ready"; initial: "Onboarding" | "Login" | "Home"; session?: Session };

function buildNavigator(initial: string, session?: Session) {
  const stack = createStackNavigator({
    initialRouteName: initial as never,
    screenOptions: {
      headerShown: false,
      cardStyle: { backgroundColor: t.color.bg },
    },
    screens: {
      Onboarding: createStackScreen({ screen: OnboardingScreen }),
      Login: createStackScreen({ screen: LoginScreen }),
      Home: createStackScreen({
        screen: HomeScreen,
        // Carries the restored session straight into the chat so a returning
        // user never sees the login form. The static navigation API infers
        // param types from the screen component, which is untyped here, so it
        // lands on `undefined` — the cast supplies what the inference cannot.
        // HomeScreen treats a missing session as "show sign-in", so a wrong
        // shape degrades to the login form rather than crashing.
        initialParams: { session } as never,
      }),
    },
  });
  return createStaticNavigation(stack);
}

export default function App() {
  const [boot, setBoot] = useState<Boot>({ stage: "loading" });

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const seen = await hasSeenIntro();
      const token = await loadToken();

      if (token) {
        try {
          const me = await api.me();
          if (!cancelled) {
            setBoot({
              stage: "ready",
              initial: "Home",
              session: { token, email: me.email, name: me.name, avatar_url: me.avatar_url },
            });
          }
          return;
        } catch {
          // Dead token, or an unreachable backend. Either way the sign-in screen
          // is the right destination — it reports the specific failure itself.
        }
      }

      if (!cancelled) {
        setBoot({ stage: "ready", initial: seen ? "Login" : "Onboarding" });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const Navigation = useMemo(
    () =>
      boot.stage === "ready" ? buildNavigator(boot.initial, boot.session) : null,
    [boot]
  );

  // GestureHandlerRootView must wrap everything the stack navigator renders —
  // its swipe-back gesture is dead without it. SafeAreaProvider supplies the
  // insets that SafeAreaView reads; without it, insets resolve to zero and the
  // boot screen slides under the notch.
  return (
    <GestureHandlerRootView style={s.root}>
      <SafeAreaProvider>
        <StatusBar style="light" />
        {boot.stage === "loading" || !Navigation ? (
          <SafeAreaView style={s.boot}>
            {/* The same mark the system splash shows, on the same ground, so
                the handoff from splash to app has no visible seam — no flash
                of a different colour, no logo jumping to a new position. */}
            <Image source={require("./assets/splash-icon.png")} style={s.bootMark} />
            <ActivityIndicator color={t.color.accent} />
          </SafeAreaView>
        ) : (
          <View style={s.root}>
            <Navigation />
          </View>
        )}
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: t.color.bg },
  boot: {
    flex: 1,
    backgroundColor: t.color.bg,
    alignItems: "center",
    justifyContent: "center",
    gap: 20,
  },
  bootMark: { width: 240, height: 89, resizeMode: "contain" },
  bootBrand: {
    color: t.color.ink,
    fontSize: 30,
    fontWeight: "700",
    letterSpacing: -0.5,
  },
});
