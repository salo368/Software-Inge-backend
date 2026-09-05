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
  color: string          // color de acento del avatar
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
    color: '#FFDA00',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Mayor red de oficinas', 'App reconocida', 'Retiros sin costo'],
    rates: { '90': 9.50, '180': 10.20, '360': 11.50, '540': 11.70, '720': 11.80 },
  },
  {
    id: 'davivienda',
    name: 'Davivienda',
    color: '#EE1C25',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Servicio digital sólido', 'Beneficios DaviPlata', 'Renovación automática'],
    rates: { '90': 9.00, '180': 10.00, '360': 11.80, '540': 12.50, '720': 13.00 },
  },
  {
    id: 'bbva',
    name: 'BBVA',
    color: '#004481',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Respaldo internacional', 'Banca móvil líder', 'Sin comisiones ocultas'],
    rates: { '90': 9.80, '180': 10.50, '360': 11.70, '540': 11.90, '720': 12.00 },
  },
  {
    id: 'bogota',
    name: 'Banco de Bogotá',
    color: '#00539B',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Tradición y solidez', 'Grupo Aval', 'Amplia cobertura'],
    rates: { '90': 10.00, '180': 10.50, '360': 11.60, '540': 11.80, '720': 12.00 },
  },
  {
    id: 'scotiabank',
    name: 'Scotiabank Colpatria',
    color: '#B22234',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Presencia global', 'Buena rentabilidad a plazos largos'],
    rates: { '90': 9.50, '180': 10.40, '360': 11.90, '540': 12.10, '720': 12.30 },
  },
  {
    id: 'popular',
    name: 'Banco Popular',
    color: '#009A44',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Enfocado en pensionados', 'Perfil conservador'],
    rates: { '90': 10.20, '180': 10.80, '360': 11.50, '540': 11.60, '720': 11.70 },
  },
  {
    id: 'occidente',
    name: 'Banco de Occidente',
    color: '#F58220',
    tier: 'AAA',
    ratingBy: 'Fitch Ratings',
    minAmount: 500_000,
    highlights: ['Grupo Aval', 'Fuerte en empresas'],
    rates: { '90': 10.10, '180': 10.60, '360': 11.70, '540': 12.00, '720': 12.20 },
  },
  {
    id: 'av_villas',
    name: 'AV Villas',
    color: '#E30613',
    tier: 'AAA',
    ratingBy: 'BRC Ratings',
    minAmount: 500_000,
    highlights: ['Grupo Aval', 'Buena relación con clientes'],
    rates: { '90': 10.30, '180': 10.90, '360': 11.80, '540': 12.00, '720': 12.10 },
  },
  {
    id: 'falabella',
    name: 'Banco Falabella',
    color: '#008B3D',
    tier: 'AA+',
    ratingBy: 'Fitch Ratings',
    minAmount: 1_000_000,
    highlights: ['Beneficios CMR', 'Tasas altas a corto plazo', '100% digital'],
    rates: { '90': 11.50, '180': 12.00, '360': 12.50, '540': 12.40, '720': 12.30 },
  },
  {
    id: 'pichincha',
    name: 'Banco Pichincha',
    color: '#FDB913',
    tier: 'AA+',
    ratingBy: 'BRC Ratings',
    minAmount: 1_000_000,
    highlights: ['Fuerte en plazos cortos', 'Respaldo Grupo Pichincha'],
    rates: { '90': 12.00, '180': 12.30, '360': 12.50, '540': 12.40, '720': 12.20 },
  },
  {
    id: 'serfinanza',
    name: 'Serfinanza',
    color: '#00A651',
    tier: 'AA+',
    ratingBy: 'BRC Ratings',
    minAmount: 1_000_000,
    highlights: ['Financiera del grupo Olímpica', 'Excelente a plazos largos'],
    rates: { '90': 10.50, '180': 11.50, '360': 12.80, '540': 13.20, '720': 13.50 },
  },
  {
    id: 'coltefinanciera',
    name: 'Coltefinanciera',
    color: '#D71E28',
    tier: 'AA',
    ratingBy: 'BRC Ratings',
    minAmount: 2_000_000,
    highlights: ['Especializada en captación', 'Las tasas más altas del mercado'],
    rates: { '90': 11.00, '180': 12.00, '360': 13.00, '540': 13.40, '720': 13.60 },
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
