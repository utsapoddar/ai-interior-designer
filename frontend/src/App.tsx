import { Link, Route, Routes } from 'react-router-dom';
import UploadPage from './routes/UploadPage';
import ChatPage from './routes/ChatPage';
import PreviewPage from './routes/PreviewPage';

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">LiDAR Room Designer</Link>
        <nav>
          <Link to="/">Upload</Link>
          <Link to="/chat?scan_id=stub">Chat</Link>
          <Link to="/preview?plan_id=stub">Preview</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/preview" element={<PreviewPage />} />
        </Routes>
      </main>
    </div>
  );
}
