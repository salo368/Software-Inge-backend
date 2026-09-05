export interface Bank {
  id: string
  name: string
  rate: number    // tasa efectiva anual como porcentaje (12.5 = 12.5%)
  color: string   // color de acento para el avatar
}

/**
 * Tasas referenciales de ejemplo. Datos quemados por ahora — en el futuro
 * vendran de un servicio real.
 */
export const BANKS: Bank[] = [
  { id: 'pichincha',       name: 'Banco Pichincha',      rate: 13.55, color: '#FDB913' },
  { id: 'serfinanza',      name: 'Serfinanza',           rate: 13.30, color: '#00A651' },
  { id: 'coltefinanciera', name: 'Coltefinanciera',      rate: 13.10, color: '#D71E28' },
  { id: 'falabella',       name: 'Banco Falabella',      rate: 12.90, color: '#008B3D' },
  { id: 'davivienda',      name: 'Davivienda',           rate: 12.80, color: '#EE1C25' },
  { id: 'scotiabank',      name: 'Scotiabank Colpatria', rate: 12.60, color: '#B22234' },
  { id: 'bancolombia',     name: 'Bancolombia',          rate: 12.50, color: '#FFDA00' },
  { id: 'occidente',       name: 'Banco de Occidente',   rate: 12.35, color: '#F58220' },
  { id: 'bogota',          name: 'Banco de Bogotá',      rate: 12.20, color: '#00539B' },
  { id: 'bbva',            name: 'BBVA',                 rate: 11.95, color: '#004481' },
  { id: 'popular',         name: 'Banco Popular',        rate: 11.75, color: '#009A44' },
  { id: 'av_villas',       name: 'AV Villas',            rate: 11.60, color: '#E30613' },
]
