import React, { useState, useEffect, useCallback } from 'react';
import { BACKEND_URL } from './config';
import { listenIssueSelected, listenDateChanged } from './ipc';
import { InventoryItem } from './types';

interface IssueSelectedPayload {
  branch: string;
  category: string;
  date: string;
}


const SECTION_CONFIG = [
  { status: 'AVAILABLE' as const, label: 'זמין', borderColor: '#38a169', bgHeader: '#f0fff4' },
  { status: 'ASSIGNED' as const, label: 'מוקצה', borderColor: '#dd6b20', bgHeader: '#fffaf0' },
  { status: 'UNAVAILABLE' as const, label: 'לא זמין', borderColor: '#e53e3e', bgHeader: '#fff5f5' },
];

export const InventoryApp: React.FC = () => {
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [filterContext, setFilterContext] = useState<{ branch?: string; category?: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchInventory = useCallback(async (category?: string, excludeBranch?: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (category) params.set('category', category);
      if (excludeBranch) params.set('exclude_branch', excludeBranch);
      const res = await fetch(`${BACKEND_URL}/inventory/available?${params}`);
      if (!res.ok) return;
      const data: InventoryItem[] = await res.json();
      setInventory(data);
    } catch {
      // backend not yet available — keep previous state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInventory(filterContext?.category, filterContext?.branch);
  }, [filterContext, fetchInventory]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listenIssueSelected((payload) => {
      const p = payload as IssueSelectedPayload;
      setFilterContext({ branch: p.branch, category: p.category });
    }).then((fn) => {
      unlisten = fn;
    });
    return () => { unlisten?.(); };
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listenDateChanged((_) => {
      
      fetchInventory(filterContext?.category, filterContext?.branch);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => { unlisten?.(); };
  }, [filterContext, fetchInventory]);

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>, item: InventoryItem) => {
    e.dataTransfer.setData(
      'application/json',
      JSON.stringify({
        type: 'inventory',
        branch_code: item.branch_code,
        category: item.category,
        quantity: item.available_quantity,
      })
    );
    e.dataTransfer.effectAllowed = 'copy';
  };

  const clearFilter = () => setFilterContext(null);

  // Items with no surplus go to UNAVAILABLE section (items not returned by endpoint)
  // The endpoint only returns surplus rows, so "unavailable" = no row for that combo.
  // We display what we have: AVAILABLE and ASSIGNED come from the API.
  // For the 3-column UI, map status directly:
  const getItemsForSection = (sectionStatus: 'AVAILABLE' | 'ASSIGNED' | 'UNAVAILABLE') => {
    if (sectionStatus === 'UNAVAILABLE') return []; // endpoint doesn't return these
    return inventory.filter((item) => item.status === sectionStatus);
  };

  return (
    <div
      style={{
        fontFamily: 'system-ui, sans-serif',
        direction: 'rtl',
        background: '#1a202c',
        minHeight: '100vh',
        color: '#e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        padding: 0,
      }}
    >
      {/* Header */}
      <header
        style={{
          background: '#2d3748',
          padding: '12px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          borderBottom: '1px solid #4a5568',
          flexWrap: 'wrap',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#f7fafc' }}>מלאי</h1>

        {filterContext?.category && (
          <span
            style={{
              background: '#2b6cb0',
              borderRadius: 12,
              padding: '2px 10px',
              fontSize: 13,
              color: '#bee3f8',
            }}
          >
            קטגוריה: {filterContext.category}
          </span>
        )}

        {filterContext?.branch && (
          <span
            style={{
              background: '#553c9a',
              borderRadius: 12,
              padding: '2px 10px',
              fontSize: 13,
              color: '#e9d8fd',
            }}
          >
            ללא סניף: {filterContext.branch}
          </span>
        )}

        {filterContext && (
          <button
            onClick={clearFilter}
            style={{
              background: '#4a5568',
              border: '1px solid #718096',
              borderRadius: 6,
              padding: '4px 12px',
              color: '#e2e8f0',
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            נקה סינון
          </button>
        )}

        <div style={{ flex: 1 }} />

        {loading && (
          <span style={{ fontSize: 13, color: '#a0aec0' }}>טוען...</span>
        )}

        <button
          onClick={() => fetchInventory(filterContext?.category, filterContext?.branch)}
          style={{
            background: '#3182ce',
            border: 'none',
            borderRadius: 6,
            padding: '6px 14px',
            color: '#fff',
            fontSize: 14,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          רענן
        </button>
      </header>

      {/* Kanban columns */}
      <div
        style={{
          display: 'flex',
          flex: 1,
          gap: 16,
          padding: 16,
          overflowX: 'auto',
        }}
      >
        {SECTION_CONFIG.map(({ status, label, borderColor, bgHeader }) => {
          const items = getItemsForSection(status);
          return (
            <div
              key={status}
              style={{
                flex: 1,
                minWidth: 220,
                background: '#2d3748',
                borderRadius: 8,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                borderTop: `3px solid ${borderColor}`,
              }}
            >
              {/* Column header */}
              <div
                style={{
                  background: bgHeader,
                  color: '#1a202c',
                  padding: '8px 14px',
                  fontWeight: 700,
                  fontSize: 15,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span>{label}</span>
                <span
                  style={{
                    background: borderColor,
                    color: '#fff',
                    borderRadius: 10,
                    padding: '1px 8px',
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                >
                  {items.length}
                </span>
              </div>

              {/* Inventory cards */}
              <div
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                {items.length === 0 && (
                  <div style={{ color: '#718096', fontSize: 13, textAlign: 'center', paddingTop: 20 }}>
                    {status === 'UNAVAILABLE' ? 'לא זמין' : 'אין פריטים'}
                  </div>
                )}
                {items.map((item, idx) => {
                  const surplus = item.current_quantity - item.min_quantity;
                  const isMarlug = item.location_type === 'marlug';
                  return (
                    <div
                      key={`${item.branch_code}-${item.category}-${idx}`}
                      draggable
                      onDragStart={(e) => handleDragStart(e, item)}
                      style={{
                        background: '#f7fafc',
                        color: '#1a202c',
                        borderRadius: 6,
                        padding: '10px 12px',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.15)',
                        cursor: 'grab',
                        borderRight: `3px solid ${borderColor}`,
                        userSelect: 'none',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                          marginBottom: 4,
                        }}
                      >
                        <div style={{ fontWeight: 600, fontSize: 14 }}>
                          {isMarlug ? 'מרלוג' : `סניף ${item.branch_code}`}
                        </div>
                        <span
                          style={{
                            background: isMarlug ? '#ebf8ff' : '#fff5f5',
                            color: isMarlug ? '#2b6cb0' : '#c53030',
                            borderRadius: 10,
                            padding: '1px 8px',
                            fontSize: 11,
                            fontWeight: 600,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {isMarlug ? '🏭 מרלוג' : '🏪 סניף'}
                        </span>
                      </div>
                      <div style={{ fontSize: 12, color: '#4a5568', marginBottom: 6 }}>
                        {item.category}
                      </div>
                      <div style={{ fontSize: 12, color: '#2d3748', fontWeight: 500 }}>
                        יש: {item.current_quantity} | מינ׳: {item.min_quantity} | עודף: {surplus}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
