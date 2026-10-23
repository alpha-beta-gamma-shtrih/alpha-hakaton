// Synthetic demo-0.2 dataset (copied from demo_data/demo_0_2) for the in-browser demo API.
import type { FinancialMonth, Product } from '../types'

export interface DemoUser {
  key: string
  id: string
  email: string
  display_name: string
  role: 'CLIENT' | 'BANK_STAFF'
}

export const DEMO_USERS: DemoUser[] = [
  { key: 'CLIENT_C01', id: 'a98a8a6c-f159-5da9-b047-2ec9b9b2b7ee', email: 'client@example.com', display_name: 'Демо-клиент C01', role: 'CLIENT' },
  { key: 'CLIENT_C02', id: 'b17c2d1e-2a40-5c8e-9d11-4e0c5f6a7b80', email: 'client2@example.com', display_name: 'Демо-клиент C02', role: 'CLIENT' },
  { key: 'BANK_01', id: 'c3d4e5f6-0718-5293-a4b5-c6d7e8f90a1b', email: 'bank@example.com', display_name: 'Демо-сотрудник 1', role: 'BANK_STAFF' },
  { key: 'BANK_02', id: 'd4e5f607-1829-53a4-b5c6-d7e8f90a1b2c', email: 'bank2@example.com', display_name: 'Демо-сотрудник 2', role: 'BANK_STAFF' },
]

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
  members: string[]
}

export const DEMO_COMPANIES: DemoCompany[] = [
  {
    key: 'C01',
    id: 'c57f3cbf-c701-5e3a-9eb4-34ada623e49a',
    legal_name: 'ООО «ДЕМО — Северный товар»',
    legal_form: 'OOO',
    inn: '0000000001',
    registration_number: '0000000000001',
    registered_on: '2022-10-01',
    okved_code: '46.90',
    region_code: '77',
    business_description: 'Вымышленная компания для проверки сохранения заявки; устойчивый профиль.',
    members: [DEMO_USERS[0].id],
  },
  {
    key: 'C02',
    id: 'e8f90a1b-2c3d-5e4f-8a6b-7c8d9e0f1a2b',
    legal_name: 'ООО «ДЕМО — Южный склад»',
    legal_form: 'OOO',
    inn: '0000000002',
    registration_number: '0000000000002',
    registered_on: '2023-10-01',
    okved_code: '47.19',
    region_code: '78',
    business_description: 'Вымышленная компания с высокой нагрузкой; отдельный клиент для проверки доступа.',
    members: [DEMO_USERS[1].id],
  },
]

const MONTHS = ['2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01', '2026-08-01', '2026-09-01']
const row = (cash_inflow: string, operating_outflow: string, existing_debt_payment: string) =>
  MONTHS.map((month): FinancialMonth => ({ month, cash_inflow, operating_outflow, existing_debt_payment }))

export const DEMO_MONTHS: Record<string, FinancialMonth[]> = {
  C01: row('1200000.00', '850000.00', '30000.00'),
  C02: row('800000.00', '600000.00', '100000.00'),
}

export const BKI: Record<string, { history_present: boolean; current_monthly_payment: string; current_overdue_amount: string; max_overdue_days_12m: number }> = {
  C01: { history_present: true, current_monthly_payment: '30000.00', current_overdue_amount: '0.00', max_overdue_days_12m: 0 },
  C02: { history_present: true, current_monthly_payment: '100000.00', current_overdue_amount: '0.00', max_overdue_days_12m: 0 },
}

export const DEMO_PRODUCT: Product = {
  id: '65340619-1b94-5882-8b01-54e8b9f86394',
  code: 'WC_DEMO',
  version: 2,
  name: 'Оборотный кредит — демонстрационные условия',
  description: 'Синтетический продукт demo-0.2. Реальное кредитование и выдача не выполняются.',
  min_amount: '100000.00',
  max_amount: '5000000.00',
  min_term_months: 6,
  max_term_months: 24,
  annual_rate_percent: '24.000',
  currency: 'RUB',
  allowed_purposes: ['INVENTORY', 'OPERATING_EXPENSES', 'SEASONAL_PURCHASE'],
  policy_version: 'demo-policy-0.2',
}
