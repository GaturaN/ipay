export function formatKES(amount) {
  return (
    'KES ' +
    Number(amount || 0).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  )
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-05-25" -> "25 May 2026". Parses the parts (not new Date) to avoid timezone shifts.
export function formatDate(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  if (!y || !m || !d) return String(value)
  return `${Number(d)} ${MONTHS[Number(m) - 1] || m} ${y}`
}
