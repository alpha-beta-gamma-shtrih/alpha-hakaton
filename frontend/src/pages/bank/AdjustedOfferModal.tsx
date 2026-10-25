import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { bank } from '../../api/endpoints'
import type { BankCard, OfferPreview } from '../../api/types'
import { Button, Checkbox, ErrorNotice, Modal, Notice, Reasons, RiskMeter } from '../../components/ui'
import { OfferComparison } from '../../components/OfferComparison'
import { money } from '../../lib/format'

export function AdjustedOfferModal({ c, onClose, onDone, onFail }: { c: BankCard; onClose: () => void; onDone: (c: BankCard, message: string) => void; onFail: (error: unknown) => void }) {
  const [amount, setAmount] = useState(String(Number(c.requested_amount)))
  const [term, setTerm] = useState(String(c.term_months))
  const [preview, setPreview] = useState<OfferPreview | null>(null)
  const [pub, setPub] = useState('')
  const [internal, setInternal] = useState('')
  const [sure, setSure] = useState(false)
  const product = c.revision.product_snapshot
  const min = Number(product.min_amount)
  const max = Math.min(Number(product.max_amount), Number(c.requested_amount))
  const minTerm = Number(product.min_term_months)
  const maxTerm = Number(product.max_term_months)
  const valid = /^\d+(?:\.\d{1,2})?$/.test(amount) && Number(amount) >= min && Number(amount) <= max && Number.isInteger(Number(term)) && Number(term) >= minTerm && Number(term) <= maxTerm
    && (Number(amount) !== Number(c.requested_amount) || Number(term) !== c.term_months)
  const quote = useMutation({
    mutationFn: () => bank.previewOffer(c.id, { expected_version: c.version, amount: Number(amount).toFixed(2), term_months: Number(term) }),
    onSuccess: (value) => { setPreview(value); setSure(false) },
    onError: onFail,
  })
  const approve = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error('Сначала рассчитайте предложение')
      return bank.decide(c.id, {
        expected_version: c.version, outcome: 'APPROVED', public_explanation: pub.trim(), internal_comment: internal.trim() || null,
        offer: { amount: preview.terms.amount, term_months: preview.terms.term_months, preview_hash: preview.preview_hash },
      })
    },
    onSuccess: (card) => onDone(card, 'Одобрено на изменённых условиях'),
    onError: onFail,
  })
  const busy = quote.isPending || approve.isPending
  const change = () => { setPreview(null); setSure(false); quote.reset(); approve.reset() }
  return <Modal open width={780} labelledBy="bank-offer-title" onClose={() => !busy && onClose()}>
    <span className="tag">Предложение банка</span>
    <h2 id="bank-offer-title" className="card-title" style={{ marginTop: 14 }}>Одобрить с изменением условий</h2>
    <p className="hint">Исходная заявка сохраняется. Сумму можно уменьшить; срок — изменить в границах отправленной версии продукта. Ставка рассчитывается автоматически.</p>
    <div className="bank-offer-fields" style={{ marginTop: 16 }}>
      <div className="field"><label htmlFor="offer-amount">Предлагаемая сумма, ₽</label>
        <input id="offer-amount" className="input" type="text" inputMode="decimal" value={amount} disabled={busy} onChange={e => { change(); setAmount(e.target.value.replace(',', '.')) }} />
        <span className="hint">От {money(min)} до {money(max)}</span></div>
      <div className="field"><label htmlFor="offer-term">Предлагаемый срок, месяцев</label>
        <input id="offer-term" className="input" type="number" min={minTerm} max={maxTerm} step="1" value={term} disabled={busy} onChange={e => { change(); setTerm(e.target.value) }} />
        <span className="hint">От {minTerm} до {maxTerm} месяцев</span></div>
    </div>
    <Button variant="blue" disabled={!valid || busy} loading={quote.isPending} onClick={() => quote.mutate()}>Рассчитать условия</Button>
    <ErrorNotice error={quote.error} />
    {preview && <>
      <OfferComparison terms={preview.terms} />
      <p className="label">Оценка предложения банка</p>
      <RiskMeter score={preview.risk_score} band={preview.risk_band} />
      <Reasons items={preview.reasons} />
      {!preview.can_approve && <Notice tone="error">Новые условия не проходят обязательные ограничения. Одобрение недоступно; измените параметры.</Notice>}
    </>}
    <div className="field" style={{ marginTop: 16 }}><label htmlFor="offer-public">Обоснование новых условий для клиента</label>
      <textarea id="offer-public" className="textarea" value={pub} maxLength={1000} disabled={busy} onChange={e => setPub(e.target.value)} />
      <span className="hint">От 20 до 1000 символов; клиент увидит этот текст</span></div>
    <div className="field"><label htmlFor="offer-internal">Внутренний комментарий · необязательно</label>
      <textarea id="offer-internal" className="textarea" value={internal} maxLength={2000} disabled={busy} onChange={e => setInternal(e.target.value)} /></div>
    <Checkbox title="Подтверждаю новые условия и окончательное решение" desc="Клиент увидит предложение и сможет принять его демо-подписью." checked={sure} disabled={!preview?.can_approve || busy} onChange={setSure} />
    <ErrorNotice error={approve.error} />
    <div className="modal-actions">
      <Button variant="ghost" disabled={busy} onClick={onClose}>Отмена</Button>
      <Button variant="lime" loading={approve.isPending} disabled={busy || !preview?.can_approve || !sure || pub.trim().length < 20} onClick={() => approve.mutate()}>Одобрить на этих условиях</Button>
    </div>
  </Modal>
}
