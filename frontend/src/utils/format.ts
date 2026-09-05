const copFormatter = new Intl.NumberFormat('es-CO', {
  style: 'currency',
  currency: 'COP',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})

export function formatCOP(n: number): string {
  if (!Number.isFinite(n)) return '$0'
  return copFormatter.format(n)
}

/**
 * Interes compuesto con tasa efectiva anual.
 * rate viene como porcentaje (12.5 = 12.5%).
 */
export function calcCdt(principal: number, ratePct: number, years: number): { interest: number; final: number } {
  const r = ratePct / 100
  const final = principal * Math.pow(1 + r, years)
  return { final, interest: final - principal }
}
