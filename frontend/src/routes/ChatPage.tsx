import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { generatePlanStreaming } from '../lib/api';

type PreviewFile = { file: File; url: string };

export default function ChatPage() {
  const [prompt, setPrompt] = useState('');
  const [references, setReferences] = useState<PreviewFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const scanId = searchParams.get('scan_id') ?? '';

  useEffect(() => () => references.forEach((preview) => URL.revokeObjectURL(preview.url)), [references]);

  async function generate() {
    setBusy(true);
    setError(null);
    setStage(null);
    try {
      const result = await generatePlanStreaming(
        scanId,
        prompt,
        references.map((preview) => preview.file),
        (_stage, label) => setStage(label),
      );
      navigate(`/preview?plan_id=${result.plan_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Plan generation failed');
      setBusy(false);
      setStage(null);
    }
  }

  function selectReferences(files: FileList | null) {
    references.forEach((preview) => URL.revokeObjectURL(preview.url));
    setReferences(Array.from(files ?? []).map((file) => ({ file, url: URL.createObjectURL(file) })));
  }

  return (
    <section className="panel">
      <p className="eyebrow">Step 2 · scan {scanId || 'missing'}</p>
      <h1>Describe the room you want</h1>
      <label className="field-label" htmlFor="design-prompt">Prompt</label>
      <textarea
        id="design-prompt"
        rows={6}
        value={prompt}
        placeholder="Warm wood, low bed, reading nook by the window, budget around $3k..."
        onChange={(event) => setPrompt(event.target.value)}
      />
      <label className="field-label" htmlFor="references">Reference images</label>
      <input
        id="references"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        onChange={(event) => selectReferences(event.target.files)}
      />
      {references.length > 0 && (
        <ul className="reference-preview-list">
          {references.map((preview) => (
            <li key={`${preview.file.name}-${preview.file.lastModified}`}>
              <img src={preview.url} alt="" />
              <span>{preview.file.name}</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={generate} disabled={busy || !scanId || !prompt.trim()} className={busy ? 'busy' : ''}>
        {busy ? <><span className="spinner" /> Generating…</> : 'Generate plan'}
      </button>
      {busy && stage && <p className="muted">{stage}<span className="loading-dots" /></p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
