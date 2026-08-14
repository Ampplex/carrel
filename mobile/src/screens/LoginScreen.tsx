import { useNavigation } from "@react-navigation/native";
import type { Session } from "../api";
import { Auth } from "./Auth";

/**
 * `reset` rather than `navigate`: once signed in, the back gesture must not
 * return to a login form the user has already satisfied.
 *
 * Navigation comes from the hook because the static API does not pass it as a
 * prop — see OnboardingScreen for the failure that taught us this.
 */
export function LoginScreen() {
  const navigation = useNavigation<any>();
  return (
    <Auth
      onSignedIn={(session: Session) =>
        navigation.reset({ index: 0, routes: [{ name: "Home", params: { session } }] })
      }
    />
  );
}
