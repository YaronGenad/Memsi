import React, { useState, useEffect } from 'react';
import { Issue } from '../types';

interface IssueCardProps {
  issue: Issue;
  isSelected: boolean;
  isPlanningMode: boolean;
  onSelect: (issue: Issue) => void;
  onStatusChange: (id: number, status: string, note?: string) => void;
  isDraft?: boolean;
  onAssetDrop?: (issueId: number, assetData: any) => void;
}

function getSeverityColor(severity: number): string {
  if (severity >= 8) return '#e53e3e';
  if (severity >= 5) return '#dd6b20';
  return '#d69e2e';
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, React.CSSProperties> = {
    OPEN: {
      backgroundColor: '#fed7d7',
      color: '#c53030',
      border: '1px solid #fc8181',
    },
    PENDING: {
      backgroundColor: '#feebc8',
      color: '#c05621',
      border: '1px solid #f6ad55',
    },
    RESOLVED: {
      backgroundColor: '#c6f6d5',
      color: '#276749',
      border: '1px solid #68d391',
    },
  };

  const labels: Record<string, string> = {
    OPEN: 'פתוחה',
    PENDING: 'בטיפול ★',
    RESOLVED: 'נפתרה',
  };

  const style: React.CSSProperties = {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '9999px',
    fontSize: '11px',
    fontWeight: 600,
    ...(styles[status] ?? styles['OPEN']),
  };

  return <span style={style}>{labels[status] ?? status}</span>;
}

function IssueTypeIcon({ issueType }: { issueType: string }) {
  if (issueType === 'STAFF_SHORTAGE') {
    return <span title="מחסור בכוח אדם" style={{ fontSize: '16px' }}>👤</span>;
  }
  return <span title="מחסור במלאי" style={{ fontSize: '16px' }}>📦</span>;
}

export default function IssueCard({
  issue,
  isSelected,
  isPlanningMode,
  onSelect,
  onStatusChange,
  isDraft = false,
  onAssetDrop,
}: IssueCardProps) {
  const [noteInput, setNoteInput] = useState('');
  const [showNoteInput, setShowNoteInput] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<string | null>(null);
  const [pulseHigh, setPulseHigh] = useState(true);

  useEffect(() => {
    if (!issue.predicted) return;
    const timer = setInterval(() => setPulseHigh(h => !h), 900);
    return () => clearInterval(timer);
  }, [issue.predicted]);

  const severityColor = getSeverityColor(issue.severity);

  const cardStyle: React.CSSProperties = {
    position: 'relative',
    direction: 'rtl',
    borderRadius: '8px',
    border: isSelected ? '2px solid #3182ce' : '1px solid #e2e8f0',
    borderLeft: `4px solid ${severityColor}`,
    borderStyle: issue.predicted ? 'dashed' : undefined,
    backgroundColor: isDraft ? '#fffff0' : '#ffffff',
    padding: '12px',
    marginBottom: '8px',
    cursor: 'pointer',
    boxShadow: isSelected
      ? '0 0 0 2px #3182ce'
      : '0 1px 3px rgba(0,0,0,0.08)',
    transition: 'box-shadow 0.15s',
  };

  const selectedBorder = issue.predicted
    ? (isSelected ? '2px dashed #3182ce' : '1px dashed #a0aec0')
    : (isSelected ? '2px solid #3182ce' : '1px solid #e2e8f0');

  // Override border shorthand for predicted dashed style
  const wrapperStyle: React.CSSProperties = issue.predicted
    ? {
        ...cardStyle,
        border: isSelected ? '2px dashed #3182ce' : '1px dashed #a0aec0',
        borderLeft: `4px dashed ${severityColor}`,
      }
    : cardStyle;

  function handleStatusClick(status: string) {
    setPendingStatus(status);
    setShowNoteInput(true);
  }

  function handleConfirmStatus() {
    if (pendingStatus) {
      onStatusChange(issue.id, pendingStatus, noteInput || undefined);
    }
    setShowNoteInput(false);
    setNoteInput('');
    setPendingStatus(null);
  }

  function handleCancelStatus() {
    setShowNoteInput(false);
    setNoteInput('');
    setPendingStatus(null);
  }

  return (
    <div
      style={wrapperStyle}
      onClick={() => onSelect(issue)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(issue)}
      onDragOver={isPlanningMode ? (e) => { e.preventDefault(); e.currentTarget.style.outline = '2px dashed #68d391'; } : undefined}
      onDragLeave={isPlanningMode ? (e) => { e.currentTarget.style.outline = selectedBorder; } : undefined}
      onDrop={isPlanningMode ? (e) => {
        e.preventDefault();
        e.currentTarget.style.outline = selectedBorder;
        try {
          const data = JSON.parse(e.dataTransfer.getData('application/json'));
          onAssetDrop?.(issue.id, data);
        } catch {}
      } : undefined}
    >
      {/* Top row */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '6px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <IssueTypeIcon issueType={issue.issue_type} />
          <span
            style={{
              fontWeight: 700,
              fontSize: '14px',
              color: '#2d3748',
            }}
          >
            {issue.branch_code}
          </span>
          {issue.predicted && (
            <span
              style={{
                fontSize: '10px',
                backgroundColor: '#ebf8ff',
                color: '#2b6cb0',
                border: '1px solid #bee3f8',
                borderRadius: '4px',
                padding: '1px 5px',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  backgroundColor: '#3182ce',
                  opacity: pulseHigh ? 1 : 0.3,
                  transition: 'opacity 0.9s ease-in-out',
                }}
              />
              חזוי
            </span>
          )}
        </div>
        <StatusBadge status={issue.status} />
      </div>

      {/* Category */}
      <div
        style={{
          fontSize: '12px',
          color: '#718096',
          marginBottom: '4px',
        }}
      >
        {issue.category}
      </div>

      {/* Gap info */}
      {issue.gap !== null && issue.min_quantity !== null && (
        <div
          style={{
            fontSize: '13px',
            color: severityColor,
            fontWeight: 600,
            marginBottom: '4px',
          }}
        >
          חסר: {Math.abs(issue.gap)} מתוך {issue.min_quantity}
          {issue.current_quantity !== null && (
            <span style={{ fontWeight: 400, color: '#718096', marginRight: '4px' }}>
              (קיים: {issue.current_quantity})
            </span>
          )}
        </div>
      )}

      {/* Severity */}
      <div
        style={{
          fontSize: '11px',
          color: '#a0aec0',
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
        }}
      >
        <span
          style={{
            display: 'inline-block',
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: severityColor,
          }}
        />
        חומרה: {issue.severity}/10
        {issue.confidence !== null && (
          <span style={{ marginRight: '8px' }}>
            | ביטחון: {Math.round(issue.confidence * 100)}%
          </span>
        )}
      </div>

      {/* Planning mode action bar */}
      {isPlanningMode && (
        <div
          style={{
            marginTop: '10px',
            borderTop: '1px solid #e2e8f0',
            paddingTop: '8px',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {!showNoteInput ? (
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {issue.status !== 'PENDING' && (
                <button
                  onClick={() => handleStatusClick('PENDING')}
                  style={{
                    padding: '3px 10px',
                    fontSize: '12px',
                    borderRadius: '4px',
                    border: '1px solid #f6ad55',
                    backgroundColor: '#fffaf0',
                    color: '#c05621',
                    cursor: 'pointer',
                  }}
                >
                  העבר לטיפול
                </button>
              )}
              {issue.status !== 'RESOLVED' && (
                <button
                  onClick={() => handleStatusClick('RESOLVED')}
                  style={{
                    padding: '3px 10px',
                    fontSize: '12px',
                    borderRadius: '4px',
                    border: '1px solid #68d391',
                    backgroundColor: '#f0fff4',
                    color: '#276749',
                    cursor: 'pointer',
                  }}
                >
                  סמן כנפתרה
                </button>
              )}
              {issue.status !== 'OPEN' && (
                <button
                  onClick={() => handleStatusClick('OPEN')}
                  style={{
                    padding: '3px 10px',
                    fontSize: '12px',
                    borderRadius: '4px',
                    border: '1px solid #fc8181',
                    backgroundColor: '#fff5f5',
                    color: '#c53030',
                    cursor: 'pointer',
                  }}
                >
                  החזר לפתוח
                </button>
              )}
            </div>
          ) : (
            <div>
              <input
                type="text"
                placeholder="הערה (אופציונלי)"
                value={noteInput}
                onChange={(e) => setNoteInput(e.target.value)}
                style={{
                  width: '100%',
                  padding: '4px 8px',
                  fontSize: '12px',
                  borderRadius: '4px',
                  border: '1px solid #cbd5e0',
                  marginBottom: '6px',
                  direction: 'rtl',
                  boxSizing: 'border-box',
                }}
                autoFocus
              />
              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  onClick={handleConfirmStatus}
                  style={{
                    padding: '3px 10px',
                    fontSize: '12px',
                    borderRadius: '4px',
                    border: '1px solid #68d391',
                    backgroundColor: '#f0fff4',
                    color: '#276749',
                    cursor: 'pointer',
                  }}
                >
                  אשר
                </button>
                <button
                  onClick={handleCancelStatus}
                  style={{
                    padding: '3px 10px',
                    fontSize: '12px',
                    borderRadius: '4px',
                    border: '1px solid #e2e8f0',
                    backgroundColor: '#f7fafc',
                    color: '#718096',
                    cursor: 'pointer',
                  }}
                >
                  ביטול
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
