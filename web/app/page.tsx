"use client";

import { useEffect, useRef, useState } from "react";

const TOTAL_QUESTIONS = 6;

type ApiMode = "mock" | "real";

type Job = {
  id: number;
  family: string;
  title: string;
  jdDigest: string;
};

type Question = {
  text: string;
  audioUrl: string | null;
  seq: number;
};

type View =
  | { phase: "config"; message: string }
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "jobs"; mode: ApiMode; jobs: Job[] }
  | { phase: "interview"; mode: "mock"; job: Job; question: Question }
  | {
      phase: "interview";
      mode: "real";
      job: Job;
      sid: number;
      question: Question;
    };

type ParseOk<T> = { ok: true; value: T };
type ParseErr = { ok: false; message: string };

export default function HomePage() {
  const [view, setView] = useState<View>(() => initialView());
  const [busy, setBusy] = useState(false);
  const [hold, setHold] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const createLock = useRef(false);

  useEffect(() => {
    const mode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
    if (!mode.ok || mode.mode !== "real") {
      return;
    }
    let alive = true;
    void loadRealJobList().then((result) => {
      if (!alive) {
        return;
      }
      if (!result.ok) {
        setView({ phase: "error", message: result.message });
        return;
      }
      if (result.value.length === 0) {
        setView({ phase: "empty" });
        return;
      }
      setView({ phase: "jobs", mode: "real", jobs: result.value });
    });
    return () => {
      alive = false;
    };
  }, []);

  async function choose(mode: ApiMode, job: Job) {
    if (createLock.current) {
      return;
    }
    createLock.current = true;
    setBusy(true);
    setNotice(null);

    if (mode === "mock") {
      setView({
        phase: "interview",
        mode: "mock",
        job,
        question: mockQuestion(),
      });
      setBusy(false);
      return;
    }

    const result = await requestRealSession(job.id);
    if (result.kind === "network") {
      setBusy(false);
      setHold(true);
      setNotice("网络失败，无法确认会话是否已创建。未自动重试。请刷新页面后再试。");
      return;
    }
    if (result.kind === "http") {
      createLock.current = false;
      setBusy(false);
      setNotice(formatApiError(result, "创建会话失败", "未进入面试，未自动重试。"));
      return;
    }
    if (result.kind === "invalid") {
      createLock.current = false;
      setBusy(false);
      setNotice(result.message);
      return;
    }

    setView({
      phase: "interview",
      mode: "real",
      job,
      sid: result.sid,
      question: result.question,
    });
    setBusy(false);
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <header className="mb-8 min-w-0 max-w-full">
        <p className="text-sm tracking-[0.18em] text-[#7eb6ff]">智能汽车座舱</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">智驾未来 · AI面试仓</h1>
        <p className="mt-2 max-w-full text-sm text-[#9fb4d4]">选择岗位，创建会话，查看首题。</p>
      </header>

      {view.phase === "config" ? <MessagePanel title="配置错误" message={view.message} /> : null}
      {view.phase === "loading" ? <StatusPanel title="正在加载岗位" /> : null}
      {view.phase === "empty" ? (
        <StatusPanel title="暂无岗位" detail="岗位列表为空。未进入面试。" />
      ) : null}
      {view.phase === "error" ? <MessagePanel title="无法加载岗位" message={view.message} /> : null}

      {view.phase === "jobs" ? (
        <section className="min-w-0 max-w-full">
          <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg text-white">岗位列表</h2>
            <ModeBadge mode={view.mode} />
          </div>
          {notice ? (
            <p className="mb-4 max-w-full break-anywhere rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]" role="alert">
              {notice}
            </p>
          ) : null}
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
            {view.jobs.map((job) => (
              <article
                key={job.id}
                className="min-w-0 max-w-full rounded-2xl border border-[#2f6fed] bg-[#0c1730]/90 p-5 shadow-[0_0_24px_rgba(47,111,237,0.28)]"
              >
                <p className="text-xs tracking-wide text-[#7eb6ff]">{job.family}</p>
                <h3 className="mt-2 break-anywhere text-xl text-white">{job.title}</h3>
                <p className="mt-3 break-anywhere text-sm leading-6 text-[#b7c8e2]">{job.jdDigest}</p>
                <button
                  type="button"
                  className="mt-5 max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={busy || hold}
                  onClick={() => {
                    void choose(view.mode, job);
                  }}
                >
                  {busy ? "正在创建会话…" : "选择此岗位"}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {view.phase === "interview" ? (
        <InterviewPanel
          mode={view.mode}
          job={view.job}
          question={view.question}
          sid={view.mode === "real" ? view.sid : null}
        />
      ) : null}
    </main>
  );
}

function InterviewPanel({
  mode,
  job,
  question,
  sid,
}: {
  mode: ApiMode;
  job: Job;
  question: Question;
  sid: number | null;
}) {
  return (
    <section className="min-w-0 max-w-full rounded-3xl border border-[#2f6fed] bg-[#0c1730]/95 p-6 shadow-[0_0_32px_rgba(47,111,237,0.35)]">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <ModeBadge mode={mode} />
        <p className="rounded-full border border-[#ff8a2a] bg-[#ff8a2a]/15 px-3 py-1 text-sm text-[#ffb067]">
          第{question.seq}题 / 共{TOTAL_QUESTIONS}题
        </p>
      </div>
      <p className="mt-6 text-sm text-[#7eb6ff]">{job.family}</p>
      <h2 className="mt-1 break-anywhere text-2xl text-white">{job.title}</h2>
      {sid !== null ? <p className="mt-2 text-sm text-[#9fb4d4]">会话 {sid}</p> : null}
      <p className="mt-6 break-anywhere text-lg leading-8 text-white">{question.text}</p>
    </section>
  );
}

function ModeBadge({ mode }: { mode: ApiMode }) {
  if (mode === "mock") {
    return (
      <span className="rounded-full border border-[#ff8a2a] px-3 py-1 text-xs text-[#ffb067]">
        演示模式 · 非正式数据
      </span>
    );
  }
  return (
    <span className="rounded-full border border-[#2f6fed] px-3 py-1 text-xs text-[#7eb6ff]">
      后端联调
    </span>
  );
}

function MessagePanel({ title, message }: { title: string; message: string }) {
  return (
    <section className="max-w-full rounded-2xl border border-[#ff8a2a] bg-[#2a1608] p-5" role="alert">
      <h2 className="text-lg text-[#ffb067]">{title}</h2>
      <p className="mt-2 break-anywhere text-sm leading-6 text-[#ffd0a8]">{message}</p>
    </section>
  );
}

function StatusPanel({ title, detail }: { title: string; detail?: string }) {
  return (
    <section className="max-w-full rounded-2xl border border-[#2f6fed] bg-[#0c1730]/90 p-5" role="status">
      <h2 className="text-lg text-white">{title}</h2>
      {detail ? <p className="mt-2 break-anywhere text-sm text-[#b7c8e2]">{detail}</p> : null}
    </section>
  );
}

function initialView(): View {
  const mode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
  if (!mode.ok) {
    return { phase: "config", message: mode.message };
  }
  if (mode.mode === "mock") {
    return { phase: "jobs", mode: "mock", jobs: mockJobs() };
  }
  return { phase: "loading" };
}

function readApiMode(raw: string | undefined): { ok: true; mode: ApiMode } | { ok: false; message: string } {
  if (raw === undefined) {
    return { ok: true, mode: "mock" };
  }
  if (raw === "mock" || raw === "real") {
    return { ok: true, mode: raw };
  }
  return {
    ok: false,
    message: `配置错误：NEXT_PUBLIC_API_MODE 只能是 mock 或 real，当前值为 ${JSON.stringify(raw)}`,
  };
}

function mockJobs(): Job[] {
  return [
    {
      id: 1,
      family: "演示",
      title: "演示岗位·智驾测试",
      jdDigest: "【非正式演示】这不是后端题库数据，仅用于 mock 模式界面联调。",
    },
    {
      id: 2,
      family: "演示",
      title: "演示岗位·三电系统",
      jdDigest: "【非正式演示】这不是后端题库数据，仅用于 mock 模式界面联调。",
    },
  ];
}

function mockQuestion(): Question {
  return {
    text: "【非正式占位】此文本不是正式面试题，仅供 mock 模式首题界面联调。",
    audioUrl: null,
    seq: 1,
  };
}

type ApiErrorInfo = {
  status: number;
  code: string | null;
  serverMessage: string | null;
};

function formatApiError(info: ApiErrorInfo, action: string, tail: string): string {
  const codeText = info.code ? `，${info.code}` : "";
  const messageText = info.serverMessage ? `：${info.serverMessage}` : "";
  return `${action}（HTTP ${info.status}${codeText}）${messageText}。${tail}`;
}

async function readApiError(response: Response): Promise<ApiErrorInfo> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { status: response.status, code: null, serverMessage: null };
  }
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return { status: response.status, code: null, serverMessage: null };
  }
  const code = nonEmptyString(payload.detail.code);
  const serverMessage = nonEmptyString(payload.detail.message);
  return { status: response.status, code, serverMessage };
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

async function loadRealJobList(): Promise<ParseOk<Job[]> | ParseErr> {
  let response: Response;
  try {
    response = await fetch("/api/jobs", {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return { ok: false, message: "网络失败，未能获取岗位列表。未改用演示数据。" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return {
      ok: false,
      message: formatApiError(info, "岗位列表请求失败", "未改用演示数据。"),
    };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, message: "岗位响应不是合法 JSON。未进入面试。" };
  }
  return parseJobs(payload);
}

type RealSessionResult =
  | { kind: "network" }
  | { kind: "http"; status: number; code: string | null; serverMessage: string | null }
  | { kind: "invalid"; message: string }
  | { kind: "ok"; sid: number; question: Question };

async function requestRealSession(jobId: number): Promise<RealSessionResult> {
  let response: Response;
  try {
    response = await fetch("/api/sessions", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id: jobId }),
      cache: "no-store",
    });
  } catch {
    return { kind: "network" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return { kind: "http", ...info };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "invalid", message: "会话响应不是合法 JSON。未进入面试。" };
  }
  const parsed = parseSession(payload);
  if (!parsed.ok) {
    return { kind: "invalid", message: parsed.message };
  }
  return { kind: "ok", sid: parsed.value.sid, question: parsed.value.question };
}

function parseJobs(payload: unknown): ParseOk<Job[]> | ParseErr {
  if (!isRecord(payload) || !Array.isArray(payload.jobs)) {
    return {
      ok: false,
      message: "岗位响应格式不正确：jobs 必须是数组。未进入面试。",
    };
  }
  const jobs: Job[] = [];
  for (const item of payload.jobs) {
    if (!isRecord(item) || !isPositiveInt(item.id)) {
      return {
        ok: false,
        message: "岗位响应格式不正确：id 必须为正整数。未进入面试。",
      };
    }
    if (typeof item.family !== "string" || typeof item.title !== "string" || typeof item.jd_digest !== "string") {
      return {
        ok: false,
        message: "岗位响应格式不正确：family、title、jd_digest 必须为字符串。未进入面试。",
      };
    }
    jobs.push({
      id: item.id,
      family: item.family,
      title: item.title,
      jdDigest: item.jd_digest,
    });
  }
  return { ok: true, value: jobs };
}

function parseSession(payload: unknown): ParseOk<{ sid: number; question: Question }> | ParseErr {
  const invalid =
    "会话响应格式不正确：sid 须为正整数，question.text 须为非空字符串，seq 须为 1–6 的整数，audio_url 须为 null 或非空字符串。未进入面试。";
  if (!isRecord(payload) || !isPositiveInt(payload.sid) || !isRecord(payload.question)) {
    return { ok: false, message: invalid };
  }
  const question = payload.question;
  if (typeof question.text !== "string" || question.text.trim().length === 0) {
    return { ok: false, message: invalid };
  }
  if (!isQuestionSeq(question.seq)) {
    return { ok: false, message: invalid };
  }
  if (!isAudioUrl(question.audio_url)) {
    return { ok: false, message: invalid };
  }
  return {
    ok: true,
    value: {
      sid: payload.sid,
      question: {
        text: question.text,
        audioUrl: question.audio_url,
        seq: question.seq,
      },
    },
  };
}

function isAudioUrl(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length > 0);
}

function isQuestionSeq(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= TOTAL_QUESTIONS;
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
