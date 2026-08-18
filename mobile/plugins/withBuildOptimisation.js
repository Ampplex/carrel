/**
 * Turn on R8 and resource shrinking for release builds.
 *
 * Expo's template ships both off, so a release build carries every class and
 * drawable that any dependency happens to include. Measured on this app:
 * 51.2 MB → 49.5 MB for the bundle, 75.7 → 70.9 for the APK. The saving is
 * modest because most of the weight is native libraries, which R8 does not
 * touch and which Play splits per device anyway — what anyone actually
 * downloads is far smaller than the .aab.
 *
 * This is a plugin rather than two lines in `android/gradle.properties` for the
 * same reason the signing config is: `android/` is generated and gitignored, so
 * a hand edit survives exactly until the next `expo prebuild` and then
 * disappears without a word. A plugin is reapplied every time.
 *
 * The flag names matter more than they look. This template reads
 * `android.enableMinifyInReleaseBuilds`; setting the more commonly cited
 * `android.enableProguardInReleaseBuilds` leaves code shrinking off while
 * resource shrinking is on, and Gradle refuses that combination outright with
 * "Removing unused resources requires unused code shrinking to be turned on".
 *
 * One standing caution: minification is the setting here that can pass a build
 * and fail at runtime, because React Native and Expo resolve classes by
 * reflection. Expo's proguard-rules.pro carries the keep rules, but any release
 * built with this on should be installed and exercised on a device — cold
 * start, one streamed reply, one memory question — before it is shipped.
 */

const { withGradleProperties } = require("expo/config-plugins");

const FLAGS = {
  "android.enableMinifyInReleaseBuilds": "true",
  "android.enableShrinkResourcesInReleaseBuilds": "true",
};

module.exports = function withBuildOptimisation(config) {
  return withGradleProperties(config, (cfg) => {
    for (const [key, value] of Object.entries(FLAGS)) {
      const existing = cfg.modResults.find(
        (item) => item.type === "property" && item.key === key
      );
      if (existing) existing.value = value;
      else cfg.modResults.push({ type: "property", key, value });
    }
    return cfg;
  });
};
