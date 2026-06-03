import React, { useState, useEffect, useCallback } from 'react';
import { BACKEND_URL } from './config';
import { listenIssueSelected, listenDateChanged } from './ipc';

interface StaffAvailability {
  id: number;
  name: string;
  branch_code: string;
  roles: string[];
  shift_type: string | null;
  status: string; // AVAILABLE | ASSIGNED | UNAVAILABLE
  exception_type: string | null;
}

interface IssueSelectedPayload {
  branch: string;
  category: string;
  date: string;
}

interface DateChangedPayload {
  date: string;
}

interface ExceptionForm {
  employee_id: number | '';
  from_date: string;
  to_date: string;
  exception_type: string;
  notes: string;
}

const today = new Date().toISOString().split('T')[0];

const SECTION_CONFIG = [
  { status: 'AVAILABLE', label: 'זמין', borderColor: '#38a169', bgHeader: '#f0fff4' },
  { status: 'ASSIGNED', label: 'מוקצה', borderColor: '#dd6b20', bgHeader: '#fffaf0' },
  { status: 'UNAVAILABLE', label: 'לא זמין', borderColor: '#e53e3e', bgHeader: '#fff5f5' },
];

const EXCEPTION_LABELS: Record<string, string> = {
  SICK: 'מחלה',
  VACATION: 'חופשה',
  TRAINING: 'הדרכה',
  OTHER: 'אחר',
};

export const StaffApp: React.FC = () => {
  const [staff, setStaff] = useState<StaffAvailability[]>([]);
  const [filterContext, setFilterContext] = useState<{ branch?: string; category?: string } | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(today);
  const [branchFilter, setBranchFilter] = useState<string>('');
  const [showExceptionForm, setShowExceptionForm] = useState(false);
  const [exceptionForm, setExceptionForm] = useState<ExceptionForm>({
    employee_id: '',
    from_date: today,
    to_date: today,
    exception_type: 'SICK',
    notes: '',
  });
  const [exceptionError, setExceptionError] = useState<string | null>(null);
  const [exceptionSuccess, setExceptionSuccess] = useState(false);

  const fetchStaff = useCallback(
    async (date: string, branch: string) => {
      try {
        const params = new URLSearchParams({ date, branch_code: branch });
        const res = await fetch(`${BACKEND_URL}/staff/availability?${params}`);
        if (!res.ok) return;
        const data: StaffAvailability[] = await res.json();
        setStaff(data);
      } catch {
        // backend not yet available — keep previous state
      }
    },
    []
  );

  useEffect(() => {
    fetchStaff(selectedDate, branchFilter);
  }, [selectedDate, branchFilter, fetchStaff]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listenIssueSelected((payload) => {
      const p = payload as IssueSelectedPayload;
      setFilterContext({ branch: p.branch, category: p.category });
      setBranchFilter(p.branch ?? '');
      setSelectedDate(p.date ?? today);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listenDateChanged((payload) => {
      const p = payload as DateChangedPayload;
      if (p.date) setSelectedDate(p.date);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      unlisten?.();
    };
  }, []);

  const filteredStaff = filterContext?.category
    ? staff.filter((e) =>
        e.roles.some((r) =>
          r.toLowerCase().includes((filterContext.category ?? '').toLowerCase())
        )
      )
    : staff;

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>, employee: StaffAvailability) => {
    e.dataTransfer.setData('application/json', JSON.stringify(employee));
    e.dataTransfer.effectAllowed = 'copy';
  };

  const handleSubmitException = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setExceptionError(null);
    setExceptionSuccess(false);
    try {
      const res = await fetch(`${BACKEND_URL}/staff/exceptions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(exceptionForm),
      });
      if (!res.ok) {
        const err = await res.json();
        setExceptionError(err.detail ?? 'שגיאה');
        return;
      }
      setExceptionSuccess(true);
      setShowExceptionForm(false);
      fetchStaff(selectedDate, branchFilter);
    } catch {
      setExceptionError('שגיאת רשת');
    }
  };

  const uniqueBranches = Array.from(new Set(staff.map((e) => e.branch_code).filter(Boolean)));

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
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#f7fafc' }}>כוח אדם</h1>

        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          style={{
            background: '#4a5568',
            border: '1px solid #718096',
            borderRadius: 6,
            padding: '4px 8px',
            color: '#e2e8f0',
            fontSize: 14,
          }}
        />

        <select
          value={branchFilter}
          onChange={(e) => setBranchFilter(e.target.value)}
          style={{
            background: '#4a5568',
            border: '1px solid #718096',
            borderRadius: 6,
            padding: '4px 8px',
            color: '#e2e8f0',
            fontSize: 14,
            minWidth: 120,
          }}
        >
          <option value="">כל הסניפים</option>
          {uniqueBranches.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>

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
            מסונן: {filterContext.category}
          </span>
        )}

        <div style={{ flex: 1 }} />

        <button
          onClick={() => setShowExceptionForm((v) => !v)}
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
          + הוסף חריג
        </button>
      </header>

      {/* Inline exception form */}
      {showExceptionForm && (
        <form
          onSubmit={handleSubmitException}
          style={{
            background: '#2d3748',
            borderBottom: '1px solid #4a5568',
            padding: '12px 20px',
            display: 'flex',
            gap: 12,
            flexWrap: 'wrap',
            alignItems: 'flex-end',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: '#a0aec0' }}>מזהה עובד</label>
            <input
              type="number"
              required
              value={exceptionForm.employee_id}
              onChange={(e) =>
                setExceptionForm((f) => ({ ...f, employee_id: e.target.value === '' ? '' : Number(e.target.value) }))
              }
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: '#a0aec0' }}>מתאריך</label>
            <input
              type="date"
              required
              value={exceptionForm.from_date}
              onChange={(e) => setExceptionForm((f) => ({ ...f, from_date: e.target.value }))}
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: '#a0aec0' }}>עד תאריך</label>
            <input
              type="date"
              required
              value={exceptionForm.to_date}
              onChange={(e) => setExceptionForm((f) => ({ ...f, to_date: e.target.value }))}
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: '#a0aec0' }}>סוג</label>
            <select
              value={exceptionForm.exception_type}
              onChange={(e) => setExceptionForm((f) => ({ ...f, exception_type: e.target.value }))}
              style={inputStyle}
            >
              {Object.entries(EXCEPTION_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 12, color: '#a0aec0' }}>הערות</label>
            <input
              type="text"
              value={exceptionForm.notes}
              onChange={(e) => setExceptionForm((f) => ({ ...f, notes: e.target.value }))}
              style={{ ...inputStyle, minWidth: 160 }}
            />
          </div>
          <button type="submit" style={btnStyle}>שמור</button>
          <button
            type="button"
            onClick={() => setShowExceptionForm(false)}
            style={{ ...btnStyle, background: '#718096' }}
          >
            ביטול
          </button>
          {exceptionError && (
            <span style={{ color: '#fc8181', fontSize: 13 }}>{exceptionError}</span>
          )}
          {exceptionSuccess && (
            <span style={{ color: '#68d391', fontSize: 13 }}>נשמר בהצלחה</span>
          )}
        </form>
      )}

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
          const employees = filteredStaff.filter((e) => e.status === status);
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
                  {employees.length}
                </span>
              </div>

              {/* Employee cards */}
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
                {employees.length === 0 && (
                  <div style={{ color: '#718096', fontSize: 13, textAlign: 'center', paddingTop: 20 }}>
                    אין עובדים
                  </div>
                )}
                {employees.map((emp) => (
                  <div
                    key={emp.id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, emp)}
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
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{emp.name}</div>
                    <div style={{ fontSize: 12, color: '#4a5568', marginBottom: 6 }}>
                      {emp.branch_code}
                      {emp.shift_type && (
                        <span style={{ marginRight: 8, color: '#718096' }}>• {emp.shift_type}</span>
                      )}
                    </div>
                    {emp.roles.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
                        {emp.roles.map((role) => (
                          <span
                            key={role}
                            style={{
                              background: '#e2e8f0',
                              color: '#2d3748',
                              borderRadius: 10,
                              padding: '1px 8px',
                              fontSize: 11,
                              fontWeight: 500,
                            }}
                          >
                            {role}
                          </span>
                        ))}
                      </div>
                    )}
                    {emp.exception_type && (
                      <div
                        style={{
                          fontSize: 11,
                          color: '#e53e3e',
                          fontWeight: 500,
                          marginTop: 2,
                        }}
                      >
                        {EXCEPTION_LABELS[emp.exception_type] ?? emp.exception_type}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const inputStyle: React.CSSProperties = {
  background: '#4a5568',
  border: '1px solid #718096',
  borderRadius: 6,
  padding: '4px 8px',
  color: '#e2e8f0',
  fontSize: 13,
  fontFamily: 'inherit',
};

const btnStyle: React.CSSProperties = {
  background: '#3182ce',
  border: 'none',
  borderRadius: 6,
  padding: '6px 14px',
  color: '#fff',
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: 'inherit',
  alignSelf: 'flex-end',
};
