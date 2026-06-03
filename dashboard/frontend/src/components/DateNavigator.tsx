import React from 'react';

interface DateNavigatorProps {
  selectedDate: string;     // ISO date
  datesWithIssues: string[]; // dates that have real issues (solid red dot)
  predictedDates: string[];  // dates with only predicted issues (hollow orange dot)
  onDateChange: (date: string) => void;
}

function toISODateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function todayString(): string {
  return toISODateString(new Date());
}

function tomorrowString(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return toISODateString(d);
}

function addDays(isoDate: string, days: number): string {
  const d = new Date(isoDate + 'T00:00:00');
  d.setDate(d.getDate() + days);
  return toISODateString(d);
}

function formatDateLabel(isoDate: string): string {
  const today = todayString();
  const tomorrow = tomorrowString();
  if (isoDate === today) return 'היום';
  if (isoDate === tomorrow) return 'מחר';
  const d = new Date(isoDate + 'T00:00:00');
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `${day}/${month}`;
}

export default function DateNavigator({
  selectedDate,
  datesWithIssues,
  predictedDates,
  onDateChange,
}: DateNavigatorProps) {
  const issueSet = new Set(datesWithIssues);
  const predictedSet = new Set(predictedDates);

  const prevDate = addDays(selectedDate, -1);
  const nextDate = addDays(selectedDate, 1);

  // Next 7 days from today
  const today = todayString();
  const chips: string[] = [];
  for (let i = 0; i < 7; i++) {
    chips.push(addDays(today, i));
  }

  const containerStyle: React.CSSProperties = {
    direction: 'rtl',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '10px',
    padding: '12px 16px',
    backgroundColor: '#ffffff',
    borderBottom: '1px solid #e2e8f0',
    userSelect: 'none',
  };

  const navRowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  };

  const arrowBtnStyle: React.CSSProperties = {
    background: 'none',
    border: '1px solid #e2e8f0',
    borderRadius: '6px',
    width: '32px',
    height: '32px',
    cursor: 'pointer',
    fontSize: '16px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#4a5568',
    padding: 0,
  };

  const dateLabelStyle: React.CSSProperties = {
    fontSize: '16px',
    fontWeight: 700,
    color: '#2d3748',
    minWidth: '80px',
    textAlign: 'center',
  };

  const chipsRowStyle: React.CSSProperties = {
    display: 'flex',
    gap: '6px',
    flexWrap: 'wrap',
    justifyContent: 'center',
  };

  return (
    <div style={containerStyle}>
      {/* Main nav row */}
      <div style={navRowStyle}>
        {/* In RTL: right arrow = next day (appears on left visually), left arrow = prev day */}
        <button
          style={arrowBtnStyle}
          onClick={() => onDateChange(nextDate)}
          title="יום הבא"
          aria-label="יום הבא"
        >
          ›
        </button>
        <span style={dateLabelStyle}>{formatDateLabel(selectedDate)}</span>
        <button
          style={arrowBtnStyle}
          onClick={() => onDateChange(prevDate)}
          title="יום קודם"
          aria-label="יום קודם"
        >
          ‹
        </button>
      </div>

      {/* Chips row */}
      <div style={chipsRowStyle}>
        {chips.map((chipDate) => {
          const isSelected = chipDate === selectedDate;
          const hasRealIssues = issueSet.has(chipDate);
          // Only show predicted dot if no real issues on this date
          const hasPredictedOnly = !hasRealIssues && predictedSet.has(chipDate);

          const chipStyle: React.CSSProperties = {
            position: 'relative',
            padding: '4px 10px 12px 10px',
            borderRadius: '9999px',
            border: isSelected ? '2px solid #3182ce' : '1px solid #e2e8f0',
            backgroundColor: isSelected ? '#ebf8ff' : '#f7fafc',
            color: isSelected ? '#2b6cb0' : '#4a5568',
            fontSize: '12px',
            fontWeight: isSelected ? 700 : 400,
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          };

          return (
            <button
              key={chipDate}
              style={chipStyle}
              onClick={() => onDateChange(chipDate)}
              title={chipDate}
            >
              {formatDateLabel(chipDate)}
              {hasRealIssues && (
                <span
                  title="יש בעיות פתוחות"
                  style={{
                    position: 'absolute',
                    bottom: '3px',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor: '#e53e3e',
                    display: 'inline-block',
                  }}
                />
              )}
              {hasPredictedOnly && (
                <span
                  title="יש בעיות חזויות"
                  style={{
                    position: 'absolute',
                    bottom: '3px',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor: 'transparent',
                    border: '1.5px solid #dd6b20',
                    display: 'inline-block',
                    boxSizing: 'border-box',
                  }}
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
