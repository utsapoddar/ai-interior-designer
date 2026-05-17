import type { PlacementItem } from '../lib/api';

export type FurnitureAsset = { url: string; yaw_offset?: number };

export const FURNITURE_GLB_URLS: Record<string, FurnitureAsset[]> = {
  bed: [
    { url: 'https://static.poly.pizza/6ce318cf-aa67-4934-8cdb-7102991f0a8e.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Bed by Poly by Google
    { url: 'https://static.poly.pizza/703a8a77-2b59-456d-8c59-090007985963.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Bed by Alex Safayan
    { url: 'https://static.poly.pizza/2f8905c8-f820-4017-92fd-79a70263bebd.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; my bed by 64 Bit
  ],
  storage: [
    { url: 'https://static.poly.pizza/46e86b56-1c8e-4928-840a-b1ee8a78aceb.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Bedside Table by Bouggles
    { url: 'https://static.poly.pizza/1c26c1fe-7fb1-4511-b5f0-3dd73ea10c86.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Night Stand by Quaternius
    { url: 'https://static.poly.pizza/deb08e3b-cd54-4252-b5b2-53f86f1c1d04.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Night Stand by Quaternius
    { url: 'https://static.poly.pizza/2d613d77-d894-4056-8dca-4058d7ba68d3.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Cabinet Bed Drawer Tabl by Kenney
  ],
  seating: [
    { url: 'https://static.poly.pizza/64699642-a4c2-4850-9c4b-558a328ed1bf.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Desk Chair by Kenney
    { url: 'https://static.poly.pizza/3b62877f-a791-43d9-8a3a-0e5cbc74a0c0.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Chair Rounded by Kenney
    { url: 'https://static.poly.pizza/92a2404e-10d5-4c6a-a188-18b556474f8f.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Couch Medium by Quaternius
    { url: 'https://static.poly.pizza/21d3c956-0747-422c-b06d-6d4392380384.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Lounge Chair by Kenney
  ],
  surface: [
    { url: 'https://static.poly.pizza/0716218b-3aae-48e6-8ddd-185cf7f7b7d7.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Desk by Kenney
    { url: 'https://static.poly.pizza/8b566260-04e0-4f3a-89fa-25a2733851b7.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Desk Corner by Kenney
  ],
  lighting: [
    { url: 'https://static.poly.pizza/cb47f4ca-735f-4259-88e7-97ebb1936669.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Floor Lamp by Zsky
    { url: 'https://static.poly.pizza/7eb047ad-0a58-4cec-92f1-bbdb7156adfc.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Lamp Square Table by Kenney
  ],
  textile: [
    { url: 'https://static.poly.pizza/ea51ba53-9d02-4ca6-9785-91d568ecc23e.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Rug by Nick Slough
    { url: 'https://static.poly.pizza/93588780-3405-40b7-acb4-9a87c88569f6.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Rug by Quaternius
    { url: 'https://static.poly.pizza/65a09bc5-89c5-4953-a60f-5acaaf02fbb7.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Rug Doormat by Kenney
  ],
  decor: [
    { url: 'https://static.poly.pizza/d5cb92d9-e351-489e-8eb1-03e22801e6ec.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Picture frame by Gabriel Valdivia
    { url: 'https://static.poly.pizza/2bbb2aed-c3e1-4262-a252-5cbffa59ccde.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Houseplant by Quaternius
    { url: 'https://static.poly.pizza/6e6e6b19-011d-4b1d-9cc0-07269adec9fa.glb', yaw_offset: 0 }, // TODO yaw_offset: verify in browser; Houseplant by Quaternius
  ],
};

export async function selectFurnitureAssetUrl(item: PlacementItem): Promise<FurnitureAsset | null> {
  const assets = candidatesFor(item);
  if (assets.length === 0) return null;

  const key = item.id ?? item.catalog_id;
  const hash = await hashString(key);
  return assets[hash % assets.length];
}

function candidatesFor(item: PlacementItem): FurnitureAsset[] {
  const all = FURNITURE_GLB_URLS[item.category] ?? [];
  const dims = item.dimensions_m ?? item.dimensions;
  const maxFootprint = Math.max(dims.width, dims.depth);

  if (item.category === 'seating') {
    // index 2 is the Couch (large); others are chairs
    return maxFootprint >= 1.4
      ? [all[2]].filter(Boolean)
      : [all[0], all[1], all[3]].filter(Boolean);
  }
  if (item.category === 'storage') {
    // index 3 is Cabinet (large dresser); 0-2 are nightstands
    return maxFootprint >= 0.9
      ? [all[3]].filter(Boolean)
      : [all[0], all[1], all[2]].filter(Boolean);
  }
  if (item.category === 'lighting') {
    // index 0 is Floor Lamp, index 1 is Table Lamp
    return dims.height >= 1.0
      ? [all[0]].filter(Boolean)
      : [all[1]].filter(Boolean);
  }
  return all;
}

async function hashString(value: string): Promise<number> {
  if (globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return new DataView(digest).getUint32(0, false);
  }

  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}
