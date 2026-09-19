const copFormatter = new Intl.NumberFormat('es-CO', {
  style: 'currency',
  currency: 'COP',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function formatCOP(n: number): string {
  if (!Number.isFinite(n)) return '$0';
  return copFormatter.format(n);
}

/** CSS class helper para tier badges (mapea AA+ -> tier-AAplus). */
export function tierCss(tier: string): string {
  return 'tier-' + tier.replace('+', 'plus');
}
