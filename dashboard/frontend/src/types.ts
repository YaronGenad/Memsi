export interface InventoryItem {
  location_type: 'marlug' | 'branch';
  branch_code: string;
  category: string;
  available_quantity: number;
  min_quantity: number;
  current_quantity: number;
  status: 'AVAILABLE' | 'ASSIGNED';
}

export interface Issue {
  id: number;
  issue_date: string;       // ISO date
  branch_code: string;
  category: string;
  issue_type: string;       // 'INVENTORY_SHORTAGE' | 'STAFF_SHORTAGE'
  severity: number;         // 1–10
  status: string;           // 'OPEN' | 'PENDING' | 'RESOLVED'
  gap: number | null;
  min_quantity: number | null;
  current_quantity: number | null;
  resolution_note: string | null;
  predicted: boolean;
  confidence: number | null;
  resolved_at: string | null;
  created_at: string;
}
