/**
 * A full-screen panel that slides up over whatever is behind it.
 *
 * Deliberately NOT React Native's <Modal>, and the reason is a bug worth
 * recording. On iOS a Modal is a real UIKit presentation. Asking to present one
 * while another is still on screen does not queue and does not warn — it simply
 * does nothing, and it can leave the presentation stack believing something is
 * still up. Every later Modal then fails too.
 *
 * That is precisely what "Settings" from inside the conversations drawer did:
 * the drawer began its slide-out and opened Settings 180ms later, while its own
 * modal was still presented. Settings never appeared, and from that point the
 * drawer would not open again either — two dead buttons from one race, on iOS
 * only, because Android presents modals as plain views and forgives it.
 *
 * An overlay in the ordinary view tree has no presentation stack to wedge. It
 * costs the slide animation, which is twelve lines, and the Android back
 * button, which a Modal would have handled through onRequestClose.
 *
 * The drawer itself stays a Modal: it is the only one left, and a lone modal
 * has nothing to collide with.
 */

import { useEffect, useRef, useState } from "react";
import {
  Animated,
  BackHandler,
  Easing,
  StyleSheet,
  useWindowDimensions,
} from "react-native";
import { theme as t } from "../theme";

export function Sheet({
  open,
  onClose,
  /** Stacking order. A sheet opened from inside another needs the higher one. */
  level = 10,
  children,
}: {
  open: boolean;
  onClose: () => void;
  level?: number;
  children: React.ReactNode;
}) {
  // Kept mounted through the closing animation — unmounting on `open` alone
  // would make the panel vanish rather than slide away.
  const [mounted, setMounted] = useState(open);
  const anim = useRef(new Animated.Value(0)).current;
  const { height } = useWindowDimensions();

  useEffect(() => {
    if (open) {
      setMounted(true);
      Animated.timing(anim, {
        toValue: 1,
        duration: 220,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }).start();
    } else if (mounted) {
      Animated.timing(anim, {
        toValue: 0,
        duration: 170,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }).start(({ finished }) => finished && setMounted(false));
    }
  }, [open]);

  // What onRequestClose gave us for free. Without it the back button would exit
  // the app from a settings screen, which reads as a crash.
  useEffect(() => {
    if (!mounted) return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      onClose();
      return true;
    });
    return () => sub.remove();
  }, [mounted, onClose]);

  if (!mounted) return null;

  return (
    <Animated.View
      style={[
        StyleSheet.absoluteFill,
        {
          zIndex: level,
          elevation: level,
          // Opaque, or the screen underneath shows through a panel that is
          // meant to have replaced it.
          backgroundColor: t.color.bg,
          opacity: anim,
          transform: [
            {
              translateY: anim.interpolate({
                inputRange: [0, 1],
                // A short rise rather than a full-height slide: the distance is
                // what makes a transition feel slow, not the duration.
                outputRange: [Math.min(height * 0.06, 48), 0],
              }),
            },
          ],
        },
      ]}
    >
      {children}
    </Animated.View>
  );
}
