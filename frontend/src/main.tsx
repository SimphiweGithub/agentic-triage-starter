import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'
import { Capacitor } from '@capacitor/core'
import './index.css'
import App from './App.tsx'
import { PhoneApp } from './phone/PhoneApp'
import { Toaster } from './components/ui/sonner'
import { TooltipProvider } from './components/ui/tooltip'

// The theme follows the device: shadcn's dark tokens apply under the .dark class.
const dark = window.matchMedia('(prefers-color-scheme: dark)')
const applyTheme = () => document.documentElement.classList.toggle('dark', dark.matches)
applyTheme()
dark.addEventListener('change', applyTheme)

// On the phone, the protected person's view: no sign-in, because Google blocks sign-in inside app web views.
// In a browser, the caregiver's dashboard behind Clerk sign-in.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {Capacitor.isNativePlatform() ? (
      <PhoneApp />
    ) : (
      <ClerkProvider>
        <TooltipProvider>
          <App />
          <Toaster position="bottom-right" />
        </TooltipProvider>
      </ClerkProvider>
    )}
  </StrictMode>,
)
