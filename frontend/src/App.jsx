import React from 'react';
import DashboardPage from './pages/DashboardPage.jsx';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title">
          <div className="app-logo">TB</div>
          <div>
            <h1>TRUSTBATTLE</h1>
            <div className="app-subtitle">
              AI-Driven Battlefield Information Integrity &amp; Trust Assessment
            </div>
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
          Schema v1.0 · Live from /ws/live
        </div>
      </header>
      <main className="app-main">
        <DashboardPage />
      </main>
    </div>
  );
}
