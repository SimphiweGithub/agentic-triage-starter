import type { CapacitorConfig } from '@capacitor/cli'

// The Android app loads the built front end from the phone and talks to the KinGuard server over the network.
const config: CapacitorConfig = {
  appId: 'za.kinguard.app',
  appName: 'KinGuard',
  webDir: 'dist',
  server: {
    androidScheme: 'https',
    cleartext: true, // the demo server runs on plain http on the laptop
  },
  android: {
    allowMixedContent: true, // lets the https app page call that http server
  },
}

export default config
