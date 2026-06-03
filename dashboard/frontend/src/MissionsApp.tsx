import React, { useState, useEffect, useCallback } from 'react';
import { BACKEND_URL } from './config';
import { emitIssueSelected } from './ipc';
import { Issue } from './types';
import IssueCard from './components/IssueCard';
import DateNavigator from './components/DateNavigator';

const today = new Date().toISOString().slice(0, 10);

const modeTabStyle: React.CSSProperties = {
  border: 'none',
  padding: '6px 14px',
  fontSize: 13,
  cursor: 'pointer',
  transition: 'background 0.15s',
  fontFamily: 'inherit',
};

const actionBtnStyle: React.CSSProperties = {
  border: 'none',
  borderRadius: 6,
  padding: '6px 14px',
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: 'inherit',
};

export const MissionsApp: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState<string>(today);
  const [isPlanningMode, setIsPlanningMode] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [datesWithIssues, setDatesWithIssues] = useState<string[]>([]);
  const [predictedDates, setPredictedDates] = useState<string[]>([]);
  const [includePredicted, setIncludePredicted] = useState<boolean>(false);
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null);
  const [draftChanges, setDraftChanges] = useState<Map<number, { status: string; note?: string }>>(new Map());
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('OPEN');

  // Fetch issues for selected date + current filter
  const fetchIssues = useCallback(async (date: string, filter: string, withPredicted: boolean) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ date });
      if (withPredicted) {
        // No status filter — include PREDICTED alongside real issues
      } else if (filter !== 'ALL') {
        params.set('status', filter);
      }
      const res = await fetch(`${BACKEND_URL}/issues?${params}`);
      if (res.ok) {
        const data: Issue[] = await res.json();
        setIssues(data.sort((a, b) => b.severity - a.severity));
      }
    } catch (e) {
      console.error('Failed to fetch issues', e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch dates that have issues for navigator dots
  const fetchDates = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/issues/dates?days_ahead=30`);
      if (res.ok) {
        const data: { dates: string[]; predicted_dates?: string[] } = await res.json();
        setDatesWithIssues(data.dates ?? []);
        setPredictedDates(data.predicted_dates ?? []);
      }
    } catch (e) {
      console.error('Failed to fetch issue dates', e);
    }
  }, []);

  useEffect(() => {
    fetchDates();
  }, [fetchDates]);

  useEffect(() => {
    fetchIssues(selectedDate, statusFilter, includePredicted);
    setSelectedIssue(null);
  }, [selectedDate, statusFilter, includePredicted, fetchIssues]);

  const handleIssueSelect = (issue: Issue) => {
    setSelectedIssue(issue);
    emitIssueSelected({
      branch: issue.branch_code,
      category: issue.category,
      date: issue.issue_date,
    });
  };

  const handleDateChange = (date: string) => {
    setSelectedDate(date);
    if (isPlanningMode && draftChanges.size > 0) {
      setDraftChanges(new Map());
    }
  };

  const enterPlanningMode = () => {
    setIsPlanningMode(true);
    setDraftChanges(new Map());
  };

  const exitPlanningMode = (discard = true) => {
    if (discard) setDraftChanges(new Map());
    setIsPlanningMode(false);
  };

  const handleStatusChange = (issueId: number, status: string, note?: string) => {
    setDraftChanges(prev => {
      const next = new Map(prev);
      next.set(issueId, { status, note });
      return next;
    });
  };

  const handleConfirmChanges = async () => {
    if (draftChanges.size === 0) {
      exitPlanningMode(false);
      return;
    }
    setLoading(true);
    try {
      const patches = Array.from(draftChanges.entries()).map(([id, change]) =>
        fetch(`${BACKEND_URL}/issues/${id}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: change.status, resolution_note: change.note }),
        })
      );
      await Promise.all(patches);
      await fetchIssues(selectedDate, statusFilter, includePredicted);
      await fetchDates();
      exitPlanningMode(false);
    } catch (e) {
      console.error('Failed to save draft changes', e);
    } finally {
      setLoading(false);
    }
  };

  const handleAssetDrop = async (issueId: number, assetData: any) => {
    const response = await fetch(`${BACKEND_URL}/issues/${issueId}/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_type: assetData.type,
        asset_id: assetData.type === 'staff' ? assetData.id : null,
        branch_code: assetData.branch_code,
        category: assetData.category ?? null,
        quantity: assetData.quantity ?? null,
      }),
    });

    if (response.ok) {
      setIssues(prev => prev.map(i =>
        i.id === issueId ? { ...i, status: 'PENDING' } : i
      ));
      setDraftChanges(prev => new Map(prev).set(issueId, { status: 'PENDING' }));
    }
  };

  const handleRefresh = async () => {
    setLoading(true);
    try {
      await fetch(`${BACKEND_URL}/issues/refresh?date=${selectedDate}`, { method: 'POST' });
      await fetchIssues(selectedDate, statusFilter, includePredicted);
      await fetchDates();
    } catch (e) {
      console.error('Refresh failed', e);
    } finally {
      setLoading(false);
    }
  };

  const openCount = issues.filter(i => i.status === 'OPEN').length;

  return (
    <div
      style={{
        fontFamily: 'system-ui, sans-serif',
        direction: 'rtl',
        background: '#1a202c',
        color: '#e2e8f0',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        borderTop: isPlanningMode ? '3px solid #ed8936' : '3px solid transparent',
        transition: 'border-top-color 0.2s',
      }}
    >
      {/* Fixed top bar */}
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 16px',
          background: '#1a202c',
          borderBottom: '1px solid #2d3748',
          flexShrink: 0,
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <DateNavigator
          selectedDate={selectedDate}
          datesWithIssues={datesWithIssues}
          predictedDates={predictedDates}
          onDateChange={handleDateChange}
        />

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 0, borderRadius: 6, overflow: 'hidden', border: '1px solid #4a5568' }}>
          <button
            onClick={() => { if (isPlanningMode) exitPlanningMode(true); }}
            style={{
              ...modeTabStyle,
              background: !isPlanningMode ? '#3182ce' : 'transparent',
              color: !isPlanningMode ? '#fff' : '#a0aec0',
            }}
          >
            תמונת מצב
          </button>
          <button
            onClick={() => { if (!isPlanningMode) enterPlanningMode(); }}
            style={{
              ...modeTabStyle,
              background: isPlanningMode ? '#ed8936' : 'transparent',
              color: isPlanningMode ? '#fff' : '#a0aec0',
            }}
          >
            תכנון
          </button>
        </div>

        {/* Refresh */}
        <button
          onClick={handleRefresh}
          disabled={loading}
          style={{
            ...actionBtnStyle,
            background: '#2d3748',
            color: '#e2e8f0',
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? '...' : 'רענן'}
        </button>
      </header>

      {/* Sub-header: count + filter */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 16px',
          borderBottom: '1px solid #2d3748',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 14, color: '#a0aec0' }}>
          {openCount} בעיות פתוחות
          {isPlanningMode && draftChanges.size > 0 && (
            <span style={{ marginRight: 8, color: '#ed8936', fontSize: 12 }}>
              ({draftChanges.size} שינויים בטיוטה)
            </span>
          )}
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              fontSize: 13,
              color: '#a0aec0',
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              type="checkbox"
              checked={includePredicted}
              onChange={e => setIncludePredicted(e.target.checked)}
              style={{ cursor: 'pointer', accentColor: '#dd6b20' }}
            />
            כולל חזויות
          </label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            disabled={includePredicted}
            style={{
              background: '#2d3748',
              color: includePredicted ? '#718096' : '#e2e8f0',
              border: '1px solid #4a5568',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
              cursor: includePredicted ? 'not-allowed' : 'pointer',
            }}
          >
            <option value="OPEN">פתוח</option>
            <option value="PENDING">בטיפול</option>
            <option value="RESOLVED">נסגר</option>
            <option value="ALL">הכל</option>
          </select>
        </div>
      </div>

      {/* Scrollable cards area */}
      <main
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '12px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
        }}
      >
        {loading && issues.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#718096', marginTop: 40, fontSize: 14 }}>
            טוען...
          </div>
        ) : issues.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#718096', marginTop: 40, fontSize: 14 }}>
            אין בעיות לתאריך זה
          </div>
        ) : (
          issues.map(issue => (
            <IssueCard
              key={issue.id}
              issue={issue}
              isSelected={selectedIssue?.id === issue.id}
              isPlanningMode={isPlanningMode}
              onSelect={handleIssueSelect}
              onStatusChange={handleStatusChange}
              isDraft={draftChanges.has(issue.id)}
              onAssetDrop={isPlanningMode ? handleAssetDrop : undefined}
            />
          ))
        )}
      </main>

      {/* Planning mode confirm bar */}
      {isPlanningMode && (
        <footer
          style={{
            padding: '10px 16px',
            borderTop: '1px solid #2d3748',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 10,
            background: '#1a202c',
            flexShrink: 0,
          }}
        >
          <button
            onClick={() => exitPlanningMode(true)}
            style={{
              ...actionBtnStyle,
              background: 'transparent',
              border: '1px solid #4a5568',
              color: '#a0aec0',
            }}
          >
            ביטול
          </button>
          <button
            onClick={handleConfirmChanges}
            disabled={loading || draftChanges.size === 0}
            style={{
              ...actionBtnStyle,
              background: draftChanges.size > 0 ? '#ed8936' : '#4a5568',
              color: '#fff',
              opacity: loading ? 0.6 : 1,
            }}
          >
            אשר שינויים ({draftChanges.size})
          </button>
        </footer>
      )}
    </div>
  );
};

export default MissionsApp;
