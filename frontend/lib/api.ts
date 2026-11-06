import type {
  DashboardStats,
  DocumentDetail,
  DocumentListItem,
  DocumentListResponse,
  Job,
  LoginResponse,
  Meta,
  SearchResponse,
  SheetRow,
  UploadResponse,
  User,
  Extraction,
  Finding,
  Invoice,
  Reconciliation,
} from "./types";

const BASE = "/api/v1";
export const TOKEN_KEY = "docintel_token";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item: { msg?: string; loc?: string[] }) => item.msg || item.loc?.join("."))
        .filter(Boolean)
        .join(", ");
    }
    return body.title || body.message || "Request failed";
  } catch {
    return response.statusText || "Request failed";
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("docintel:unauthorized"));
    }
    const detail = await parseError(response);
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const result = await apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(result.token);
  return result;
}

export async function logout(): Promise<void> {
  try {
    await apiRequest("/auth/logout", { method: "POST" });
  } finally {
    setToken(null);
  }
}

export function me(): Promise<User> {
  return apiRequest<User>("/auth/me");
}

export function getMeta(): Promise<Meta> {
  return apiRequest<Meta>("/meta");
}

export function listDocuments(params: {
  q?: string;
  status?: string;
  kind?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<DocumentListResponse> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== null) search.set(key, String(value));
  });
  return apiRequest<DocumentListResponse>(`/documents?${search.toString()}`);
}

export function getDocument(id: string, includeText = false): Promise<DocumentDetail> {
  return apiRequest<DocumentDetail>(`/documents/${id}?include_text=${includeText}`);
}

export function reprocessDocument(id: string): Promise<{ job_id: string; status: string }> {
  return apiRequest(`/documents/${id}/reprocess`, {
    method: "POST",
    body: JSON.stringify({ stage: "all" }),
  });
}

export function approveDocument(
  id: string,
  note?: string,
): Promise<{ document_id: string; status: string; approved_invoice_ids: string[] }> {
  return apiRequest(`/documents/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function saveExtraction(
  invoiceId: string,
  extractionId: string,
  version: number,
  changes: Record<string, unknown>,
  reason?: string,
): Promise<Extraction> {
  return apiRequest(`/invoices/${invoiceId}/extractions/${extractionId}`, {
    method: "PATCH",
    headers: { "If-Match": String(version) },
    body: JSON.stringify({ changes, reason: reason || "Manual correction" }),
  });
}

export function reviewInvoice(
  invoiceId: string,
  action: "approve" | "reopen",
  note?: string,
): Promise<Invoice> {
  return apiRequest(`/invoices/${invoiceId}/review`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
}

export function updateFinding(
  findingId: string,
  status: "resolved" | "dismissed",
  note?: string,
): Promise<Finding> {
  return apiRequest(`/findings/${findingId}`, {
    method: "PATCH",
    body: JSON.stringify({ status, note }),
  });
}

export function updateReconciliation(
  reconciliationId: string,
  status: "matched" | "dismissed",
  note?: string,
): Promise<Reconciliation> {
  return apiRequest(`/reconciliations/${reconciliationId}`, {
    method: "PATCH",
    body: JSON.stringify({ status, note }),
  });
}

export function searchDocuments(params: {
  q: string;
  mode?: string;
  status?: string;
  kind?: string;
  supplier?: string;
  currency?: string;
  limit?: number;
}): Promise<SearchResponse> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  return apiRequest<SearchResponse>(`/search?${search.toString()}`);
}

export function getDashboard(): Promise<DashboardStats> {
  return apiRequest<DashboardStats>("/dashboard/stats");
}

export function listJobs(status?: string): Promise<Job[]> {
  const search = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest<Job[]>(`/jobs${search}`);
}

export function retryJob(jobId: string): Promise<Job> {
  return apiRequest(`/jobs/${jobId}/retry`, { method: "POST" });
}

export function getSheetRows(
  documentId: string,
  offset = 0,
  limit = 100,
  sheet?: string,
): Promise<{ items: SheetRow[]; total: number }> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (sheet) params.set("sheet", sheet);
  return apiRequest(`/documents/${documentId}/sheet-rows?${params.toString()}`);
}

export function getDocumentText(
  documentId: string,
  pageFrom = 1,
  pageTo?: number,
): Promise<{
  document_id: string;
  pages: Array<{
    page_number: number;
    text_source: string;
    ocr_confidence: number | null;
    width: number;
    height: number;
    error: string | null;
    text: string | null;
  }>;
}> {
  const params = new URLSearchParams({ page_from: String(pageFrom) });
  if (pageTo) params.set("page_to", String(pageTo));
  return apiRequest(`/documents/${documentId}/text?${params.toString()}`);
}

export function uploadDocuments(
  files: File[],
  onProgress: (percent: number) => void,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/documents`);
    xhr.withCredentials = true;
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve(body as UploadResponse);
      } else {
        const detail =
          (body as { detail?: string | Array<{ msg?: string }> } | null)?.detail || "Upload failed";
        reject(
          new ApiError(
            xhr.status,
            typeof detail === "string"
              ? detail
              : detail.map((item) => item.msg).filter(Boolean).join(", "),
          ),
        );
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
    xhr.send(form);
  });
}

export async function downloadDocument(documentId: string, filename: string): Promise<void> {
  const response = await fetch(`${BASE}/documents/${documentId}/file`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function fetchPagePreview(documentId: string, page: number): Promise<string> {
  const response = await fetch(`${BASE}/documents/${documentId}/pages/${page}/preview`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (!response.ok) throw new ApiError(response.status, "Could not load page preview");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export function getDocumentListSync(items: DocumentListItem[]): DocumentListItem[] {
  return [...items].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
}
