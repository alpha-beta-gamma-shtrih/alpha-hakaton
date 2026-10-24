// Synthetic demo-0.3 dataset for the in-browser demo API.
// dataset.json is generated from demo_data/demo_0_3 by `npm run gen:mock` — do not edit it by hand.
import type { FinancialMonth, Product } from '../types'
import dataset from './dataset.json'

export interface DemoUser {
  key: string
  id: string
  email: string
  display_name: string
  role: 'CLIENT' | 'BANK_STAFF'
}

export interface DemoCompany {
  key: string
  id: string
  legal_name: string
  legal_form: 'OOO' | 'IP'
  inn: string
  registration_number: string | null
  registered_on: string
  okved_code: string
  region_code: string
  business_description: string | null
  /** Internal demo bank profile (bank_relationships.json); never sent by the client. */
  has_active_loan_in_our_bank: boolean
  members: string[]
}

export interface SourceFixture {
  company_key: string
  status: 'SUCCESS' | 'NO_DATA' | 'ERROR'
  error_code: string | null
  normalized_data: Record<string, unknown> | null
  run_no: number
  revision_no: number | null
}

export interface DemoScenario {
  key: string
  company_key: string
  requested_amount: string
  term_months: number
  purpose_code: string
  purchase_from_bank_partner: boolean
  sequence: string[]
  expected: { status: string; risk_score: number | null; reason_codes: string[] | null; annual_rate_percent: string | null; monthly_payment: string | null }
}

export const DEMO_USERS = dataset.users as DemoUser[]
export const DEMO_COMPANIES = dataset.companies as DemoCompany[]
export const DEMO_MONTHS = dataset.months as Record<string, FinancialMonth[]>
export const DEMO_FNS = dataset.fns as SourceFixture[]
export const DEMO_BKI = dataset.bki as SourceFixture[]
export const DEMO_PRODUCT = dataset.product as unknown as Product
export const CALCULATION_DATE = dataset.calculation_date
export const FINANCIAL_MONTHS = dataset.financial_months
export const REASON_TEXT = dataset.reasons as Record<string, string>
export const DEMO_SCENARIOS = dataset.scenarios as DemoScenario[]
