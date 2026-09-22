/**
 * 最终评分长请求断连后的只读报告恢复。
 * 硬约束：结果不明时绝不自动重发答案 POST；仅轮询 GET /api/reports/{sid}。
 */

import { parseReportResponse, type ReportData } from "./report-data.ts";

/** 轮询间隔（毫秒）。集中定义，禁止散落魔数。 */
export const REPORT_POLL_INTERVAL_MS = 2000;
/** 最长轮询时长（毫秒）。 */
export const REPORT_POLL_MAX_MS = 120_000;

export const CONFIRMING_NOTICE = "正在确认评分结果，请勿重复提交";
export const TIMEOUT_NOTICE = "结果状态仍未知，请打开报告页确认";

/** 已知业务 detail.code；带这些码的响应不按「反代式不明 500」处理。 */
export const KNOWN_BUSINESS_CODES = [
  "ANSWER_IN_PROGRESS",
  "ASR_UNAVAILABLE",
  "AUDIO_PROCESS_FAILED",
  "AUDIO_INVALID",
  "AUDIO_TOO_LARGE",
  "SCORING_UNAVAILABLE",
  "SESSION_COMPLETED",
  "SESSION_NOT_FOUND",
  "JOB_NOT_FOUND",
  "REPORT_NOT_FOUND",
] as const;

export type KnownBusinessCode = (typeof KNOWN_BUSINESS_CODES)[number];

export type FetchLike = (
  input: string,
  init?: { method?: string; headers?: Record<string, string>; signal?: AbortSignal; cache?: string },
) => Promise<Response>;

export type SleepFn = (ms: number, signal?: AbortSignal) => Promise<void>;

export type AnswerPostResult =
  | { kind: "network" }
  | { kind: "http"; status: number; code: string | null; serverMessage: string | null }
  | { kind: "invalid"; message: string }
  | { kind: "ok"; value: unknown };

export type ReportPollResult =
  | { kind: "ready"; report: ReportData }
  | { kind: "not_ready" }
  | { kind: "session_not_found" }
  | { kind: "invalid"; message: string }
  | { kind: "http_error"; status: number }
  | { kind: "network" }
  | { kind: "aborted" }
  | { kind: "timeout" };

export type ResolveOutcome =
  | { outcome: "answer_ok"; value: unknown }
  | { outcome: "report_ready"; report: ReportData }
  | { outcome: "scoring_unavailable"; status: number; code: string; serverMessage: string | null }
  | { outcome: "answer_in_progress"; status: number; code: string; serverMessage: string | null }
  | {
      outcome: "retryable_client";
      status: number;
      code: string | null;
      serverMessage: string | null;
    }
  | {
      outcome: "business_error";
      status: number;
      code: string | null;
      serverMessage: string | null;
    }
  | { outcome: "invalid_locked"; message: string }
  | { outcome: "session_not_found" }
  | { outcome: "still_unknown"; reason: "timeout" | "invalid_report" | "unexpected_http" | "network" }
  | { outcome: "aborted" };

export type RecoveryDeps = {
  fetch: FetchLike;
  sleep: SleepFn;
  signal?: AbortSignal;
  intervalMs?: number;
  maxMs?: number;
  now?: () => number;
};

function isKnownBusinessCode(code: string | null): code is KnownBusinessCode {
  if (code === null) {
    return false;
  }
  return (KNOWN_BUSINESS_CODES as readonly string[]).includes(code);
}

/**
 * 结果不明：网络异常，或 HTTP 500 且无已知业务 detail.code（Next 反代失败特征）。
 */
export function isAmbiguousSubmitFailure(post: AnswerPostResult): boolean {
  if (post.kind === "network") {
    return true;
  }
  if (post.kind === "http" && post.status === 500 && !isKnownBusinessCode(post.code)) {
    return true;
  }
  return false;
}

/** 409 SESSION_COMPLETED：不得重发，可只读确认报告。 */
export function shouldConfirmReportReadOnly(post: AnswerPostResult): boolean {
  return post.kind === "http" && post.code === "SESSION_COMPLETED";
}

export function shouldEnterReportRecovery(post: AnswerPostResult): boolean {
  return isAmbiguousSubmitFailure(post) || shouldConfirmReportReadOnly(post);
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof Error && error.name === "AbortError") ||
    (typeof DOMException !== "undefined" &&
      error instanceof DOMException &&
      error.name === "AbortError")
  );
}

async function readDetailCode(response: Response): Promise<{
  code: string | null;
  message: string | null;
}> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { code: null, message: null };
  }
  if (
    typeof payload !== "object" ||
    payload === null ||
    Array.isArray(payload) ||
    !("detail" in payload)
  ) {
    return { code: null, message: null };
  }
  const detail = (payload as { detail: unknown }).detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) {
    return { code: null, message: null };
  }
  const codeRaw = (detail as { code?: unknown }).code;
  const msgRaw = (detail as { message?: unknown }).message;
  const code =
    typeof codeRaw === "string" && codeRaw.trim().length > 0 ? codeRaw.trim() : null;
  const message =
    typeof msgRaw === "string" && msgRaw.trim().length > 0 ? msgRaw.trim() : null;
  return { code, message };
}

/**
 * 单次只读查询报告。不调用 LLM，不重发答案。
 */
export async function fetchReportOnce(
  sid: number,
  deps: Pick<RecoveryDeps, "fetch" | "signal">,
): Promise<ReportPollResult> {
  if (deps.signal?.aborted) {
    return { kind: "aborted" };
  }
  let response: Response;
  try {
    response = await deps.fetch(`/api/reports/${sid}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: deps.signal,
    });
  } catch (error) {
    if (isAbortError(error) || deps.signal?.aborted) {
      return { kind: "aborted" };
    }
    return { kind: "network" };
  }

  if (response.status === 200) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return { kind: "invalid", message: "报告响应不是合法 JSON" };
    }
    try {
      const report = parseReportResponse(payload);
      return { kind: "ready", report };
    } catch (error) {
      const message = error instanceof Error ? error.message : "报告结构非法";
      return { kind: "invalid", message };
    }
  }

  if (response.status === 404) {
    const { code } = await readDetailCode(response);
    if (code === "SESSION_NOT_FOUND") {
      return { kind: "session_not_found" };
    }
    if (code === "REPORT_NOT_FOUND") {
      return { kind: "not_ready" };
    }
    // 未知 404、缺少 detail.code 或其他业务码：立即停止，禁止空等
    return { kind: "http_error", status: 404 };
  }

  return { kind: "http_error", status: response.status };
}

/**
 * 轮询 GET /api/reports/{sid}：首次立即查询，之后按间隔，最长 maxMs。
 */
export async function pollForReport(sid: number, deps: RecoveryDeps): Promise<ReportPollResult> {
  const intervalMs = deps.intervalMs ?? REPORT_POLL_INTERVAL_MS;
  const maxMs = deps.maxMs ?? REPORT_POLL_MAX_MS;
  const now = deps.now ?? (() => Date.now());
  const start = now();

  while (true) {
    if (deps.signal?.aborted) {
      return { kind: "aborted" };
    }

    const once = await fetchReportOnce(sid, deps);
    if (once.kind === "ready") {
      return once;
    }
    if (once.kind === "session_not_found") {
      return once;
    }
    if (once.kind === "invalid") {
      return once;
    }
    if (once.kind === "http_error") {
      return once;
    }
    if (once.kind === "network") {
      return once;
    }
    if (once.kind === "aborted") {
      return once;
    }
    // not_ready → 继续

    if (now() - start >= maxMs) {
      return { kind: "timeout" };
    }

    try {
      await deps.sleep(intervalMs, deps.signal);
    } catch (error) {
      if (isAbortError(error) || deps.signal?.aborted) {
        return { kind: "aborted" };
      }
      throw error;
    }

    if (now() - start >= maxMs) {
      return { kind: "timeout" };
    }
  }
}

/**
 * 根据单次 POST 结果决定是否进入只读报告恢复；绝不在此函数内重发 POST。
 * `submitOnce` 由调用方保证只调用一次并传入其结果。
 */
export async function resolveAfterAnswerSubmit(
  postResult: AnswerPostResult,
  sid: number,
  deps: RecoveryDeps,
): Promise<ResolveOutcome> {
  if (postResult.kind === "ok") {
    return { outcome: "answer_ok", value: postResult.value };
  }

  if (postResult.kind === "invalid") {
    return { outcome: "invalid_locked", message: postResult.message };
  }

  if (postResult.kind === "http") {
    const code = postResult.code ?? "";
    if (code === "SCORING_UNAVAILABLE") {
      return {
        outcome: "scoring_unavailable",
        status: postResult.status,
        code,
        serverMessage: postResult.serverMessage,
      };
    }
    if (code === "ANSWER_IN_PROGRESS") {
      return {
        outcome: "answer_in_progress",
        status: postResult.status,
        code,
        serverMessage: postResult.serverMessage,
      };
    }
    if (
      code === "AUDIO_INVALID" ||
      code === "AUDIO_TOO_LARGE" ||
      postResult.status === 413 ||
      postResult.status === 422
    ) {
      return {
        outcome: "retryable_client",
        status: postResult.status,
        code: postResult.code,
        serverMessage: postResult.serverMessage,
      };
    }
    if (
      code === "ASR_UNAVAILABLE" ||
      code === "AUDIO_PROCESS_FAILED"
    ) {
      return {
        outcome: "retryable_client",
        status: postResult.status,
        code: postResult.code,
        serverMessage: postResult.serverMessage,
      };
    }
    if (!shouldEnterReportRecovery(postResult)) {
      return {
        outcome: "business_error",
        status: postResult.status,
        code: postResult.code,
        serverMessage: postResult.serverMessage,
      };
    }
  }

  // network / proxy_500 / SESSION_COMPLETED → 只读轮询
  const polled = await pollForReport(sid, deps);
  if (polled.kind === "ready") {
    return { outcome: "report_ready", report: polled.report };
  }
  if (polled.kind === "session_not_found") {
    return { outcome: "session_not_found" };
  }
  if (polled.kind === "aborted") {
    return { outcome: "aborted" };
  }
  if (polled.kind === "timeout") {
    return { outcome: "still_unknown", reason: "timeout" };
  }
  if (polled.kind === "invalid") {
    return { outcome: "still_unknown", reason: "invalid_report" };
  }
  if (polled.kind === "network") {
    return { outcome: "still_unknown", reason: "network" };
  }
  return { outcome: "still_unknown", reason: "unexpected_http" };
}

/**
 * 严格只调用一次 submitOnce，再按结果决定是否只读恢复报告。
 */
export async function submitOnceThenResolve(
  submitOnce: () => Promise<AnswerPostResult>,
  sid: number,
  deps: RecoveryDeps,
): Promise<ResolveOutcome> {
  const postResult = await submitOnce();
  return resolveAfterAnswerSubmit(postResult, sid, deps);
}

/** 测试/页面可用的瞬时 sleep；尊重 AbortSignal。 */
export function createImmediateSleep(advance?: (ms: number) => void): SleepFn {
  return async (ms, signal) => {
    if (signal?.aborted) {
      const err = new Error("The operation was aborted");
      err.name = "AbortError";
      throw err;
    }
    advance?.(ms);
  };
}

/** 虚拟时钟：sleep 推进 now()，便于单测压缩 120s 上限。 */
export function createVirtualClock(startMs = 0): {
  now: () => number;
  sleep: SleepFn;
} {
  let t = startMs;
  return {
    now: () => t,
    sleep: createImmediateSleep((ms) => {
      t += ms;
    }),
  };
}

export function reportPathForSid(sid: number): string {
  return `/reports/${sid}`;
}
