import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { CataloguePrice, Price, Provider, Usage } from '../api/types'
import { isCli } from '../models/ModelsPage'
import { modelName } from '../shell/modelName'
import { day } from './cost'
import { Fold } from './Fold'

interface Props {
  providers: Provider[]
  /** The usage rows now on the page: a model that ran can have a price though no provider names it. */
  rows: Usage['by_model']
  prices: Price[]
  /** models.dev's price of the models in use: used where the user wrote none, and written over here. */
  catalogue?: CataloguePrice[]
  /** Each throws ApiError with the server's reason. */
  onPrice: (price: Price) => Promise<void>
  onRemovePrice: (modelId: string) => Promise<void>
}

/** A price as typed: a number that is not negative, or null. */
const amount = (text: string) => (/^\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : null)

function PriceRow({ model, price, catalogue, onPrice, onRemovePrice }: { model: string; price: Price | undefined; catalogue?: CataloguePrice } & Pick<Props, 'onPrice' | 'onRemovePrice'>) {
  // The user's price, else the catalogue's to start from: saved, it is the user's and wins.
  const shown = price ?? catalogue
  const [input, setInput] = useState(shown ? String(shown.input) : '')
  const [output, setOutput] = useState(shown ? String(shown.output) : '')
  const [currency, setCurrency] = useState(shown?.currency ?? '')
  const [cacheRead, setCacheRead] = useState(shown?.cache_read != null ? String(shown.cache_read) : '')
  const [cacheWrite, setCacheWrite] = useState(shown?.cache_write != null ? String(shown.cache_write) : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sent = amount(input)
  const written = amount(output)
  // Each may be left empty; one that holds something must be a price.
  const read = amount(cacheRead)
  const wrote = amount(cacheWrite)
  const ready = sent !== null && written !== null && Boolean(currency.trim()) && (!cacheRead.trim() || read !== null) && (!cacheWrite.trim() || wrote !== null)

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready || sent === null || written === null) return
    // An empty box is left out: those tokens then have no price.
    void run(() =>
      onPrice({
        model_id: model,
        input: sent,
        output: written,
        currency: currency.trim(),
        ...(read !== null && { cache_read: read }),
        ...(wrote !== null && { cache_write: wrote }),
      }),
    )
  }

  return (
    <>
      <form className="price-row" onSubmit={submit}>
        <span className="mono" title={model}>
          {modelName(model)}
        </span>
        <input className="input mono" inputMode="decimal" aria-label={`Input price of ${model}`} value={input} placeholder="sent" onChange={e => setInput(e.target.value)} />
        <input className="input mono" inputMode="decimal" aria-label={`Output price of ${model}`} value={output} placeholder="written" onChange={e => setOutput(e.target.value)} />
        <input className="input mono" aria-label={`Currency of ${model}`} value={currency} maxLength={8} placeholder="USD" onChange={e => setCurrency(e.target.value)} />
        <button type="submit" className="btn btn-small" aria-label={`Save the price of ${model}`} disabled={busy || !ready}>
          Save price
        </button>
        {price ? (
          <button
            type="button"
            className="btn btn-small"
            aria-label={catalogue ? `Use models.dev’s price for ${model}` : `Remove the price of ${model}`}
            disabled={busy}
            onClick={() => void run(() => onRemovePrice(model))}
          >
            {catalogue ? 'Use models.dev’s' : 'Remove'}
          </button>
        ) : (
          <span />
        )}
        <div className="price-cache">
          <label>
            A million read from the cache
            <input className="input mono" inputMode="decimal" aria-label={`A million read from the cache, for ${model}`} value={cacheRead} placeholder="optional" onChange={e => setCacheRead(e.target.value)} />
          </label>
          <label>
            A million written to it
            <input className="input mono" inputMode="decimal" aria-label={`A million written to it, for ${model}`} value={cacheWrite} placeholder="optional" onChange={e => setCacheWrite(e.target.value)} />
          </label>
        </div>
        {catalogue && (
          <span className="muted price-cache">
            {price
              ? `Your price is used. models.dev’s${catalogue.read_on ? ` (${day(catalogue.read_on)})` : ''}: ${catalogue.input} / ${catalogue.output} ${catalogue.currency}.`
              : `models.dev’s price${catalogue.read_on ? ` (${day(catalogue.read_on)})` : ''}, used until you save your own.`}
          </span>
        )}
      </form>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}

/**
 * What the user says a model costs. Where the user says nothing the tables above use models.dev's
 * price (the catalogue's), and say so.
 */
export function Prices({ providers, rows, prices, catalogue = [], onPrice, onRemovePrice }: Props) {
  const apis = providers.filter(p => !isCli(p.kind))
  const priced = new Set(prices.map(p => p.model_id))
  // Every model once: those with a price, those that ran (a provider that is no longer known
  // is not taken for a CLI) and those an API provider names. Priced first, then by name.
  const models = [
    ...new Set(
      [
        ...priced,
        ...rows.filter(row => !providers.some(p => p.name === row.provider_name && isCli(p.kind))).map(row => row.model_id),
        ...apis.flatMap(p => [p.default_model, ...(p.models ?? []).map(m => m.name)]),
        ...catalogue.map(c => c.model_id),
      ].filter((name): name is string => Boolean(name)),
    ),
  ].sort((a, b) => Number(priced.has(b)) - Number(priced.has(a)) || a.localeCompare(b))
  return (
    // (Its id: the Cost box's "set prices" opens it.)
    <Fold title="Prices" id="usage-prices" count={`${models.length === 1 ? '1 model' : `${models.length} models`} · ${priced.size} priced`}>
      {models.length === 0 ? (
        <p className="muted">No model has a price, ran in this period or is named by an API provider.</p>
      ) : (
        <div className="price-rows">
          {models.map(model => {
            const price = prices.find(p => p.model_id === model)
            const known = catalogue.find(c => c.model_id === model)
            return (
              // What is saved is what the row starts from: a saved price is a new row.
              <PriceRow key={`${model}:${price?.input}:${price?.output}:${price?.currency}:${price?.cache_read}:${price?.cache_write}`} model={model} price={price} catalogue={known} onPrice={onPrice} onRemovePrice={onRemovePrice} />
            )
          })}
        </div>
      )}
      <p className="muted memory-hint">
        For a million tokens sent and a million written, in a currency you name; and, where the provider keeps a
        cache, for a million read from it and a million written to it. Leave those empty and such tokens are left out
        of the cost, which then says “≥”. A price belongs to the model’s name, whichever provider runs it.
        Where you write none, models.dev’s price for the model on its provider is used, in USD, and the cost says so -
        in the monthly budget too. A model it has a price for is listed with it: save your own to use yours instead, or
        go back to models.dev’s. A CLI on a plan has no price for a token and is not listed.
      </p>
    </Fold>
  )
}
