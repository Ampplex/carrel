/**
 * Turn on R8, resource shrinking, and R8's actual optimisation passes.
 *
 * Expo's template ships shrinking off, so a release build carries every class
 * and drawable that any dependency happens to include. Measured on this app:
 * 51.2 MB → 49.5 MB for the bundle, 75.7 → 70.9 for the APK. The saving is
 * modest because most of the weight is native libraries, which R8 does not
 * touch and which Play splits per device anyway — what anyone actually
 * downloads is far smaller than the .aab.
 *
 * This is a plugin rather than lines in `android/gradle.properties` for the
 * same reason the signing config is: `android/` is generated and gitignored, so
 * a hand edit survives exactly until the next `expo prebuild` and then
 * disappears without a word. A plugin is reapplied every time.
 *
 * Three things had to be right, and each was wrong in a different way:
 *
 * 1. The flag name. This template reads `android.enableMinifyInReleaseBuilds`;
 *    setting the more commonly cited `android.enableProguardInReleaseBuilds`
 *    leaves code shrinking off while resource shrinking is on, and Gradle
 *    refuses that combination with "Removing unused resources requires unused
 *    code shrinking to be turned on".
 *
 * 2. The default ProGuard config. The template uses `proguard-android.txt`,
 *    which contains a literal `-dontoptimize` — so R8 would shrink and rename
 *    but skip every optimisation pass. Play caught this and said plainly
 *    "Optimisation isn't enabled", which was true even though R8 was demonstrably
 *    running (a 26 MB mapping.txt is hard to argue with). The `-optimize`
 *    variant is byte-identical apart from dropping that one line, so this swaps
 *    to it.
 *
 * 3. Full mode. R8 full mode does the more aggressive interprocedural work and
 *    is the default from AGP 8, but it is set explicitly here so that the
 *    behaviour does not silently depend on which AGP version Expo pins next.
 *
 * One standing caution, and it grows with this change: optimisation is the
 * setting that can pass a build and fail at runtime, because React Native and
 * Expo resolve classes by reflection and R8's optimiser is more willing to
 * rewrite code than its shrinker. Expo's proguard-rules.pro carries the keep
 * rules, but any release built with this on should be installed and exercised
 * on a device — cold start, one streamed reply, one memory question — before it
 * is shipped.
 */

const { withGradleProperties, withAppBuildGradle } = require("expo/config-plugins");

const FLAGS = {
  "android.enableMinifyInReleaseBuilds": "true",
  "android.enableShrinkResourcesInReleaseBuilds": "true",
  // Explicit rather than inherited from the AGP default, so an Expo upgrade
  // cannot quietly change how aggressively the release build is optimised.
  "android.enableR8.fullMode": "true",
};

/** `proguard-android.txt` disables optimisation outright; this one does not. */
function useOptimizedProguardDefaults(config) {
  return withAppBuildGradle(config, (cfg) => {
    if (!cfg.modResults.contents.includes('getDefaultProguardFile("proguard-android.txt")')) {
      return cfg; // already swapped, or the template changed shape
    }
    cfg.modResults.contents = cfg.modResults.contents.replace(
      'getDefaultProguardFile("proguard-android.txt")',
      'getDefaultProguardFile("proguard-android-optimize.txt")'
    );
    return cfg;
  });
}

module.exports = function withBuildOptimisation(config) {
  const withFlags = withGradleProperties(config, (cfg) => {
    for (const [key, value] of Object.entries(FLAGS)) {
      const existing = cfg.modResults.find(
        (item) => item.type === "property" && item.key === key
      );
      if (existing) existing.value = value;
      else cfg.modResults.push({ type: "property", key, value });
    }
    return cfg;
  });
  return useOptimizedProguardDefaults(withFlags);
};
