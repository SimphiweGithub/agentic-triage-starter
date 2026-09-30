import type { CapacitorConfig } from '@capacitor/cli'

// The Android app loads the built front end from the phone and talks to the Scam Stop server over the network.
const config: CapacitorConfig = {
  appId: 'za.kinguard.app',
  appName: 'Scam Stop',
  webDir: 'dist',
  loggingBehavior: 'none', // otherwise debug builds write every message the plugin reads into the phone's system log
  server: {
    androidScheme: 'https',
    cleartext: true, // the demo server runs on plain http on the laptop
  },
  android: {
    allowMixedContent: true, // lets the https app page call that http server
  },
}

export default config
