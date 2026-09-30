# Scam Stop on Android

The same front end, wrapped with Capacitor. On a phone it shows the protected
person's view, not the caregiver dashboard: it asks for consent, reads the SMS
inbox, sends each text to the Scam Stop server, and shows the warnings the
server writes, as notifications too.

## What runs where

| Part | File |
|---|---|
| Reading the inbox and hearing new texts | `android/app/src/main/java/za/kinguard/app/SmsInboxPlugin.java` (our own plugin) |
| Registering that plugin | `android/app/src/main/java/za/kinguard/app/MainActivity.java` |
| SMS and notification permissions, plain-http allowed | `android/app/src/main/AndroidManifest.xml` |
| The phone screen, sync and notifications | `src/phone/PhoneApp.tsx` |
| Phone or browser? | `src/main.tsx` |

One-time PINs, passwords and recovery codes are filtered on the phone before
anything is sent, using the patterns from `GET /api/privacy/patterns`. The
server filters them again.

## Build

From `frontend/`:

```powershell
npm install
npm run build
npx cap sync android
cd android
.\gradlew.bat assembleDebug
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`. The first
Gradle build downloads its tools and takes a few minutes. If Gradle fails with
"Unable to establish loopback connection", set
`JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:/some/short/folder` and retry.

## Install and connect

1. On the phone: Settings → About phone → Software information → tap **Build
   number** seven times, then turn on **USB debugging** in Developer options.
2. Plug the phone in and tap **Allow** on the USB debugging prompt.
3. Install and connect the phone's `localhost:8000` to the laptop's server:

```powershell
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
adb reverse tcp:8000 tcp:8000
```

4. On the laptop, `backend/.env` must allow the app's origin:
   `CORS_ORIGINS=https://localhost,http://localhost`.
5. Open Scam Stop on the phone, agree, and allow SMS access and notifications.

To use Wi-Fi instead of USB, start the backend with `--host 0.0.0.0` and put
the laptop's address, for example `http://192.168.1.20:8000`, under Settings
in the app.

## Limits to say out loud

- New texts are caught while the app is open or in the background; if Android
  closes the app, the next opening catches up from where it left off.
- Google Play only allows SMS reading for the default SMS app, so this is
  installed directly, not through the Play Store.
- The caregiver dashboard with Google sign-in stays in the browser, because
  Google blocks sign-in inside app web views.
