import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'
import { Capacitor } from '@capacitor/core'
import './index.css'
import App from './App.tsx'
import { PhoneApp } from './phone/PhoneApp'

// On the phone, the protected person's view: no sign-in, because Google blocks sign-in inside app web views.
// In a browser, the caregiver's dashboard behind Clerk sign-in.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {Capacitor.isNativePlatform() ? (
      <PhoneApp />
    ) : (
      <ClerkProvider>
        <App />
      </ClerkProvider>
    )}
  </StrictMode>,
)
