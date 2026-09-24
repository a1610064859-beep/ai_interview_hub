"use client";

import * as echarts from "echarts";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildGrowthHref,
  buildReportHref,
  comparisonReasonLabel,
  formatDeltaOrUnevaluated,
  formatScoreOrUnevaluated,
  inputModeLabel,
  loadInterviewIdentity,
  parseGrowthHistoryResponse,
  parseGrowthTrendResponse,
  parseStudentsResponse,
  persistInterviewIdentity,
  transformTrendToLineOptions,
  type GrowthHistoryData,
  type GrowthTrendData,
  type StudentProfile,
} from "../../lib/growth-data";
import { DIMENSION_LABEL_MAP, REQUIRED_DIMENSIONS } from "../../lib/report-data";

type JobOption = { id: number; family: string; title: string };

type PageState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      students: StudentProfile[];
      jobs: JobOption[];
    };

function parsePositiveInt(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : null;
}

async function readApiError(response: Response): Promise<string> {
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
      const code = typeof detail.code === "string" ? detail.code : null;
      const message = typeof detail.message === "string" ? detail.message : null;
      if (code || message) {
        return `${code ?? "ERROR"}${message ? `：${message}` : ""}`;
      }
    }
  } catch {
    // ignore
  }
  return `HTTP ${response.status}`;
}

function GrowthPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [bootstrap, setBootstrap] = useState<PageState>({ kind: "loading" });
  const [userId, setUserId] = useState<number | null>(() => parsePositiveInt(searchParams.get("user_id")));
  const [jobId, setJobId] = useState<number | null>(() => parsePositiveInt(searchParams.get("job_id")));
  const [history, setHistory] = useState<GrowthHistoryData | null>(null);
  const [trend, setTrend] = useState<GrowthTrendData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [studentsRes, jobsRes] = await Promise.all([
          fetch("/api/students", { headers: { Accept: "application/json" }, cache: "no-store" }),
          fetch("/api/jobs", { headers: { Accept: "application/json" }, cache: "no-store" }),
        ]);
        if (!alive) return;
        if (!studentsRes.ok) {
          setBootstrap({ kind: "error", message: await readApiError(studentsRes) });
          return;
        }
        if (!jobsRes.ok) {
          setBootstrap({ kind: "error", message: await readApiError(jobsRes) });
          return;
        }
        const studentsJson: unknown = await studentsRes.json();
        const jobsJson: unknown = await jobsRes.json();
        const students = parseStudentsResponse(studentsJson);
        if (
          typeof jobsJson !== "object" ||
          jobsJson === null ||
          !Array.isArray((jobsJson as { jobs?: unknown }).jobs)
        ) {
          throw new Error("岗位列表响应非法");
        }
        const jobs: JobOption[] = [];
        for (const item of (jobsJson as { jobs: unknown[] }).jobs) {
          if (typeof item !== "object" || item === null) throw new Error("岗位项非法");
          const row = item as Record<string, unknown>;
          if (typeof row.id !== "number" || typeof row.family !== "string" || typeof row.title !== "string") {
            throw new Error("岗位字段非法");
          }
          jobs.push({ id: row.id, family: row.family, title: row.title });
        }
        const stored = loadInterviewIdentity();
        setBootstrap({ kind: "ready", students, jobs });
        setUserId((prev) => {
          if (prev !== null) return prev;
          if (stored && students.some((s) => s.id === stored.userId)) return stored.userId;
          return students[0]?.id ?? null;
        });
        setJobId((prev) => {
          if (prev !== null) return prev;
          if (stored && jobs.some((j) => j.id === stored.jobId)) return stored.jobId;
          return jobs[0]?.id ?? null;
        });
      } catch (err) {
        if (!alive) return;
        setBootstrap({
          kind: "error",
          message: err instanceof Error ? err.message : "成长页初始化失败",
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const reloadGrowth = useCallback(async () => {
    if (userId === null) {
      setHistory(null);
      setTrend(null);
      setLoadError("请先选择学生档案");
      return;
    }
    setLoadingData(true);
    setLoadError(null);
    try {
      const historyUrl =
        jobId === null
          ? `/api/growth/${userId}/history`
          : `/api/growth/${userId}/history?job_id=${jobId}`;
      const historyRes = await fetch(historyUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!historyRes.ok) {
        throw new Error(await readApiError(historyRes));
      }
      const historyData = parseGrowthHistoryResponse(await historyRes.json());
      setHistory(historyData);

      if (jobId === null) {
        setTrend(null);
      } else {
        const trendRes = await fetch(`/api/growth/${userId}/trend?job_id=${jobId}`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (!trendRes.ok) {
          throw new Error(await readApiError(trendRes));
        }
        setTrend(parseGrowthTrendResponse(await trendRes.json()));
      }
      if (jobId !== null) {
        persistInterviewIdentity({ userId, jobId });
      }
      router.replace(buildGrowthHref(userId, jobId));
    } catch (err) {
      setHistory(null);
      setTrend(null);
      setLoadError(err instanceof Error ? err.message : "成长数据加载失败");
    } finally {
      setLoadingData(false);
    }
  }, [userId, jobId, router]);

  useEffect(() => {
    if (bootstrap.kind !== "ready") return;
    void reloadGrowth();
  }, [bootstrap.kind, reloadGrowth]);

  const chartOptions = useMemo(() => {
    if (!trend || trend.points.length === 0) return null;
    return transformTrendToLineOptions(trend, history?.records ?? []);
  }, [trend, history]);

  useEffect(() => {
    if (!chartRef.current || !chartOptions) {
      chartInstance.current?.dispose();
      chartInstance.current = null;
      return;
    }
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }
    const { _meta: _ignored, ...options } = chartOptions;
    chartInstance.current.setOption({ ...options, animation: false }, true);
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
    };
  }, [chartOptions]);

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  if (bootstrap.kind === "loading") {
    return <StatusCard title="正在加载成长舱…" />;
  }
  if (bootstrap.kind === "error") {
    return <StatusCard title="成长舱初始化失败" detail={bootstrap.message} />;
  }

  const selectedStudent = bootstrap.students.find((s) => s.id === userId) ?? null;
  const recordCount = history?.records.length ?? 0;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <header className="cabin-panel flex min-w-0 flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0">
          <p className="text-xs tracking-[0.2em] text-cyan-300/80">智驾未来 · 面试仓</p>
          <h1 className="mt-1 text-2xl text-slate-50">成长追踪</h1>
          <p className="mt-2 text-xs text-slate-400">
            同一学生、同一岗位的训练历史与可比变化（模型评分观测）
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/"
            className="rounded-full border border-cyan-400/40 bg-cyan-500/15 px-4 py-2 text-sm text-cyan-100"
          >
            再次训练
          </Link>
        </div>
      </header>

      <section className="cabin-panel grid min-w-0 gap-4 p-4 md:grid-cols-2">
        <label className="flex min-w-0 flex-col gap-2 text-sm text-slate-300">
          学生档案
          <select
            className="rounded-xl border border-cyan-400/30 bg-slate-950 px-3 py-2 text-slate-100"
            value={userId ?? ""}
            onChange={(e) => {
              const next = parsePositiveInt(e.target.value);
              setUserId(next);
            }}
          >
            {bootstrap.students.length === 0 ? <option value="">暂无学生档案</option> : null}
            {bootstrap.students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nameMasked} · {s.major ?? "专业未填"} · {s.grade ?? "年级未填"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-2 text-sm text-slate-300">
          岗位筛选
          <select
            className="rounded-xl border border-cyan-400/30 bg-slate-950 px-3 py-2 text-slate-100"
            value={jobId ?? ""}
            onChange={(e) => {
              const raw = e.target.value;
              setJobId(raw === "" ? null : parsePositiveInt(raw));
            }}
          >
            <option value="">全部岗位（仅历史）</option>
            {bootstrap.jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.family} · {j.title}
              </option>
            ))}
          </select>
        </label>
      </section>

      {selectedStudent ? (
        <p className="text-sm text-slate-400">
          当前学生：{selectedStudent.nameMasked}
          {loadingData ? " · 加载中…" : null}
        </p>
      ) : null}

      {loadError ? (
        <div className="cabin-panel border border-orange-400/40 p-4 text-sm text-orange-200" role="alert">
          {loadError}
        </div>
      ) : null}

      {history && recordCount === 0 ? (
        <StatusCard title="暂无训练记录" detail="该学生在所选范围内尚无已完成且已生成报告的训练。请先去面试舱完成一场训练。" />
      ) : null}

      {trend ? (
        <section className="cabin-panel cabin-glow flex min-w-0 flex-col gap-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg text-slate-50">{trend.jobTitle} · 趋势</h2>
            <span className="rounded-full border border-slate-500/50 px-3 py-1 text-xs text-slate-300">
              输入口径：{inputModeLabel(trend.inputMode)} · 共 {trend.sessionsCount} 次
            </span>
          </div>

          {trend.sessionsCount === 1 ? (
            <p className="text-sm text-slate-400">仅一次训练，显示记录但不计算增减。</p>
          ) : null}

          {trend.inputMode === "mixed" ? (
            <p className="rounded-xl border border-orange-400/40 bg-orange-500/10 px-3 py-2 text-sm text-orange-100">
              文本与语音口径混合：总体分不直接比较；同版本、两次均有效的单项维度可连线比较。
            </p>
          ) : null}

          <div className="rounded-xl border border-cyan-400/20 bg-slate-950/60 p-4">
            <p className="text-sm text-slate-400">最近两次可比变化</p>
            <p className="mt-2 text-xl text-slate-50">
              {formatDeltaOrUnevaluated(
                trend.overallComparison.delta,
                trend.overallComparison.comparable,
              )}
            </p>
            {!trend.overallComparison.comparable ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-orange-200">
                {trend.overallComparison.reasons.map((code) => (
                  <li key={code}>{comparisonReasonLabel(code)}</li>
                ))}
              </ul>
            ) : null}
            {trend.overallComparison.message ? (
              <p className="mt-2 text-sm text-slate-400">{trend.overallComparison.message}</p>
            ) : null}
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {REQUIRED_DIMENSIONS.map((key) => {
                const change = trend.dimensionChanges[key];
                return (
                  <div key={key} className="rounded-lg border border-slate-700/80 px-3 py-2 text-sm">
                    <p className="text-slate-400">{DIMENSION_LABEL_MAP[key]}</p>
                    <p className="mt-1 text-slate-100">
                      {change === null
                        ? "未评估"
                        : `${formatScoreOrUnevaluated(change.previous)} → ${formatScoreOrUnevaluated(change.current)}（${change.delta >= 0 ? "+" : ""}${change.delta.toFixed(1)}）`}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {trend.points.length >= 1 ? (
            <div ref={chartRef} className="h-[280px] w-full min-w-0 max-w-full sm:h-[360px]" />
          ) : null}
        </section>
      ) : null}

      {history && recordCount > 0 ? (
        <section className="cabin-panel flex min-w-0 flex-col gap-3 p-4">
          <h2 className="text-lg text-slate-50">训练历史</h2>
          <ul className="flex flex-col gap-3">
            {history.records.map((rec) => (
              <li
                key={rec.sessionId}
                className="rounded-xl border border-cyan-400/20 bg-slate-950/50 p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-base text-slate-50">
                      {rec.jobTitle}
                      <span className="ml-2 text-sm text-slate-400">
                        会话 #{rec.sessionId} · 报告 #{rec.reportId}
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {rec.startedAt} · {rec.mode} · {inputModeLabel(rec.inputMode)} · 评分
                      {rec.scoringVersion ?? "未标识"}
                    </p>
                    <p className="mt-2 text-sm text-slate-200">
                      综合分：{formatScoreOrUnevaluated(rec.overall)}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-300">
                      {REQUIRED_DIMENSIONS.map((key) => (
                        <span
                          key={key}
                          className="rounded-full border border-slate-600 px-2 py-1"
                        >
                          {DIMENSION_LABEL_MAP[key]} {formatScoreOrUnevaluated(rec.dimensions[key])}
                        </span>
                      ))}
                    </div>
                    {rec.improvement.length > 0 ? (
                      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
                        {rec.improvement.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-3 text-sm text-slate-500">本场无改进建议原文</p>
                    )}
                  </div>
                  <Link
                    href={
                      userId !== null
                        ? buildReportHref(rec.sessionId, userId, rec.jobId)
                        : `/reports/${rec.sessionId}`
                    }
                    className="rounded-full border border-cyan-400/40 bg-cyan-500/15 px-4 py-2 text-sm text-cyan-100"
                  >
                    打开原报告
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function StatusCard({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="cabin-panel p-4 sm:p-6">
      <h2 className="text-lg text-slate-50">{title}</h2>
      {detail ? <p className="mt-2 text-sm text-slate-400">{detail}</p> : null}
      <Link href="/" className="mt-4 inline-block text-sm text-cyan-300 underline">
        返回面试舱再次训练
      </Link>
    </div>
  );
}

export default function GrowthPage() {
  return (
    <main className="cabin-shell mx-auto min-h-dvh w-full max-w-6xl px-3 py-5 sm:px-4 sm:py-8">
      <Suspense fallback={<StatusCard title="正在加载成长舱…" />}>
        <GrowthPageInner />
      </Suspense>
    </main>
  );
}
