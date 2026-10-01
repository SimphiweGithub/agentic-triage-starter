import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { PersonRecord } from './types'

/** Who someone is in a protected person's care circle. */
export type CircleRole = 'protected' | 'next_of_kin' | 'caregiver' | 'helper'

export type CircleMember = {
  id: string
  name: string
  relation: string
  role: CircleRole
  /** A short line such as "Phone paired" or "Invite sent". */
  status: string
  /** The signed-in user. */
  you?: boolean
}

export const ROLE: Record<CircleRole, { label: string; summary: string; chip: string; avatar: string }> = {
  protected: {
    label: 'Protected person',
    summary: 'Gets plain warnings and call tips on their phone, and answers “is this yours?” questions.',
    chip: 'bg-primary/12 text-primary',
    avatar: 'bg-primary text-primary-foreground',
  },
  next_of_kin: {
    label: 'Next of kin',
    summary: 'Sees everything and approves disputes and debit blocks.',
    chip: 'bg-kin-soft text-kin',
    avatar: 'bg-kin text-background',
  },
  caregiver: {
    label: 'Caregiver',
    summary: 'Sees alerts and calls and checks in. Can suggest, not approve, anything about money.',
    chip: 'bg-info-soft text-info',
    avatar: 'bg-info text-background',
  },
  helper: {
    label: 'Trusted helper',
    summary: 'A neighbour or friend. Pinged only for urgent calls, never sees message text.',
    chip: 'bg-helper-soft text-helper',
    avatar: 'bg-helper text-background',
  },
}

/** Roles that can be given by invite, most trusted first. */
export const INVITE_ROLES: CircleRole[] = ['next_of_kin', 'caregiver', 'helper']

type Access = 'yes' | 'no' | 'own' | 'suggest' | 'urgent' | 'no-kin' | 'remove'

export const ACCESS_WORD: Record<Access, string> = {
  yes: 'Yes',
  no: '—',
  own: 'Own',
  suggest: 'Suggest',
  urgent: 'Urgent only',
  'no-kin': 'If no kin',
  remove: 'Remove',
}

/** What each role may do. The server must enforce the same table; the screen only explains it. */
export const PERMISSIONS: { label: string; access: Record<CircleRole, Access> }[] = [
  { label: 'See warnings about their messages', access: { protected: 'own', next_of_kin: 'yes', caregiver: 'yes', helper: 'no' } },
  { label: 'Read the full message text', access: { protected: 'own', next_of_kin: 'yes', caregiver: 'yes', helper: 'no' } },
  { label: 'See call activity (number, time, length)', access: { protected: 'own', next_of_kin: 'yes', caregiver: 'yes', helper: 'no' } },
  { label: 'Get pinged about a risky call', access: { protected: 'no', next_of_kin: 'yes', caregiver: 'yes', helper: 'urgent' } },
  { label: 'Approve a dispute or debit block', access: { protected: 'no-kin', next_of_kin: 'yes', caregiver: 'suggest', helper: 'no' } },
  { label: 'Mark a company as trusted', access: { protected: 'yes', next_of_kin: 'yes', caregiver: 'suggest', helper: 'no' } },
  { label: 'Pair and manage devices', access: { protected: 'no', next_of_kin: 'yes', caregiver: 'yes', helper: 'no' } },
  { label: 'Invite or remove people', access: { protected: 'remove', next_of_kin: 'yes', caregiver: 'no', helper: 'no' } },
]

export function canApprove(role: CircleRole | undefined): boolean {
  return role === undefined || role === 'next_of_kin'
}

export function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || '?'
}

/** Until the server lists the circle, it is the person and the signed-in user, whose role follows whether a guardian is enrolled. */
function fallbackCircle(person: PersonRecord, guardian: boolean | undefined): CircleMember[] {
  return [
    { id: person.id, name: person.name, relation: person.relation, role: 'protected', status: 'Being looked after' },
    { id: 'you', name: 'You', relation: '', role: guardian === false ? 'caregiver' : 'next_of_kin', status: 'Signed in', you: true },
  ]
}

/**
 * Everyone in one person's care circle. `listed` is false while the server has no circle route, so the
 * screen can say that only the two of you are shown.
 */
export function useCircle(person: PersonRecord, guardian: boolean | undefined, intervalMs = 15000) {
  const [members, setMembers] = useState<CircleMember[] | null>(null)
  const [listed, setListed] = useState<boolean | null>(null)

  const refresh = useCallback(async () => {
    try {
      setMembers(await api<CircleMember[]>(`/people/${person.id}/circle`))
      setListed(true)
    } catch {
      setMembers(null)
      setListed(false)
    }
  }, [person.id])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, intervalMs])

  const shown = members ?? fallbackCircle(person, guardian)
  const you = shown.find((item) => item.you)
  return { members: shown, listed, you, refresh }
}

export type CircleInvite = { token: string; role: CircleRole; name: string; expires_at: string }

export function circleInviteLink(invite: { token: string }): string {
  return `${window.location.origin}/?invite=${invite.token}`
}
