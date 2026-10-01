# Scam Stop on Android

The phone is a **bridge**. Once it is paired and allowed, native Android code
forwards every new text and chat-app message to the Scam Stop server by itself,
with the app closed, and shows the warnings the server sends back as phone
notifications. The dashboard does everything else, including Gmail. The app's
own screen only sets the bridge up (pairing code, text access, WhatsApp
access, server address) and shows whether it is working.

```
New SMS ──► SmsReceiver (manifest, woken by Android) ─┐
WhatsApp ─► NotificationBridge (notification access) ─┼─► Forwarder ─► POST /api/people/{id}/intake/share/batch
                                                      │      (privacy filter, queue, X-Device-Key)
                                                      └─◄ decisions ─► warning notification on the phone
```

## What runs where

| Part | File |
|---|---|
| Sending to the server: privacy filter, queue, retry, warning notifications | `android/app/src/main/java/za/kinguard/app/Forwarder.java` |
| New texts, even with the app closed | `.../SmsReceiver.java`, declared in the manifest |
| WhatsApp, WhatsApp Business, Telegram, Messenger and Signal | `.../NotificationBridge.java`, a `NotificationListenerService` |
| First sync of the last week, bridge settings and status, opening Android's notification access screen | `.../SmsInboxPlugin.java` |
| Call reminders: hears a call ring and end, then shows common call scams | `.../CallReceiver.java`, declared in the manifest |
| Call reminders: permission, on/off, last call time | `.../CallMonitorPlugin.java`, `src/phone/calls.ts` |
| Registering the plugins | `.../MainActivity.java` |
| Permissions, the receiver and the listener service | `android/app/src/main/AndroidManifest.xml` |
| The set-up and status screen | `src/phone/PhoneApp.tsx` |
| Phone or browser? | `src/main.tsx` |

One-time PINs, passwords and recovery codes are filtered on the phone before
anything is sent, using the patterns from `GET /api/privacy/patterns`, which
the app hands to the native code when it pairs. The server filters them again.
Only the listed chat apps are read; every other app's notifications are
ignored and never sent. A text is not sent twice: the SMS app's notifications
are not on the list, and the bridge remembers a hash of the last 500 messages
because chat apps re-post earlier messages with every new one.

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
6. On the dashboard, open Devices → **Pair the phone app** for the person. Type
   the 10-character code into the app under Settings → Pairing code and tap
   **Pair this phone**. With `KINGUARD_DEV_OPEN=1` and no code, the app uses the
   first person the developer looks after.

To use Wi-Fi instead of USB, start the backend with `--host 0.0.0.0` and put
the laptop's address, for example `http://192.168.1.20:8000`, under Settings
in the app.

## Call reminders

When an incoming call ends, a notification lists common phone scams (bank,
"grandchild in trouble", prizes, SIM-swap codes, tax or fines, remote-access
apps) and the rule: hang up and call the number on your card yourself. If the
agent warned about a scam message in the 2 hours before the call, the
notification says so first, because scammers often text, then call.

`CallReceiver` only reads the phone's state: ringing, in a call, idle. It never
hears the call and never learns the number, which would need call-log access.
Android delivers this broadcast with the app closed. Outgoing calls are
ignored; a missed call and an answered one are worded differently. The person
can switch reminders off on the phone.

## Limits to say out loud

- WhatsApp is read from its notifications, so a message whose notification is
  muted or hidden by WhatsApp's own settings is not seen.
- Notification access is a special permission: Android only lets the person
  switch it on in Settings. On some phones a directly installed app needs
  App info → ⋮ → **Allow restricted settings** first.
- If the server cannot be reached, messages wait in a queue on the phone. The
  queue is retried with the next message, when the app opens (and every few
  seconds while it is open), and when the WhatsApp listener reconnects.
- A repeat of a scam is not acted on twice by the agent, but the phone shows
  the warning again, because the person has just received it again.
- On this laptop the Nox emulator starts its own adb, which takes the phone's
  USB link away. If the phone stops reaching the server, close Nox, restart
  adb and run `adb reverse tcp:8000 tcp:8000` again.
- Google Play only allows SMS reading for the default SMS app, so this is
  installed directly, not through the Play Store. The call reminders need only
  `READ_PHONE_STATE`, which Play allows.
- The call reminder is the same list of scams after every call: without the
  number it cannot tell a scammer from a friend, except through the timing of
  a recent scam message.
- The caregiver dashboard with Google sign-in stays in the browser, because
  Google blocks sign-in inside app web views.
- The phone does not sign in; it pairs with a code from the dashboard. Anyone
  holding that code can act as the person's phone until a new code replaces
  it, so it should be typed in, not sent around.
