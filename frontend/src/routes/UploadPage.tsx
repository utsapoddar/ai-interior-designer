import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadScan } from '../lib/api';

export default function UploadPage() {
  const [scanFile, setScanFile] = useState<File | null>(null);
  const navigate = useNavigate();

  async function continueToChat() {
    const result = await uploadScan(scanFile);
    navigate(`/chat?scan_id=${result.scan_id}`);
  }

  return (
    <section className="panel narrow-panel">
      <p className="eyebrow">Step 1</p>
      <h1>Upload a RoomPlan scan</h1>
      <p className="muted">Choose a USDZ export from the iPhone capture app.</p>
      <label className="field-label" htmlFor="scan-file">USDZ scan</label>
      <input
        id="scan-file"
        type="file"
        accept=".usdz,model/vnd.usdz+zip"
        onChange={(event) => setScanFile(event.target.files?.[0] ?? null)}
      />
      <button type="button" onClick={continueToChat} disabled={!scanFile}>Continue</button>
    </section>
  );
}
