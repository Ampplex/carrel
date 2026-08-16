/**
 * Sign release builds with a real key instead of the debug one.
 *
 * Expo's Android template ships `release { signingConfig signingConfigs.debug }`
 * — the debug keystore, whose private key is in the repository with the
 * password "android". Anything signed with it can be forged by anyone, and on
 * Android the signing key IS the app's identity: it decides who may publish an
 * update to an installed app.
 *
 * This exists as a plugin rather than a hand edit because `android/` is
 * generated and gitignored. Editing build.gradle directly works until the next
 * `expo prebuild`, which regenerates the file and silently restores debug
 * signing — a release build that looks identical and is signed with a key
 * everybody has. A plugin is applied on every prebuild, so the property cannot
 * quietly disappear.
 *
 * Credentials come from ~/.gradle/gradle.properties, outside the repo:
 *
 *   CARREL_RELEASE_STORE_FILE=carrel-release.keystore
 *   CARREL_RELEASE_KEY_ALIAS=carrel
 *   CARREL_RELEASE_STORE_PASSWORD=...
 *   CARREL_RELEASE_KEY_PASSWORD=...
 *
 * With those absent the build falls back to debug signing, so a fresh clone
 * still builds rather than failing with an unexplained Gradle error. That
 * fallback is deliberate but it does mean a release APK built without the
 * credentials is NOT publishable — check the fingerprint before shipping one:
 *
 *   apksigner verify --print-certs app-release.apk
 */

const { withAppBuildGradle } = require("expo/config-plugins");

const SIGNING_CONFIG = `
        release {
            if (project.hasProperty('CARREL_RELEASE_STORE_PASSWORD')) {
                storeFile file(CARREL_RELEASE_STORE_FILE)
                storePassword CARREL_RELEASE_STORE_PASSWORD
                keyAlias CARREL_RELEASE_KEY_ALIAS
                keyPassword CARREL_RELEASE_KEY_PASSWORD
            }
        }`;

module.exports = function withReleaseSigning(config) {
  return withAppBuildGradle(config, (mod) => {
    let gradle = mod.modResults.contents;

    // Idempotent: prebuild may run repeatedly, and a second copy of the block
    // is a Gradle syntax error rather than a harmless duplicate.
    if (!gradle.includes("CARREL_RELEASE_STORE_PASSWORD")) {
      gradle = gradle.replace(
        /signingConfigs \{/,
        `signingConfigs {${SIGNING_CONFIG}`
      );

      // The release build type points at the debug config in the template.
      gradle = gradle.replace(
        /(buildTypes \{[\s\S]*?release \{[\s\S]*?)signingConfig signingConfigs\.debug/,
        `$1signingConfig project.hasProperty('CARREL_RELEASE_STORE_PASSWORD')\n                ? signingConfigs.release\n                : signingConfigs.debug`
      );
    }

    mod.modResults.contents = gradle;
    return mod;
  });
};
