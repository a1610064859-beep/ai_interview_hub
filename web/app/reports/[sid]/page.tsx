"use client";

import * as echarts from "echarts";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppTheme } from "../../../components/theme-provider";

import {
  buildGrowthHref,
  loadInterviewIdentity,
  parseIdentityFromSearchParams,
} from "../../../lib/growth-data";
import {
  DIMENSION_LABEL_MAP,
  REQUIRED_DIMENSIONS,
  isTextModeReport,
  overallGrade,
  parseReportResponse,
  radarDegradeBadge,
  reportModeHint,
  transformDimensionsToRadar,
  type DimensionKey,
  type ReportData,
} from "../../../lib/report-data";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; report: ReportData }
  | { kind: "param_error"; message: string }
  | { kind: "error"; title: string; message: string; code: string | null; canRetry: boolean };

function parseSid(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1) return null;
  return n;
}

async function readApiError(response: Response): Promise<{ code: string | null; message: string | null }> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof (payload as { detail: unknown }).detail === "object" &&
      (payload as { detail: unknown }).detail !== null
    ) {
      const detail = (payload as { detail: Record<string, unknown> }).detail;
      return {
        code: typeof detail.code === "string" ? detail.code : null,
        message: typeof detail.message === "string" ? detail.message : null,
      };
    }
  } catch {
    // ignore
  }
  return { code: null, message: null };
}

function ReportPageInner({ params }: { params: Promise<{ sid: string }> }) {
  const { sid: sidRaw } = use(params);
  const sid = parseSid(sidRaw);
  const searchParams = useSearchParams();
  const growthHref = useMemo(() => {
    const fromQuery = parseIdentityFromSearchParams((key) => searchParams.get(key));
    const identity = fromQuery ?? loadInterviewIdentity();
    if (!identity) {
      return "/growth";
    }
    return buildGrowthHref(identity.userId, identity.jobId);
  }, [searchParams]);
  const [state, setState] = useState<LoadState>(() =>
    sid === null
      ? { kind: "param_error", message: "无效的报告访问地址，参数格式不合规" }
      : { kind: "loading" },
  );
  const [reloadToken, setReloadToken] = useState(0);

  const load = useCallback(async () => {
    if (sid === null) {
      setState({ kind: "param_error", message: "无效的报告访问地址，参数格式不合规" });
      return;
    }
    setState({ kind: "loading" });
    let response: Response;
    try {
      response = await fetch(`/api/reports/${sid}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
    } catch {
      setState({
        kind: "error",
        title: "座舱通信链路中断",
        message: "网络失败，请检查服务连通性后重试。",
        code: null,
        canRetry: true,
      });
      return;
    }

    if (!response.ok) {
      const info = await readApiError(response);
      if (info.code === "SESSION_NOT_FOUND") {
        setState({
          kind: "error",
          title: "会话记录不存在",
          message: info.message ?? `会话记录不存在或已被重置 (#${sid})`,
          code: info.code,
          canRetry: false,
        });
        return;
      }
      if (info.code === "REPORT_NOT_FOUND") {
        setState({
          kind: "error",
          title: "报告尚未生成",
          message: info.message ?? `报告尚未生成 (#${sid})`,
          code: info.code,
          canRetry: true,
        });
        return;
      }
      setState({
        kind: "error",
        title: "报告加载失败",
        message: `HTTP ${response.status}${info.code ? `，${info.code}` : ""}${info.message ? `：${info.message}` : ""}`,
        code: info.code,
        canRetry: true,
      });
      return;
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      setState({
        kind: "error",
        title: "响应格式错误",
        message: "报告响应不是合法 JSON。",
        code: null,
        canRetry: true,
      });
      return;
    }

    try {
      const report = parseReportResponse(payload);
      setState({ kind: "ready", report });
    } catch (error) {
      setState({
        kind: "error",
        title: "响应格式错误",
        message: error instanceof Error ? error.message : "报告响应字段校验失败。",
        code: null,
        canRetry: true,
      });
    }
  }, [sid]);

  useEffect(() => {
    void load();
  }, [load, reloadToken]);

  return (
    <main className="cabin-shell mx-auto min-h-dvh w-full max-w-7xl overflow-x-hidden px-3 py-4 sm:px-6 sm:py-6">
      {state.kind === "loading" ? (
        <section className="cabin-panel flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8" role="status">
          <div className="cabin-pulse h-16 w-16 rounded-full border border-cyan-400/40" />
          <p className="text-sm text-slate-300">智驾面试仓正在解析考官双评证据与指标...</p>
        </section>
      ) : null}

      {state.kind === "param_error" ? (
        <ErrorPanel title="参数错误" message={state.message} canRetry={false} onRetry={null} />
      ) : null}

      {state.kind === "error" ? (
        <ErrorPanel
          title={state.title}
          message={state.message}
          canRetry={state.canRetry}
          code={state.code}
          onRetry={
            state.canRetry
              ? () => {
                  setReloadToken((n) => n + 1);
                }
              : null
          }
        />
      ) : null}

      {state.kind === "ready" ? (
        <ReportView report={state.report} growthHref={growthHref} />
      ) : null}
    </main>
  );
}

export default function ReportPage({ params }: { params: Promise<{ sid: string }> }) {
  return (
    <Suspense
      fallback={
        <main className="cabin-shell mx-auto min-h-dvh w-full max-w-7xl overflow-x-hidden px-3 py-4 sm:px-6 sm:py-6">
          <section className="cabin-panel flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8" role="status">
            <div className="cabin-pulse h-16 w-16 rounded-full border border-cyan-400/40" />
            <p className="text-sm text-slate-300">正在加载报告页…</p>
          </section>
        </main>
      }
    >
      <ReportPageInner params={params} />
    </Suspense>
  );
}

function ErrorPanel({
  title,
  message,
  canRetry,
  onRetry,
  code,
}: {
  title: string;
  message: string;
  canRetry: boolean;
  onRetry: (() => void) | null;
  code?: string | null;
}) {
  const isReportMissing = code === "REPORT_NOT_FOUND";
  return (
    <section className="cabin-panel border-orange-500/40 p-4 sm:p-6" role="alert">
      <h1 className="text-xl text-orange-300">{title}</h1>
      <p className="mt-3 break-anywhere text-sm leading-6 text-slate-300">{message}</p>
      <div className="mt-6 flex flex-wrap gap-3">
        {canRetry && onRetry ? (
          <button
            type="button"
            className="rounded-full border border-cyan-400/50 bg-cyan-500/20 px-4 py-2 text-sm text-cyan-100"
            onClick={onRetry}
          >
            {isReportMissing ? "刷新报告" : "重试加载"}
          </button>
        ) : null}
        <Link
          href="/"
          className="rounded-full border border-slate-500/50 bg-slate-800/80 px-4 py-2 text-sm text-slate-100"
        >
          返回首页
        </Link>
      </div>
    </section>
  );
}

function ReportView({
  report,
  growthHref,
}: {
  report: ReportData;
  growthHref: string;
}) {
  const { theme } = useAppTheme();
  const radar = useMemo(() => transformDimensionsToRadar(report.dimensions, theme), [report.dimensions, theme]);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!radar.canRenderRadar || !radar.radarOptions || !chartRef.current) {
      if (instanceRef.current) {
        instanceRef.current.dispose();
        instanceRef.current = null;
      }
      return;
    }

    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    }
    instanceRef.current.setOption({ ...radar.radarOptions, animation: false }, true);

    const observer = new ResizeObserver(() => instanceRef.current?.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [radar]);

  const overallText = report.overall === null ? "--" : report.overall.toFixed(1);
  const ringPct = report.overall === null ? 0 : Math.max(0, Math.min(100, report.overall));
  const isTextMode = isTextModeReport(report.dimensions);
  const modeHint = reportModeHint(isTextMode);
  const degradeBadge = radarDegradeBadge(radar.validCount, isTextMode);

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <header className="cabin-panel flex min-w-0 flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0">
          <p className="text-xs tracking-[0.2em] text-cyan-300/80">智驾未来 · 面试仓</p>
          <h1 className="mt-1 break-anywhere text-2xl text-slate-50">
            {report.job_title}
            <span className="ml-2 text-base font-normal text-slate-400">· 模拟面试能力评估</span>
          </h1>
          <p className="mt-2 text-xs text-slate-400">
            会话编号 #{report.session_id} · 报告编号 #{report.id} · {modeHint}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/"
            className="rounded-full border border-cyan-400/40 bg-cyan-500/15 px-4 py-2 text-sm text-cyan-100"
          >
            再次训练
          </Link>
          <Link
            href={growthHref}
            className="rounded-full border border-slate-500/50 bg-slate-800/80 px-4 py-2 text-sm text-slate-200"
          >
            查看成长记录
          </Link>
        </div>
      </header>

      <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-10">
        <div className="cabin-panel cabin-glow min-w-0 p-4 sm:p-6 lg:col-span-4">
          <p className="text-sm text-slate-400">综合评定</p>
          <div className="mt-4 flex items-center gap-6">
            <OverallRing percent={ringPct} label={overallText} />
            <div>
              <p className="text-3xl font-semibold text-slate-50">{overallGrade(report.overall)}</p>
              <p className="mt-2 max-w-xs text-sm leading-6 text-slate-400">
                {report.overall === null
                  ? "当前有效评估不足，综合分待评。"
                  : "基于有效维度等权均值的可解释综合分。"}
              </p>
            </div>
          </div>
        </div>

        <div className="cabin-panel cabin-glow min-w-0 p-4 sm:p-6 lg:col-span-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-lg text-slate-50">多维能力雷达舱</h2>
            {degradeBadge ? (
              <span className="rounded-full border border-orange-400/40 px-2 py-1 text-xs text-orange-300">
                {degradeBadge}
              </span>
            ) : null}
          </div>
          {radar.canRenderRadar ? (
            <div ref={chartRef} className="h-[260px] w-full min-w-0 max-w-full sm:h-[320px]" />
          ) : (
            <LinearGauges report={report} />
          )}
        </div>
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
        {REQUIRED_DIMENSIONS.map((key) => (
          <DimensionCard
            key={key}
            dimKey={key}
            data={report.dimensions[key]}
            isTextMode={isTextMode}
          />
        ))}
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
        <InsightList
          title="优势亮点"
          empty="未检测到突出亮点"
          items={report.highlights}
          tone="emerald"
        />
        <InsightList
          title="需关注点"
          empty="暂无显著能力顾虑"
          items={report.concerns}
          tone="orange"
        />
        <InsightList
          title="针对性能力提升路线"
          empty="暂无建议，保持当前水平"
          items={report.improvement}
          tone="cyan"
          numbered
        />
      </section>
    </div>
  );
}

function OverallRing({ percent, label }: { percent: number; label: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - percent / 100);
  return (
    <div className="relative h-[112px] w-[112px] shrink-0 sm:h-[140px] sm:w-[140px]">
      <svg viewBox="0 0 140 140" className="h-full w-full -rotate-90">
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(51,65,85,0.7)" strokeWidth="10" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="#06B6D4"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="drop-shadow-[0_0_8px_rgba(6,182,212,0.55)]"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center rotate-0">
        <span className="text-3xl font-semibold text-slate-50">{label}</span>
      </div>
    </div>
  );
}

function LinearGauges({ report }: { report: ReportData }) {
  return (
    <div className="space-y-4" role="status">
      <p className="rounded-xl border border-dashed border-slate-600 px-3 py-2 text-sm text-slate-400">
        座舱雷达校准中 · 有效维度不足 3 项 · 已切换为线性仪表对比态
      </p>
      {REQUIRED_DIMENSIONS.map((key) => {
        const dim = report.dimensions[key];
        const valid = typeof dim.score === "number";
        return (
          <div key={key}>
            <div className="mb-1 flex justify-between text-sm">
              <span className="text-slate-300">{DIMENSION_LABEL_MAP[key]}</span>
              <span className="text-slate-400">
                {valid ? `${dim.score!.toFixed(1)}` : "未评估"}
              </span>
            </div>
            <div
              className={`h-2 overflow-hidden rounded-full ${valid ? "bg-slate-800" : "border border-dashed border-slate-600 bg-transparent"}`}
            >
              {valid ? (
                <div
                  className="h-full rounded-full bg-cyan-400"
                  style={{ width: `${Math.max(0, Math.min(100, dim.score!))}%` }}
                />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DimensionCard({
  dimKey,
  data,
  isTextMode,
}: {
  dimKey: DimensionKey;
  data: ReportData["dimensions"][DimensionKey];
  isTextMode: boolean;
}) {
  const scored = typeof data.score === "number";
  return (
    <article className="cabin-panel cabin-glow min-w-0 p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg text-slate-50">{DIMENSION_LABEL_MAP[dimKey]}</h3>
        {scored ? (
          <span className="text-cyan-300">{data.score!.toFixed(1)} 分</span>
        ) : (
          <span className="rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-400">未评估</span>
        )}
      </div>
      {scored ? (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-cyan-400/90"
            style={{ width: `${Math.max(0, Math.min(100, data.score!))}%` }}
          />
        </div>
      ) : null}
      {data.evidence !== null ? (
        <blockquote className="evidence-chip mt-4 whitespace-pre break-anywhere text-sm text-cyan-100">
          <span className="mr-2 text-xs text-cyan-300/80">[考官引用]</span>
          “{data.evidence}”
        </blockquote>
      ) : (
        <p className="mt-4 text-sm text-slate-500">本维度无直接字面引用</p>
      )}
      <p className="mt-3 text-sm leading-6 text-slate-400">{data.reason}</p>
      {dimKey === "expression_fluency" && isTextMode ? (
        <p className="mt-3 text-xs text-slate-500">
          语音闭环版本（M2）将接入语速、停顿与填充词声学量化分析
        </p>
      ) : null}
    </article>
  );
}

function InsightList({
  title,
  empty,
  items,
  tone,
  numbered = false,
}: {
  title: string;
  empty: string;
  items: string[];
  tone: "emerald" | "orange" | "cyan";
  numbered?: boolean;
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
      : tone === "orange"
        ? "border-orange-500/30 bg-orange-950/20 text-orange-200"
        : "border-cyan-500/30 bg-cyan-950/20 text-cyan-100";
  return (
    <section className={`cabin-panel min-w-0 p-5 ${toneClass}`}>
      <h3 className="text-base text-slate-50">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-slate-400">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm leading-6">
          {items.map((item, index) => (
            <li key={`${index}-${item}`} className="break-anywhere">
              {numbered ? (
                <span className="mr-2 text-xs text-cyan-300">
                  {String(index + 1).padStart(2, "0")}.
                </span>
              ) : (
                <span className="mr-2">•</span>
              )}
              {item}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
