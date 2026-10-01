/**
 * Sign-in for the dashboard. With VITE_CLERK_PUBLISHABLE_KEY set this is simply Clerk.
 * Without a key it is local demo mode: everyone is treated as signed in and no token is sent,
 * which only works against a backend started with KINGUARD_DEV_OPEN=1 (it skips sign-in too).
 */
import * as Clerk from '@clerk/react'
import type { ReactNode } from 'react'

export const CLERK_KEY: string = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ?? ''
export const LOCAL_DEMO = !CLERK_KEY.startsWith('pk_') || CLERK_KEY === 'pk_test_replace_me'

function LocalShow({ when, children }: { when: 'signed-in' | 'signed-out'; children?: ReactNode }) {
  return when === 'signed-in' ? <>{children}</> : null
}

function LocalUserButton() {
  return <span className="rounded-md bg-warn-soft px-2 py-1 text-xs font-semibold text-warn">Local demo: no sign-in</span>
}

function Passthrough({ children }: { children?: ReactNode }) {
  return <>{children}</>
}

export const ClerkProvider = LOCAL_DEMO ? Passthrough : Clerk.ClerkProvider
export const ClerkLoading = LOCAL_DEMO ? () => null : Clerk.ClerkLoading
export const Show = (LOCAL_DEMO ? LocalShow : Clerk.Show) as typeof LocalShow
export const UserButton = LOCAL_DEMO ? LocalUserButton : Clerk.UserButton
export const SignInButton = (LOCAL_DEMO ? Passthrough : Clerk.SignInButton) as typeof Clerk.SignInButton
export const SignUpButton = (LOCAL_DEMO ? Passthrough : Clerk.SignUpButton) as typeof Clerk.SignUpButton
export const useAuth = LOCAL_DEMO ? () => ({ getToken: async () => null as string | null }) : Clerk.useAuth

const GMAIL_READ = 'https://www.googleapis.com/auth/gmail.readonly'

/**
 * Sends the signed-in person back to Google asking only for permission to read their Gmail. Needed when they
 * signed in but did not tick Gmail access, or signed up without Google: Google remembers the earlier answer
 * and does not ask again by itself. Null in local demo mode, where there is no Google sign-in.
 */
function useClerkGrantGmail(): (() => Promise<void>) | null {
  const { user } = Clerk.useUser()
  if (!user) return null
  return async () => {
    const redirectUrl = window.location.href
    const google = user.externalAccounts.find((account) => account.provider === 'google')
    const pending = google
      ? await google.reauthorize({ additionalScopes: [GMAIL_READ], redirectUrl })
      : await user.createExternalAccount({ strategy: 'oauth_google', additionalScopes: [GMAIL_READ], redirectUrl })
    const next = pending.verification?.externalVerificationRedirectURL
    if (!next) throw new Error('Google did not return a sign-in page. Try again.')
    window.location.href = next.toString()
  }
}

export const useGrantGmail: () => (() => Promise<void>) | null = LOCAL_DEMO ? () => null : useClerkGrantGmail
