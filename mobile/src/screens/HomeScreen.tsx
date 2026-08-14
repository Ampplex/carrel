import { useNavigation, useRoute } from "@react-navigation/native";
import { Session, api } from "../api";
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
      /**
       * Sign out has to end the session, not just leave the screen.
       *
       * This used to navigate and nothing else. The token stayed in the
       * keychain and stayed valid on the server, so the next launch found it,
       * validated it, and went straight back into the chat — signing out
       * appeared to work and then undid itself. Worse, anyone who picked up the
       * phone afterwards had a working session sitting in the keychain.
       *
       * api.logout revokes it server-side and clears the keychain, and never
       * throws: leaving is not something that can fail.
       */
      onSignOut={async () => {
        await api.logout();
        navigation.reset({ index: 0, routes: [{ name: "Login" }] });
      }}
    />
  );
}
