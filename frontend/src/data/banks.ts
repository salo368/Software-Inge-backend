export type TermKey = '90' | '180' | '360' | '540' | '720'

export interface Term {
  key: TermKey
  label: string
  days: number
}

export const TERMS: Term[] = [
  { key: '90',  label: '90 días',  days: 90 },
  { key: '180', label: '180 días', days: 180 },
  { key: '360', label: '360 días', days: 360 },
  { key: '540', label: '540 días', days: 540 },
  { key: '720', label: '720 días', days: 720 },
]

export type Tier = 'AAA' | 'AA+' | 'AA' | 'A+' | 'A'

export interface Bank {
  id: string
  name: string
  logo: string           // ruta en /public
  tier: Tier
  ratingBy: string       // agencia calificadora
  minAmount: number      // monto minimo para abrir CDT (COP)
  highlights: string[]   // 2-3 cualidades destacables
  rates: Record<TermKey, number>  // tasa E.A. como porcentaje por plazo
}

/**
 * Datos referenciales quemados. Las curvas de tasas y calificaciones son
 * ejemplos; en produccion vendran de un servicio real. Distintos plazos
 * favorecen distintas entidades a proposito.
 */
export const BANKS: Bank[] = [
  {
    id: 'bancolombia',
    name: 'Bancolombia',
    logo: '/banks/bancolombia.png',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['La red más grande del país', 'App líder en Colombia', 'Atención 24/7'],
    rates: { '90': 9.50, '180': 10.20, '360': 11.50, '540': 11.70, '720': 11.80 },
  },
  {
    id: 'davivienda',
    name: 'Davivienda',
    logo: '/banks/davivienda.png',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Fuerte en plazos largos', 'Ecosistema DaviPlata', 'Renovación automática'],
    rates: { '90': 9.00, '180': 10.00, '360': 11.80, '540': 12.50, '720': 13.00 },
  },
  {
    id: 'bbva',
    name: 'BBVA',
    logo: '/banks/bbva.png',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Respaldo internacional', 'Banca móvil premiada', 'Tasas estables'],
    rates: { '90': 9.80, '180': 10.50, '360': 11.70, '540': 11.90, '720': 12.00 },
  },
  {
    id: 'bogota',
    name: 'Banco de Bogotá',
    logo: '/banks/bogota.png',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Tradición desde 1870', 'Grupo Aval', 'Cobertura nacional'],
    rates: { '90': 10.00, '180': 10.50, '360': 11.60, '540': 11.80, '720': 12.00 },
  },
  {
    id: 'itau',
    name: 'Itaú',
    logo: '/banks/itau.png',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['El banco más grande de Latam', 'Equilibrio tasa-solidez'],
    rates: { '90': 10.40, '180': 11.00, '360': 11.90, '540': 12.10, '720': 12.20 },
  },
  {
    id: 'scotiabank',
    name: 'Scotiabank Colpatria',
    logo: '/banks/scotiabank.png',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Presencia en 25 países', 'Mejora en plazos largos'],
    rates: { '90': 9.50, '180': 10.40, '360': 11.90, '540': 12.10, '720': 12.30 },
  },
  {
    id: 'serfinanza',
    name: 'Serfinanza',
    logo: '/banks/serfinanza.png',
    tier: 'AA+',
    ratingBy: 'BRC Ratings',
    minAmount: 1_000_000,
    highlights: ['Aliada del Grupo Olímpica', 'Top en plazos largos'],
    rates: { '90': 10.50, '180': 11.50, '360': 12.80, '540': 13.20, '720': 13.50 },
  },
  {
    id: 'pichincha',
    name: 'Banco Pichincha',
    logo: '/banks/pichincha.png',
    tier: 'AA+',
    ratingBy: 'BRC Ratings',
    minAmount: 1_000_000,
    highlights: ['Campeón del corto plazo', 'Apertura 100% en línea'],
    rates: { '90': 12.00, '180': 12.30, '360': 12.50, '540': 12.40, '720': 12.20 },
  },
  {
    id: 'finandina',
    name: 'Banco Finandina',
    logo: '/banks/finandina.png',
    tier: 'AA+',
    ratingBy: 'BRC Ratings',
    minAmount: 200_000,
    highlights: ['Banco 100% digital', 'Sin filas ni papeleo', 'CDT desde la app'],
    rates: { '90': 11.20, '180': 11.80, '360': 12.60, '540': 12.70, '720': 12.60 },
  },
  {
    id: 'pibank',
    name: 'Pibank',
    logo: '/banks/pibank.png',
    tier: 'AA+',
    ratingBy: 'Fitch Ratings',
    minAmount: 200_000,
    highlights: ['Tasas agresivas', 'Cero comisiones', 'Respaldado por Banco Pichincha'],
    rates: { '90': 11.80, '180': 12.20, '360': 12.90, '540': 12.60, '720': 12.40 },
  },
  {
    id: 'coltefinanciera',
    name: 'Coltefinanciera',
    logo: '/banks/coltefinanciera.png',
    tier: 'AA',
    ratingBy: 'BRC Ratings',
    minAmount: 2_000_000,
    highlights: ['Las tasas más altas del mercado', 'Especialista en CDTs'],
    rates: { '90': 11.00, '180': 12.00, '360': 13.00, '540': 13.40, '720': 13.60 },
  },
  {
    id: 'nu',
    name: 'Nu Colombia',
    logo: '/banks/nu.png',
    tier: 'AA',
    ratingBy: 'Fitch Ratings',
    minAmount: 100_000,
    highlights: ['El neobanco más grande del mundo', 'Experiencia 100% digital', 'Sin letra pequeña'],
    rates: { '90': 12.20, '180': 12.40, '360': 12.70, '540': 12.30, '720': 12.00 },
  },
]

/**
 * Color asociado a cada tier para el badge.
 */
export const TIER_COLORS: Record<Tier, { bg: string; fg: string; label: string }> = {
  'AAA': { bg: '#dcfce7', fg: '#166534', label: 'Máxima solidez' },
  'AA+': { bg: '#ccfbf1', fg: '#115e59', label: 'Muy alta solidez' },
  'AA':  { bg: '#e0f2fe', fg: '#075985', label: 'Alta solidez' },
  'A+':  { bg: '#fef9c3', fg: '#854d0e', label: 'Solidez adecuada' },
  'A':   { bg: '#fed7aa', fg: '#9a3412', label: 'Solidez aceptable' },
}
