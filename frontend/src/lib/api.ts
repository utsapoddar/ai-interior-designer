const apiBase = import.meta.env.VITE_API_BASE ?? '';

export type ScanUploadResponse = {
  scan_id: string;
  dimensions_m: Record<string, number>;
  has_labeled_primitives: boolean;
};

export type PlacementItem = {
  catalog_id: string;
  id?: string;
  name?: string;
  category: string;
  position: { x: number; y: number; z: number };
  rotation_degrees: 0 | 90 | 180 | 270 | number;
  dimensions: { width: number; depth: number; height: number };
  dimensions_m?: { width: number; depth: number; height: number };
  rationale: string;
  product_url?: string | null;
  approx_price_usd?: number;
  verified?: boolean;
  fallback_url?: string | null;
};

export type RepairLogEntry = {
  id: string;
  action: 'kept' | 'snapped' | 'shifted_zone' | 'shifted_collision' | 'dropped' | string;
  reason: string;
  name?: string;
  category?: string;
  replaces?: string;
  wall_preference?: string;
};

export type ExclusionZone = {
  kind: 'door' | 'window' | string;
  feature_id: string;
  wall: string;
  bounds: { x_min: number; x_max: number; z_min: number; z_max: number };
};

export type PlanResponse = {
  plan_id: string;
  scan_id: string;
  items: PlacementItem[];
  rationale: string;
  status: string;
  exclusion_zones: ExclusionZone[];
  repair_log?: RepairLogEntry[];
};

type ProgressHandler = (stage: string, label: string, extra?: Record<string, unknown>) => void;

export type MeshResponse = {
  dimensions_m: { width: number; depth: number; height: number };
  up_axis: string;
};

export type CatalogItem = {
  catalog_id: string;
  name: string;
  category: string;
  dimensions_m: { width: number; depth: number; height: number };
  style_tags: string[];
  approx_price_usd?: number;
  product_url?: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function uploadScan(file: File | null): Promise<ScanUploadResponse> {
  const formData = new FormData();
  if (file) {
    formData.append('file', file);
  }

  return request('/scans', { method: 'POST', body: formData });
}

export function generatePlan(scanId: string, prompt: string, references: File[] = []): Promise<PlanResponse> {
  const formData = new FormData();
  formData.append('scan_id', scanId);
  formData.append('prompt', prompt);
  references.forEach((file) => formData.append('references', file));

  return request('/plans', { method: 'POST', body: formData });
}

export async function generatePlanStreaming(
  scanId: string,
  prompt: string,
  references: File[],
  onProgress: ProgressHandler,
): Promise<{ plan_id: string }> {
  const formData = new FormData();
  formData.append('scan_id', scanId);
  formData.append('prompt', prompt);
  references.forEach((file) => formData.append('references', file));

  const response = await fetch(`${apiBase}/plans/stream`, { method: 'POST', body: formData });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  if (!response.body) throw new Error('No response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) throw new Error('Stream closed before done event');
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';
    for (const raw of events) {
      if (!raw.trim()) continue;
      const lines = raw.split('\n');
      const eventLine = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() ?? 'message';
      const dataLine = lines.find((line) => line.startsWith('data:'))?.slice(5).trim() ?? '{}';
      const data = JSON.parse(dataLine);
      if (eventLine === 'progress') {
        onProgress(data.stage, data.label, data);
      } else if (eventLine === 'done') {
        return { plan_id: data.plan_id };
      } else if (eventLine === 'error') {
        throw new Error(data.message ?? 'Plan generation failed');
      }
    }
  }
}

export function getPlan(planId: string): Promise<PlanResponse> {
  return request(`/plans/${planId}`);
}

export function getScanMesh(scanId: string): Promise<MeshResponse> {
  return request(`/scans/${scanId}/mesh`);
}

export async function getCatalog(): Promise<CatalogItem[]> {
  const response = await request<{ items: CatalogItem[] }>('/catalog');
  return response.items;
}


export type PlanImage = {
  index: number;
  url: string;
  prompt: string;
};

export async function getPlanImages(planId: string): Promise<PlanImage[]> {
  const response = await fetch(`${apiBase}/plans/${planId}/images`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.images ?? [];
}
