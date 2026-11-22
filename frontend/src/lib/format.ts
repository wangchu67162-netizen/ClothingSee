const currency = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return currency.format(value).replace('CN¥', '¥')
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function shortText(value: string, length = 80): string {
  if (!value) return ''
  return value.length > length ? `${value.slice(0, length)}…` : value
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function cnNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}
