import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { applications } from '../../api/endpoints'
import type { Draft } from '../../api/types'
import { PixelArt } from '../../components/pixel'
import { Arrow, ErrorNotice, PageLoader } from '../../components/ui'
import { PROCESSING_STATUSES } from '../../lib/labels'
import { StatusView } from './StatusView'
import { Wizard } from './wizard/Wizard'

export function ApplicationPage() {
  const { id = '' } = useParams()
  const [sp, setSp] = useSearchParams()
  const qc = useQueryClient()
  const [justSubmitted, setJustSubmitted] = useState(false)
  const q = useQuery({
    queryKey: ['application', id],
    queryFn: () => applications.get(id),
    refetchInterval: (query) => (query.state.data && PROCESSING_STATUSES.includes(query.state.data.status) ? 3000 : false),
  })

  if (q.isLoading) return <PageLoader />
  if (q.error) {
    const notFound = q.error instanceof ApiError && q.error.status === 404
    return (
      <div className="page">
        <div className="card empty" style={{ marginTop: 40 }}>
          <PixelArt shape="question" size={10} color="var(--line-2)" />
          <h2 className="card-title">{notFound ? 'Заявка не найдена' : 'Не удалось загрузить заявку'}</h2>
          {!notFound && <ErrorNotice error={q.error} onRetry={() => q.refetch()} />}
          <Link to="/overview" className="btn">
            На главную <Arrow />
          </Link>
        </div>
      </div>
    )
  }
  const d = q.data!
  const edit = d.status === 'DRAFT' || (d.status === 'NEEDS_INFO' && sp.get('edit') === '1')
  const forceStatus = sp.get('view') === 'status' && d.latest_revision_no

  if (edit && !forceStatus) {
    return (
      <Wizard
        key={d.id}
        draft={d}
        onSubmitted={(nd: Draft) => {
          qc.setQueryData(['application', id], nd)
          qc.invalidateQueries({ queryKey: ['applications'] })
          qc.invalidateQueries({ queryKey: ['events', id] })
          setJustSubmitted(true)
          setSp({}, { replace: true })
          window.scrollTo({ top: 0, behavior: 'smooth' })
        }}
      />
    )
  }
  return <StatusView app={d} justSubmitted={justSubmitted} onEdit={() => setSp({ edit: '1' })} />
}
