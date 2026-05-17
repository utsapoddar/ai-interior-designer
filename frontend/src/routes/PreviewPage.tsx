import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getCatalog, getPlan, getPlanImages, type CatalogItem, type PlanImage, type PlanResponse } from '../lib/api';
import RoomPreviewScene from '../three/RoomPreviewScene';

export default function PreviewPage() {
  const [searchParams] = useSearchParams();
  const planId = searchParams.get('plan_id') ?? '';
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);

  useEffect(() => {
    if (!planId) return;
    getPlan(planId).then(setPlan).catch(console.error);
    getCatalog().then(setCatalog).catch(console.error);
  }, [planId]);

  const catalogById = useMemo(() => new Map(catalog.map((item) => [item.catalog_id, item])), [catalog]);
  const totalBudget = useMemo(
    () => plan?.items.reduce((sum, item) => sum + (item.approx_price_usd ?? catalogById.get(item.catalog_id)?.approx_price_usd ?? 0), 0) ?? 0,
    [catalogById, plan],
  );
  const placedItemIds = useMemo(
    () => new Set(plan?.items.flatMap((item) => [item.catalog_id, item.id].filter(Boolean) as string[]) ?? []),
    [plan],
  );
  const substitutionsByDropId = useMemo(() => {
    const substitutions = new Map<string, string>();
    for (const entry of plan?.repair_log ?? []) {
      if (entry.action === 'substituted' && entry.replaces) {
        substitutions.set(entry.replaces, entry.id);
      }
    }
    return substitutions;
  }, [plan]);
  const couldntFit = useMemo(
    () => (plan?.repair_log ?? []).filter((entry) => (
      entry.action === 'dropped'
      && !placedItemIds.has(entry.id)
      && !substitutionsByDropId.has(entry.id)
    )),
    [placedItemIds, plan, substitutionsByDropId],
  );

  return (
    <section className="panel preview-panel">
      <p className="eyebrow">Step 3 · plan {planId || 'missing'}</p>
      <h1>3D layout preview</h1>
      <div className="preview-layout">
        <RoomCarousel planId={planId} />
        <aside className="preview-sidebar">
          <h2>Rationale</h2>
          <p className="muted">{plan?.rationale ?? <span>Loading plan<span className="loading-dots" /></span>}</p>
          <h2>Items</h2>
          <ul>
            {plan?.items.map((item) => {
              const catalogItem = catalogById.get(item.catalog_id);
              const price = item.approx_price_usd ?? catalogItem?.approx_price_usd ?? 0;
              const productUrl = item.product_url ?? null;
              const fallbackUrl = productUrl ? null : (item.fallback_url ?? null);
              const url = productUrl ?? fallbackUrl;
              const label = item.name ?? catalogItem?.name ?? item.catalog_id;
              const linkHost = productUrl ? (() => { try { return new URL(productUrl).hostname.replace(/^www\./, ''); } catch { return productUrl; } })() : null;
              return (
                <li key={item.catalog_id} className="item-row">
                  <div>
                    <strong>{label}</strong>
                    {item.verified && <small>✓ verified</small>}
                    <span>{item.category}</span>
                    <small>{item.dimensions.width} × {item.dimensions.depth} × {item.dimensions.height} m</small>
                    {url && <a className="product-link" href={url} target="_blank" rel="noopener noreferrer">{fallbackUrl ? 'Search ↗' : `${linkHost} ↗`}</a>}
                  </div>
                  <span>{price ? `$${price}` : '—'}</span>
                </li>
              );
            })}
          </ul>
          {couldntFit.length > 0 && (
            <>
              <h2 className="couldnt-fit-heading">Couldn't fit</h2>
              <ul className="couldnt-fit-list">
                {couldntFit.map((entry, index) => (
                  <li key={`${entry.id}-${index}`} className="couldnt-fit-row">
                    <div>
                      <strong>{entry.name ?? entry.id}</strong>
                      <span>{entry.category ?? 'unknown'}</span>
                      <small>{entry.reason}</small>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="budget-row">
            <strong>Total budget</strong>
            <strong>${totalBudget}</strong>
          </div>
        </aside>
      </div>
    </section>
  );
}

function RoomCarousel({ planId }: { planId: string }) {
  const [images, setImages] = useState<PlanImage[]>([]);
  const [slideIndex, setSlideIndex] = useState(0);
  const [isGenerating, setIsGenerating] = useState(true);
  const slideCount = 1 + images.length;

  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    let interval: number | undefined;
    const startedAt = Date.now();

    const poll = async () => {
      const nextImages = await getPlanImages(planId).catch(() => []);
      if (cancelled) return;
      setImages(nextImages);
      const timedOut = Date.now() - startedAt >= 60_000;
      setIsGenerating(nextImages.length < 3 && !timedOut);
      if ((nextImages.length >= 3 || timedOut) && interval !== undefined) {
        window.clearInterval(interval);
      }
    };

    poll();
    interval = window.setInterval(poll, 3000);

    return () => {
      cancelled = true;
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [planId]);

  useEffect(() => {
    setSlideIndex((current) => Math.min(current, slideCount - 1));
  }, [slideCount]);

  return (
    <div className="carousel-wrap">
      <div className="carousel-counter">
        {slideIndex + 1} / 4{isGenerating ? ' (generating images…)' : ''}
      </div>
      <div className="carousel-track" style={{ transform: `translateX(-${slideIndex * 100}%)` }}>
        <div className="carousel-slide">
          <RoomPreviewScene planId={planId} />
        </div>
        {images.map((image) => (
          <div className="carousel-slide" key={image.index}>
            <img src={image.url} alt="" />
          </div>
        ))}
      </div>
      <button className="carousel-arrow carousel-arrow-left" onClick={() => setSlideIndex((index) => index - 1)} disabled={slideIndex === 0} aria-label="Previous slide">‹</button>
      <button className="carousel-arrow carousel-arrow-right" onClick={() => setSlideIndex((index) => index + 1)} disabled={slideIndex >= slideCount - 1} aria-label="Next slide">›</button>
      <div className="carousel-dots">
        {Array.from({ length: slideCount }).map((_, index) => (
          <button key={index} className={index === slideIndex ? 'active' : ''} onClick={() => setSlideIndex(index)} aria-label={`Go to slide ${index + 1}`} />
        ))}
      </div>
    </div>
  );
}
