export type StageKey = 'formularios' | 'documentos' | 'firma' | 'pago' | 'terminado'

export interface Stage {
  key: StageKey
  label: string
  icon: string
}

export const STAGES: Stage[] = [
  { key: 'formularios', label: 'Formularios', icon: 'bi-card-checklist' },
  { key: 'documentos', label: 'Documentos', icon: 'bi-cloud-arrow-up' },
  { key: 'firma', label: 'Firma', icon: 'bi-pen' },
  { key: 'pago', label: 'Pago', icon: 'bi-credit-card' },
  { key: 'terminado', label: 'Terminado', icon: 'bi-check-circle' },
]

export function stageIndex(stage: string): number {
  return STAGES.findIndex((s) => s.key === stage)
}
