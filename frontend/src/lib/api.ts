/** 统一 API 客户端：{data} 信封解包、401 跳登录、错误转中文消息。 */

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** 401 统一跳登录（SSR/测试环境无 window 时安全跳过）。 */
function redirectToLogin() {
  if (typeof window !== "undefined") window.location.href = "/login";
}

export async function api<T = unknown>(
  path: string,
  opts: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = opts;
  const headers: Record<string, string> = { ...(rest.headers as Record<string, string>) };
  let body = rest.body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  const res = await fetch(path, { ...rest, headers, body });

  if (res.status === 401 && !path.startsWith("/api/auth")) {
    redirectToLogin();
    throw new ApiError("未登录", 401);
  }
  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    /* 空响应 */
  }
  if (!res.ok) {
    const p = payload as { detail?: unknown; error?: { message?: string } } | null;
    const detail =
      typeof p?.detail === "string"
        ? p.detail
        : Array.isArray(p?.detail)
          ? (p?.detail as { msg?: string }[]).map((d) => d.msg).join("; ")
          : p?.error?.message;
    throw new ApiError(detail || `请求失败（HTTP ${res.status}）`, res.status);
  }
  // 后端统一 {data: ...} 信封；webhook 等返回裸对象则原样
  const env = payload as { data?: unknown } | null;
  return (env && "data" in env ? env.data : payload) as T;
}

/** 上传文件（multipart）。 */
export async function upload(path: string, form: FormData): Promise<unknown> {
  const res = await fetch(path, { method: "POST", body: form });
  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError("未登录", 401);
  }
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((payload as { detail?: string }).detail || "上传失败", res.status);
  return (payload as { data?: unknown }).data ?? payload;
}

// ---------------------------------------------------------------- 类型 ----

export interface Contact {
  id: number; email: string; name: string; status: string; source: string; note: string;
  created_at: string | null; last_email_at: string | null;
  tags: { id: number; name: string; color: string }[];
}

export interface ImportReport {
  total_rows: number; added: number; updated: number; skipped_duplicates: number;
  excluded_unsubscribed: number; invalid_count: number;
  invalid: { raw: string; reason: string }[];
}

export interface Template {
  id: number; name: string; subject: string; mode: string; body: string;
  variables: string[]; created_at: string | null; updated_at: string | null;
}

export interface Channel {
  id: number; kind: "resend" | "smtp"; name: string; config: Record<string, unknown>;
  is_default: boolean; status: string; last_error: string; created_at: string | null;
}

export interface CampaignPlan {
  total: number; by_status: Record<string, number>; batch_size: number; rate_per_minute: number;
  batches: number; estimated_minutes: number;
  channel: { id: number; name: string; kind: string } | null; subject: string;
  generated_at: string;
}

export interface Campaign {
  id: number; name: string; subject: string; mode: string; body: string;
  channel_id: number | null; status: string;
  batch_size: number; rate_per_minute: number; max_retries: number;
  plan: CampaignPlan | null; counts: Record<string, number>; variables: string[];
  created_at: string | null; started_at: string | null; finished_at: string | null;
}

export interface Recipient {
  id: number; email: string; name: string; status: string; attempts: number; error: string;
  sent_at: string | null; delivered_at: string | null; opened_at: string | null;
  bounced_at: string | null; complained_at: string | null;
}

export interface RecipientEvent {
  id: number; type: string; detail: Record<string, unknown>; created_at: string | null;
}

export interface Message {
  id: number; direction: string; subject: string; snippet: string; text: string; html: string;
  from_email: string; from_name: string; to_email: string;
  is_read: boolean; is_archived: boolean; contact_id: number | null;
  received_at: string | null; sent_at: string | null;
}

export interface AIConfig {
  id: number; name: string; base_url: string; api_key: string; model: string;
  is_active: boolean; last_test_at: string | null; last_test_ok: boolean | null;
}

export interface CheckupResult {
  score: number; level: string;
  issues: { code: string; message: string; severity: string }[];
  suggestions: string[]; rule_hits: Record<string, unknown>;
  ai_available?: boolean; ai_error?: string;
}

export interface DashboardStats {
  contacts: { total: number; active?: number; unsubscribed?: number; bounced?: number; complained?: number };
  campaigns: { total: number; sending: number };
  delivery: {
    sent: number; delivered: number; opened: number; bounced: number; complained: number;
    pending: number; deliver_rate: number | null; open_rate: number | null;
  };
  inbox: { unread: number };
}
