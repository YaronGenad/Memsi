import { emit, listen } from '@tauri-apps/api/event';

export const EVENTS = {
  ISSUE_SELECTED: 'issue-selected',    // missions → staff + inventory
  ASSET_DRAGGED: 'asset-dragged',       // staff/inventory → missions
  DATE_CHANGED: 'date-changed',         // missions → all
  FILTER_CLEARED: 'filter-cleared',     // missions → all
};

export const emitIssueSelected = (payload: { branch: string; category: string; date: string }) =>
  emit(EVENTS.ISSUE_SELECTED, payload);

export const listenIssueSelected = (handler: (payload: unknown) => void) =>
  listen(EVENTS.ISSUE_SELECTED, (e) => handler(e.payload));

export const emitAssetDragged = (payload: { assetId: string; targetDate: string }) =>
  emit(EVENTS.ASSET_DRAGGED, payload);

export const listenAssetDragged = (handler: (payload: unknown) => void) =>
  listen(EVENTS.ASSET_DRAGGED, (e) => handler(e.payload));

export const emitDateChanged = (payload: { date: string }) =>
  emit(EVENTS.DATE_CHANGED, payload);

export const listenDateChanged = (handler: (payload: unknown) => void) =>
  listen(EVENTS.DATE_CHANGED, (e) => handler(e.payload));

export const emitFilterCleared = () =>
  emit(EVENTS.FILTER_CLEARED, {});

export const listenFilterCleared = (handler: () => void) =>
  listen(EVENTS.FILTER_CLEARED, () => handler());
