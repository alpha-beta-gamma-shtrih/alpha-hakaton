import type { Draft, Revision } from '../../../api/types'

type NeedTerms = Pick<Draft, 'requested_amount' | 'term_months' | 'purpose_code'> & {
  purchase_from_bank_partner: boolean
}

/** Values that change financing conditions; formatting and explanatory text do not. */
export function needTermsKey(terms: NeedTerms): string | null {
  const amount = Number(terms.requested_amount)
  if (!Number.isFinite(amount) || amount <= 0 || !terms.term_months || !Number.isInteger(terms.term_months) || terms.term_months < 1 || !terms.purpose_code) return null
  return JSON.stringify([amount, terms.term_months, terms.purpose_code, terms.purchase_from_bank_partner])
}

export function submittedNeedKey(revision: Revision): string | null {
  return needTermsKey({
    requested_amount: revision.requested_amount,
    term_months: revision.term_months,
    purpose_code: revision.purpose_code,
    purchase_from_bank_partner: revision.financial_snapshot.purchase_from_bank_partner === true,
  })
}

/** An old browser flag alone cannot confirm changed terms during a bank request. */
export function needConfirmation(isReply: boolean, currentKey: string | null, submittedKey: string | null, storedConfirmed: boolean, storedKey: string | null) {
  if (!isReply) return { confirmed: storedConfirmed, inherited: false }
  if (!currentKey || !submittedKey) return { confirmed: false, inherited: false }
  const inherited = currentKey === submittedKey
  return { confirmed: inherited || (storedConfirmed && storedKey === currentKey), inherited }
}
