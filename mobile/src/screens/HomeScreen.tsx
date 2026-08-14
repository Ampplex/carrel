import { useNavigation, useRoute } from "@react-navigation/native";
import type { Session } from "../api";
import { Chat } from "./Chat";
import { LoginScreen } from "./LoginScreen";

/**
 * Guards the chat.
 *
 * A session normally arrives as a route param — restored by the boot gate, or
 * handed over by the login screen. If it is somehow absent (a reload during
 * development, a deep link) then showing the sign-in form is the only honest
 * option: with no session there is no token, and every request would 401.
 */
export function HomeScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const session: Session | undefined = route.params?.session;

  if (!session) {
    return <LoginScreen />;
  }

  return (
    <Chat
      session={session}
      onSignOut={() => navigation.reset({ index: 0, routes: [{ name: "Login" }] })}
    />
  );
}
