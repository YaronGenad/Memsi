import React from 'react';
import { useHealthCheck } from './useHealthCheck';
import { HealthIndicator } from './components/HealthIndicator';

export const InventoryApp: React.FC = () => {
  const health = useHealthCheck();

  return (
    <div
      style={{
        fontFamily: 'system-ui, sans-serif',
        direction: 'rtl',
        padding: 24,
        height: '100vh',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
      }}
    >
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #e5e7eb',
          paddingBottom: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22 }}>מלאי</h1>
        <HealthIndicator status={health} />
      </header>

      <main
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#9ca3af',
          fontSize: 16,
        }}
      >
        נתוני מלאי יוצגו כאן
      </main>
    </div>
  );
};
