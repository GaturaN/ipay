export function formatKES(amount) {
  return (
    'KES ' +
    Number(amount || 0).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  )
}
