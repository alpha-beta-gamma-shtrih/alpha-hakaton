import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { applications, catalog } from '../api/endpoints'
import { useToast } from '../components/ui'

export const useCompanies = () => useQuery({ queryKey: ['companies'], queryFn: catalog.companies, staleTime: 60_000 })
export const useCompany = (id?: string) => useQuery({ queryKey: ['company', id], queryFn: () => catalog.company(id!), enabled: !!id, staleTime: 60_000 })
export const useProducts = () => useQuery({ queryKey: ['products'], queryFn: catalog.products, staleTime: 300_000 })
export const useApplications = () => useQuery({ queryKey: ['applications'], queryFn: () => applications.list() })

/** «Подобрать финансирование»: creates one DRAFT for the company and opens the form. */
export function useStartApplication() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ companyId, productId }: { companyId: string; productId: string }) => applications.create(companyId, productId),
    onSuccess: (d) => {
      qc.setQueryData(['application', d.id], d)
      qc.invalidateQueries({ queryKey: ['applications'] })
      qc.invalidateQueries({ queryKey: ['company-documents'] })
      nav(`/applications/${d.id}`)
    },
    onError: (e) => toast.error(e, 'Не удалось создать заявку'),
  })
}
