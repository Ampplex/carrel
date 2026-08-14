import { useNavigation } from "@react-navigation/native";
import { markIntroSeen } from "../intro";
import { Onboarding } from "./Onboarding";

/**
 * Records that the intro has been seen so it never appears again — the boot
 * gate in App.tsx reads that flag to choose the launch screen.
 *
 * `useNavigation()` rather than a `navigation` prop: the static navigation API
 * does not pass one down, so reading it from props gave `undefined` and every
 * tap threw "Cannot read property 'reset' of undefined". The hook works under
 * both the static and dynamic APIs.
 *
 * `reset` rather than `navigate`: swiping back into a finished intro is not
 * something anyone wants.
 */
export function OnboardingScreen() {
  const navigation = useNavigation<any>();
  return (
    <Onboarding
      onDone={async () => {
        await markIntroSeen();
        navigation.reset({ index: 0, routes: [{ name: "Login" }] });
      }}
    />
  );
}
