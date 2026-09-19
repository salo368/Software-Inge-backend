// Types que reflejan assets/docs/parex.json y assets/docs/contexto.json.

export type FlowType = 'basico' | 'alternativo' | 'error' | 'extensivo';

export interface Actor {
  id: string;
  name: string;
  detail: string;
}

export interface ScenarioStep {
  n: number;
  useCase: string;
  flow: string;
  note?: string;
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  steps: ScenarioStep[];
}

export interface Service {
  id: string;
  name: string;
  consumers: string[];
  revenue: string | null;
  summary: string;
  stages?: string[];
  scenarios: Scenario[];
}

export interface UseCaseStep {
  id: string;
  text: string;
}

export interface Flow {
  id: string;
  type: FlowType;
  name: string | null;
  composition: string;
  closure: string;
}

export interface UseCase {
  id: string;
  name: string;
  steps: UseCaseStep[];
  flows: Flow[];
}

export interface ParexDoc {
  meta: {
    version: string;
    updatedAt: string;
    methodology: string;
    author: string;
    notes: string;
  };
  actors: Actor[];
  services: Service[];
  useCases: UseCase[];
}

export interface CanvasBlock {
  block: string;
  content: string;
}

export interface ActorRole {
  actor: string;
  role: string;
  consumesServices: boolean;
  isPayer: boolean;
  note: string;
}

export interface Capability {
  domain: string;
  supports: string[];
  items: string[];
}

export interface Product {
  name: string;
  description: string;
  services: string[];
}

export interface ContextoDoc {
  meta: { version: string; updatedAt: string; source: string };
  identity: {
    type: string;
    sector: string;
    product: string;
    businessModel: string;
    roleVsEntity: string;
    revenueSource: string;
    channels: string[];
    scope: string;
    definition: string;
  };
  canvas: CanvasBlock[];
  actorRoles: ActorRole[];
  capabilities: Capability[];
  products: Product[];
}
