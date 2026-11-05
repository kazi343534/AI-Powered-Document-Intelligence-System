export type Role = "admin" | "reviewer" | "viewer";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
}

export interface Evidence {
  page: number | null;
  quote: string | null;
}

export interface FieldValue {
  value: string | null;
  confidence: number;
  evidence: Evidence | null;
  reason: string | null;
}

export interface ExtractionLineItem {
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
  tax_rate: string | null;
  confidence: number;
  page: number | null;
}

export interface ExtractionData {
  schema_version: string;
  document_type: string;
  invoice_number: FieldValue;
  invoice_date: FieldValue;
  supplier_name: FieldValue;
  supplier_tax_id: FieldValue;
  customer_name: FieldValue;
  currency: FieldValue;
  subtotal: FieldValue;
  tax: FieldValue;
  total: FieldValue;
  line_items: ExtractionLineItem[];
  warnings: string[];
}

export interface LineItem {
  id: string;
  line_no: number;
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
  tax_rate: string | null;
  confidence: number;
  page: number | null;
}

export interface Extraction {
  id: string;
  invoice_id: string;
  version: number;
  schema_version: string;
  prompt_version: string;
  model: string;
  source: string;
  data: ExtractionData;
  confidence: {
    overall?: number;
    fields?: Record<string, number>;
  };
  review_status: "pending" | "approved";
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
  line_items: LineItem[];
}

export interface Finding {
  id: string;
  document_id: string;
  invoice_id: string | null;
  extraction_id: string | null;
  rule_code: string;
  severity: "info" | "warning" | "error";
  field_path: string;
  message: string;
  expected: string | null;
  actual: string | null;
  status: "open" | "resolved" | "dismissed";
  resolution_note: string | null;
  created_at: string;
}

export interface Reconciliation {
  id: string;
  invoice_id: string;
  matched_invoice_id: string | null;
  matched_document_id: string | null;
  sheet_row_id: string | null;
  match_type: "pdf_pdf" | "pdf_sheet";
  confidence: number;
  diffs: Array<{
    field: string;
    invoice_value: string | null;
    sheet_value: string | null;
    severity: string;
  }>;
  status: "matched" | "mismatch" | "dismissed";
  created_at: string;
}

export interface Invoice {
  id: string;
  document_id: string;
  page_start: number;
  page_end: number;
  status: string;
  grouping_confidence: number;
  current_extraction: Extraction | null;
  findings: Finding[];
}

export interface DocSummary {
  invoice_number: string | null;
  supplier_name: string | null;
  total: string | null;
  currency: string | null;
  confidence: number | null;
  review_status: string | null;
}

export type DocumentStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "completed"
  | "needs_review"
  | "failed";

export interface LoginResponse {
  token: string;
  user: User;
}

export interface DocumentListResponse {
  items: DocumentListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentListItem {
  id: string;
  original_filename: string;
  kind: "pdf" | "image" | "spreadsheet";
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  stage: string;
  page_count: number;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  invoice_count: number;
  finding_count: number;
  summary: DocSummary | null;
  duplicate?: boolean;
}

export interface PageInfo {
  page_number: number;
  text_source: string;
  ocr_confidence: number | null;
  width: number;
  height: number;
  error: string | null;
  text: string | null;
}

export interface Job {
  id: string;
  document_id: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DocumentDetail extends DocumentListItem {
  pages: PageInfo[];
  invoices: Invoice[];
  findings: Finding[];
  jobs: Job[];
  reconciliations: Reconciliation[];
}

export interface SheetRow {
  id: string;
  sheet_name: string;
  row_number: number;
  data: Record<string, unknown>;
  normalized: Record<string, unknown>;
  warnings: string[];
}

export interface SearchHit {
  document_id: string;
  document: DocumentListItem;
  score: number;
  snippet: string;
  page_number: number | null;
  invoice_id: string | null;
  match: string;
}

export interface SearchResponse {
  query: string;
  mode: string;
  items: SearchHit[];
  total: number;
}

export interface DashboardStats {
  documents: Record<string, number>;
  kinds: Record<string, number>;
  findings: Record<string, number>;
  recent_documents: DocumentListItem[];
  queue_depth: number;
  avg_processing_seconds: number | null;
  total_documents: number;
  needs_review: number;
  failed: number;
}

export interface Meta {
  app: string;
  environment: string;
  ai_enabled: boolean;
  ai_model: string | null;
  ocr_engine: string;
  embedding_provider: string;
  storage_backend: string;
  supported_extensions: string[];
  max_file_mb: number;
}

export interface UploadResponse {
  documents: DocumentListItem[];
  rejected: Array<{ filename: string; code: string; message: string }>;
}
