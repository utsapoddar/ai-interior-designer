import { Component, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Canvas, useLoader } from '@react-three/fiber';
import { Edges, OrbitControls, Text } from '@react-three/drei';
import { Box3, BoxGeometry, DoubleSide, EdgesGeometry, Mesh, MeshStandardMaterial, MOUSE, TOUCH, Vector3, type Group } from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { USDZLoader } from 'three/examples/jsm/loaders/USDZLoader.js';
import { getPlan, getScanMesh, type ExclusionZone, type MeshResponse, type PlanResponse, type PlacementItem } from '../lib/api';
import { selectFurnitureAssetUrl, type FurnitureAsset } from './furniture_assets';

function BboxRoomFallback({ dimensions }: { dimensions: MeshResponse['dimensions_m'] }) {
  const edges = useMemo(() => new EdgesGeometry(new BoxGeometry(dimensions.width, dimensions.height, dimensions.depth)), [dimensions.width, dimensions.height, dimensions.depth]);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[dimensions.width / 2, 0, dimensions.depth / 2]}>
        <planeGeometry args={[dimensions.width, dimensions.depth]} />
        <meshStandardMaterial color="#e7dccd" transparent opacity={0.28} roughness={0.9} />
      </mesh>
      <lineSegments geometry={edges} position={[dimensions.width / 2, dimensions.height / 2, dimensions.depth / 2]}>
        <lineBasicMaterial color="#38485a" transparent opacity={0.65} />
      </lineSegments>
    </group>
  );
}

type UsdzResource = {
  read: () => Group;
};

const usdzResources = new Map<string, UsdzResource>();

async function loadScannedRoom(scanId: string): Promise<Group> {
  const response = await fetch(`/scans/${encodeURIComponent(scanId)}/usdz`);
  if (!response.ok) {
    throw new Error(`Failed to load USDZ scan ${scanId}: ${response.status} ${response.statusText}`);
  }

  const blob = await response.blob();
  const buffer = await blob.arrayBuffer();
  const group = new USDZLoader().parse(buffer);
  const material = new MeshStandardMaterial({
    color: '#d4cdc0',
    side: DoubleSide,
    transparent: true,
    opacity: 0.35,
    roughness: 0.85,
  });

  group.traverse((child) => {
    if (child instanceof Mesh) {
      child.material = material;
    }
  });

  const box = new Box3().setFromObject(group);
  if (box.isEmpty()) {
    throw new Error(`USDZ scan ${scanId} did not contain renderable geometry`);
  }
  group.position.set(-box.min.x, -box.min.y, -box.min.z);

  return group;
}

function getUsdzResource(scanId: string): UsdzResource {
  const cached = usdzResources.get(scanId);
  if (cached) return cached;

  let status: 'pending' | 'success' | 'error' = 'pending';
  let room: Group | null = null;
  let error: unknown = null;
  const promise = loadScannedRoom(scanId).then(
    (loadedRoom) => {
      status = 'success';
      room = loadedRoom;
    },
    (loadError) => {
      status = 'error';
      error = loadError;
    },
  );

  const resource: UsdzResource = {
    read() {
      if (status === 'pending') throw promise;
      if (status === 'error') throw error;
      return room as Group;
    },
  };
  usdzResources.set(scanId, resource);
  return resource;
}

function ScannedRoomPrimitive({ scanId }: { scanId: string }) {
  const loadedRoom = getUsdzResource(scanId).read();
  const room = useMemo(() => loadedRoom.clone(true), [loadedRoom]);
  return <primitive object={room} />;
}

class ScannedRoomErrorBoundary extends Component<
  { scanId: string; fallback: ReactNode; children: ReactNode },
  { failedScanId: string | null }
> {
  state = { failedScanId: null };

  static getDerivedStateFromError(_: unknown) {
    return { failedScanId: '__current__' };
  }

  componentDidCatch(error: unknown) {
    console.warn('Falling back to bbox wireframe because USDZ failed to load', error);
    this.setState({ failedScanId: this.props.scanId });
  }

  componentDidUpdate(previousProps: { scanId: string }) {
    if (previousProps.scanId !== this.props.scanId && this.state.failedScanId) {
      this.setState({ failedScanId: null });
    }
  }

  render() {
    if (this.state.failedScanId === this.props.scanId || this.state.failedScanId === '__current__') {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

function ScannedRoom({ scanId, dimensions }: { scanId: string; dimensions: MeshResponse['dimensions_m'] }) {
  const fallback = <BboxRoomFallback dimensions={dimensions} />;
  if (!scanId) return fallback;

  return (
    <ScannedRoomErrorBoundary scanId={scanId} fallback={fallback}>
      <Suspense fallback={fallback}>
        <ScannedRoomPrimitive scanId={scanId} />
      </Suspense>
    </ScannedRoomErrorBoundary>
  );
}

function BoxProxy({ item }: { item: PlacementItem }) {
  const rotationY = (item.rotation_degrees * Math.PI) / 180;
  const color = item.category === 'bed' ? '#b9855a' : item.category === 'storage' ? '#7e9a8b' : '#8d8fb8';

  return (
    <group position={[item.position.x, item.position.y + item.dimensions.height / 2, item.position.z]} rotation={[0, rotationY, 0]}>
      <mesh>
        <boxGeometry args={[item.dimensions.width, item.dimensions.height, item.dimensions.depth]} />
        <meshStandardMaterial color={color} roughness={0.75} />
        <Edges color="#2b2118" />
      </mesh>
      <Text position={[0, item.dimensions.height / 2 + 0.18, 0]} fontSize={0.18} color="#1b120b" anchorX="center" anchorY="middle">
        {item.catalog_id}
      </Text>
    </group>
  );
}

class FurnitureErrorBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(_: unknown) {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn('Falling back to box proxy because GLB furniture failed to load', error);
  }

  render() {
    if (this.state.failed) return this.props.fallback;
    return this.props.children;
  }
}

function detectBackYaw(scene: Group): number {
  const box = new Box3().setFromObject(scene);
  if (box.isEmpty()) return 0;
  const center = new Vector3();
  box.getCenter(center);
  const midY = (box.min.y + box.max.y) / 2;

  let sumX = 0;
  let sumZ = 0;
  let count = 0;
  scene.traverse((child) => {
    if (!(child instanceof Mesh) || !child.geometry?.attributes?.position) return;
    const pos = child.geometry.attributes.position;
    child.updateMatrixWorld(true);
    const v = new Vector3();
    for (let i = 0; i < pos.count; i += 1) {
      v.fromBufferAttribute(pos, i).applyMatrix4(child.matrixWorld);
      if (v.y > midY) {
        sumX += v.x - center.x;
        sumZ += v.z - center.z;
        count += 1;
      }
    }
  });
  if (count === 0) return 0;
  const backX = sumX / count;
  const backZ = sumZ / count;
  // Require meaningful asymmetry. Desks/tables/dressers have nearly-centered
  // upper-half centroids; rotating them by mesh noise breaks "long side to wall."
  const size = new Vector3();
  box.getSize(size);
  const asymmetry = Math.hypot(backX, backZ);
  const threshold = 0.12 * Math.max(size.x, size.z);
  if (asymmetry < threshold) return 0;
  const backAngle = Math.atan2(backX, backZ);
  // After we rotate the model by yaw=-(backAngle + Math.PI), back lands on -Z.
  let yaw = -(backAngle + Math.PI);
  while (yaw > Math.PI) yaw -= 2 * Math.PI;
  while (yaw < -Math.PI) yaw += 2 * Math.PI;
  // Snap to nearest 90° — furniture is axis-aligned; avoids jitter from noisy meshes.
  return Math.round(yaw / (Math.PI / 2)) * (Math.PI / 2);
}

const autoYawCache = new Map<string, number>();

function FurnitureModel({ item, asset }: { item: PlacementItem; asset: FurnitureAsset }) {
  const gltf = useLoader(GLTFLoader, asset.url) as GLTF;
  const dimensions = item.dimensions_m ?? item.dimensions;

  const autoYaw = useMemo(() => {
    const cached = autoYawCache.get(asset.url);
    if (cached !== undefined) return cached;
    const yaw = detectBackYaw(gltf.scene);
    autoYawCache.set(asset.url, yaw);
    return yaw;
  }, [asset.url, gltf.scene]);

  const rotationY = (item.rotation_degrees * Math.PI) / 180 + autoYaw;

  const { model, scale } = useMemo(() => {
    const model = gltf.scene.clone(true);
    model.updateMatrixWorld(true);

    const box = new Box3().setFromObject(model);
    if (box.isEmpty()) {
      return { model, scale: 1 };
    }

    const naturalSize = new Vector3();
    const naturalCenter = new Vector3();
    box.getSize(naturalSize);
    box.getCenter(naturalCenter);

    const wRatio = dimensions.width / Math.max(naturalSize.x, 0.001);
    const hRatio = dimensions.height / Math.max(naturalSize.y, 0.001);
    const dRatio = dimensions.depth / Math.max(naturalSize.z, 0.001);
    const uniform = Math.cbrt(wRatio * hRatio * dRatio);
    const scale: [number, number, number] = [uniform, uniform, uniform];
    model.position.set(-naturalCenter.x, -box.min.y, -naturalCenter.z);

    return { model, scale };
  }, [dimensions.depth, dimensions.height, dimensions.width, gltf.scene]);

  return (
    <group position={[item.position.x, item.position.y, item.position.z]} rotation={[0, rotationY, 0]} scale={scale}>
      <primitive object={model} />
    </group>
  );
}

const USE_GLB_FURNITURE = import.meta.env.VITE_USE_GLB_FURNITURE === 'true';

function Furniture({ item }: { item: PlacementItem }) {
  const [asset, setAsset] = useState<FurnitureAsset | null>(null);

  useEffect(() => {
    if (!USE_GLB_FURNITURE) return;
    let cancelled = false;
    setAsset(null);
    selectFurnitureAssetUrl(item).then((nextAsset) => {
      if (!cancelled) setAsset(nextAsset);
    }).catch(() => {
      if (!cancelled) setAsset(null);
    });
    return () => {
      cancelled = true;
    };
  }, [item]);

  if (!USE_GLB_FURNITURE || !asset) return <BoxProxy item={item} />;

  const fallback = <BoxProxy item={item} />;
  return (
    <FurnitureErrorBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <FurnitureModel item={item} asset={asset} />
      </Suspense>
    </FurnitureErrorBoundary>
  );
}

function ExclusionZoneMesh({ zone }: { zone: ExclusionZone }) {
  const width = zone.bounds.x_max - zone.bounds.x_min;
  const depth = zone.bounds.z_max - zone.bounds.z_min;
  const label = zone.kind === 'door' ? 'door swing' : 'window clearance';

  return (
    <group position={[zone.bounds.x_min + width / 2, 0.012, zone.bounds.z_min + depth / 2]}>
      <mesh>
        <boxGeometry args={[width, 0.01, depth]} />
        <meshStandardMaterial color="#e54545" transparent opacity={0.32} />
      </mesh>
      <Text position={[0, 0.035, 0]} rotation={[-Math.PI / 2, 0, 0]} fontSize={0.14} color="#8f1111" anchorX="center" anchorY="middle">
        {label}
      </Text>
    </group>
  );
}

export default function RoomPreviewScene({ planId }: { planId: string }) {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [mesh, setMesh] = useState<MeshResponse | null>(null);
  const [showHint, setShowHint] = useState(true);

  useEffect(() => {
    if (!planId) return;
    getPlan(planId)
      .then((nextPlan) => {
        setPlan(nextPlan);
        return getScanMesh(nextPlan.scan_id);
      })
      .then(setMesh)
      .catch(console.error);
  }, [planId]);

  const dimensions = mesh?.dimensions_m ?? { width: 4, height: 2.5, depth: 3 };

  return (
    <div className="scene-wrap" onWheelCapture={(e) => { if (!e.ctrlKey) e.stopPropagation(); }}>
      {showHint && (
        <div className="scene-hint">
          <span>Left-drag to pan · Right-drag to rotate · Pinch to zoom</span>
          <button type="button" onClick={() => setShowHint(false)} aria-label="Dismiss controls hint">×</button>
        </div>
      )}
      <Canvas camera={{ position: [dimensions.width + 1.5, dimensions.height + 1.5, dimensions.depth + 1.5], fov: 45 }}>
        <color attach="background" args={["#f4efe7"]} />
        <ambientLight intensity={0.85} />
        <directionalLight position={[3, 5, 4]} intensity={1.2} />
        <gridHelper args={[Math.max(dimensions.width, dimensions.depth) + 1, 10, '#9f9384', '#ddd4c8']} position={[dimensions.width / 2, 0.003, dimensions.depth / 2]} />
        <ScannedRoom scanId={plan?.scan_id ?? ''} dimensions={dimensions} />
        {plan?.exclusion_zones.map((zone) => <ExclusionZoneMesh key={`${zone.kind}-${zone.feature_id}-${zone.wall}`} zone={zone} />)}
        {plan?.items.map((item) => <Furniture key={item.catalog_id} item={item} />)}
        <OrbitControls
          makeDefault
          enableDamping
          target={[dimensions.width / 2, dimensions.height / 4, dimensions.depth / 2]}
          mouseButtons={{ LEFT: MOUSE.PAN, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.ROTATE }}
          touches={{ ONE: TOUCH.PAN, TWO: TOUCH.DOLLY_ROTATE }}
        />
      </Canvas>
    </div>
  );
}
