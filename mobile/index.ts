// Must be the very first import in the app.
//
// @react-navigation/stack is built on react-native-gesture-handler, which
// installs its native handlers as a side effect of being imported. If anything
// else loads first, the navigator is constructed against handlers that do not
// exist yet — which surfaces as a bare "undefined is not a function" at startup,
// with nothing pointing at import order as the cause.
import "react-native-gesture-handler";

import { registerRootComponent } from "expo";

import App from "./App";

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
