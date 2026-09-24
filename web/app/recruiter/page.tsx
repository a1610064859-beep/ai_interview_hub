"use client";

import * as echarts from "echarts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DIMENSION_LABEL_MAP,
  REQUIRED_DIMENSIONS,
  transformDimensionsToRadar,
  type DimensionData,
  type DimensionKey,
} from "../../lib/report-data";

type JobOption = { id: number; family: string; title: string; jdDigest: string };

type Cohort = { input_mode: "text" | "voice"; scoring_version: string };

type Candidate = {
  user_id: number;
  name_masked: string | null;
  major: string | null;
  grade: string | null;
  session_id: number;
  report_id: number;
  job_id: number;
  input_mode: string;
  scoring_version: string;
  trained_at: string | null;
  overall: number | null;
  weighted_score: number | null;
  valid_dim_count: number;
  dimensions: Record<DimensionKey, DimensionData>;
  report_path: string;
};

type CandidatesPayload = {
  job_id: number;
  job_title: string;
  cohort: Cohort | null;
  available_cohorts: Cohort[];
  weights: Record<string, unknown> | null;
  weights_error: string | null;
  eligibility: string;
  candidates: Candidate[];
};

type ParseDraft = {
  job_id: number;
  job_id_source: string;
  applied: boolean;
  dims: string[];
  questions: { type: string; text: string }[];
  terms: string[];
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function cohortKey(c: Cohort): string {
  return `${c.input_mode}|${c.scoring_version}`;
}

function cohortLabel(c: Cohort): string {
  const mode = c.input_mode === "text" ? "文本" : "语音";
  return `${mode} · ${c.scoring_version}`;
}

function formatScore(v: number | null | undefined): string {
  if (v === null || v === undefined) return "未评估";
  return v.toFixed(1);
}

async function readApiError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && isRecord(payload.detail)) {
      const code = typeof payload.detail.code === "string" ? payload.detail.code : null;
      const message =
        typeof payload.detail.message === "string" ? payload.detail.message : null;
      if (code || message) return `${code ?? "ERROR"}${message ? `：${message}` : ""}`;
    }
  } catch {
    // ignore
  }
  return `HTTP ${response.status}`;
}

function parseJobs(payload: unknown): JobOption[] {
  if (!isRecord(payload) || !Array.isArray(payload.jobs)) {
    throw new Error("岗位列表格式不正确");
  }
  return payload.jobs.map((item, idx) => {
    if (!isRecord(item) || typeof item.id !== "number" || item.id < 1) {
      throw new Error(`岗位[${idx}] id 非法`);
    }
    if (
      typeof item.family !== "string" ||
      typeof item.title !== "string" ||
      typeof item.jd_digest !== "string"
    ) {
      throw new Error(`岗位[${idx}] 字段不完整`);
    }
    return {
      id: item.id,
      family: item.family,
      title: item.title,
      jdDigest: item.jd_digest,
    };
  });
}

function parseCandidatesPayload(payload: unknown): CandidatesPayload {
  if (!isRecord(payload)) throw new Error("候选响应格式不正确");
  if (typeof payload.job_id !== "number") throw new Error("job_id 非法");
  if (typeof payload.job_title !== "string") throw new Error("job_title 非法");
  if (!Array.isArray(payload.available_cohorts)) throw new Error("available_cohorts 非法");
  if (!Array.isArray(payload.candidates)) throw new Error("candidates 非法");

  const available_cohorts: Cohort[] = payload.available_cohorts.map((c, i) => {
    if (!isRecord(c)) throw new Error(`cohort[${i}] 非法`);
    if (c.input_mode !== "text" && c.input_mode !== "voice") {
      throw new Error(`cohort[${i}].input_mode 非法`);
    }
    if (typeof c.scoring_version !== "string" || !c.scoring_version) {
      throw new Error(`cohort[${i}].scoring_version 非法`);
    }
    return { input_mode: c.input_mode, scoring_version: c.scoring_version };
  });

  const candidates: Candidate[] = payload.candidates.map((raw, i) => {
    if (!isRecord(raw)) throw new Error(`candidate[${i}] 非法`);
    const dimsRaw = raw.dimensions;
    if (!isRecord(dimsRaw)) throw new Error(`candidate[${i}].dimensions 非法`);
    const dimensions = {} as Record<DimensionKey, DimensionData>;
    for (const key of REQUIRED_DIMENSIONS) {
      const cell = dimsRaw[key];
      if (!isRecord(cell)) throw new Error(`candidate[${i}].${key} 非法`);
      const score = cell.score;
      if (!(score === null || (typeof score === "number" && Number.isFinite(score)))) {
        throw new Error(`candidate[${i}].${key}.score 非法`);
      }
      dimensions[key] = {
        score,
        evidence: typeof cell.evidence === "string" ? cell.evidence : null,
        reason: typeof cell.reason === "string" ? cell.reason : "",
      };
    }
    return {
      user_id: Number(raw.user_id),
      name_masked: typeof raw.name_masked === "string" ? raw.name_masked : null,
      major: typeof raw.major === "string" ? raw.major : null,
      grade: typeof raw.grade === "string" ? raw.grade : null,
      session_id: Number(raw.session_id),
      report_id: Number(raw.report_id),
      job_id: Number(raw.job_id),
      input_mode: String(raw.input_mode),
      scoring_version: String(raw.scoring_version),
      trained_at: typeof raw.trained_at === "string" ? raw.trained_at : null,
      overall: typeof raw.overall === "number" ? raw.overall : null,
      weighted_score: typeof raw.weighted_score === "number" ? raw.weighted_score : null,
      valid_dim_count: Number(raw.valid_dim_count),
      dimensions,
      report_path: String(raw.report_path),
    };
  });

  let cohort: Cohort | null = null;
  if (payload.cohort !== null && payload.cohort !== undefined) {
    if (!isRecord(payload.cohort)) throw new Error("cohort 非法");
    if (payload.cohort.input_mode !== "text" && payload.cohort.input_mode !== "voice") {
      throw new Error("cohort.input_mode 非法");
    }
    if (typeof payload.cohort.scoring_version !== "string") {
      throw new Error("cohort.scoring_version 非法");
    }
    cohort = {
      input_mode: payload.cohort.input_mode,
      scoring_version: payload.cohort.scoring_version,
    };
  }

  return {
    job_id: payload.job_id,
    job_title: payload.job_title,
    cohort,
    available_cohorts,
    weights: isRecord(payload.weights) ? payload.weights : null,
    weights_error: typeof payload.weights_error === "string" ? payload.weights_error : null,
    eligibility: typeof payload.eligibility === "string" ? payload.eligibility : "",
    candidates,
  };
}

export default function RecruiterPage() {
  const [jobs, setJobs] = useState<JobOption[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [discover, setDiscover] = useState<CandidatesPayload | null>(null);
  const [selectedCohortKey, setSelectedCohortKey] = useState<string>("");
  const [list, setList] = useState<CandidatesPayload | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [jdText, setJdText] = useState("");
  const [parseDraft, setParseDraft] = useState<ParseDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/jobs");
        if (!resp.ok) throw new Error(await readApiError(resp));
        const parsed = parseJobs(await resp.json());
        if (cancelled) return;
        setJobs(parsed);
        if (parsed[0]) setJobId(parsed[0].id);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载岗位失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadDiscover = useCallback(async (jid: number) => {
    setBusy(true);
    setError(null);
    setList(null);
    setSelectedCohortKey("");
    setSelectedUserId(null);
    try {
      const resp = await fetch(`/api/recruiter/candidates?job_id=${jid}`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      const payload = parseCandidatesPayload(await resp.json());
      setDiscover(payload);
    } catch (e) {
      setDiscover(null);
      setError(e instanceof Error ? e.message : "发现 cohort 失败");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (jobId !== null) void loadDiscover(jobId);
  }, [jobId, loadDiscover]);

  const loadCandidates = useCallback(async () => {
    if (jobId === null || !selectedCohortKey) return;
    const [input_mode, scoring_version] = selectedCohortKey.split("|");
    if (input_mode !== "text" && input_mode !== "voice") return;
    setBusy(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        job_id: String(jobId),
        input_mode,
        scoring_version,
      });
      const resp = await fetch(`/api/recruiter/candidates?${qs.toString()}`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      const payload = parseCandidatesPayload(await resp.json());
      setList(payload);
      setSelectedUserId(payload.candidates[0]?.user_id ?? null);
    } catch (e) {
      setList(null);
      setError(e instanceof Error ? e.message : "加载候选失败");
    } finally {
      setBusy(false);
    }
  }, [jobId, selectedCohortKey]);

  useEffect(() => {
    if (selectedCohortKey) void loadCandidates();
  }, [selectedCohortKey, loadCandidates]);

  const selected = useMemo(() => {
    if (!list) return null;
    return list.candidates.find((c) => c.user_id === selectedUserId) ?? null;
  }, [list, selectedUserId]);

  useEffect(() => {
    if (!selected || !chartRef.current) {
      chartInstance.current?.dispose();
      chartInstance.current = null;
      return;
    }
    const chartElement = chartRef.current;
    const radar = transformDimensionsToRadar(selected.dimensions);
    if (!radar.canRenderRadar || !radar.radarOptions) {
      chartInstance.current?.clear();
      return;
    }
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    }
    chartInstance.current.setOption({ ...radar.radarOptions, animation: false }, true);
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartElement);
    return () => observer.disconnect();
  }, [selected]);

  async function runParse() {
    if (jobId === null) return;
    setBusy(true);
    setError(null);
    setParseDraft(null);
    try {
      const resp = await fetch("/api/jobs/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, jd_text: jdText }),
      });
      if (!resp.ok) throw new Error(await readApiError(resp));
      const raw: unknown = await resp.json();
      if (!isRecord(raw)) throw new Error("解析响应非法");
      setParseDraft({
        job_id: Number(raw.job_id),
        job_id_source: String(raw.job_id_source),
        applied: Boolean(raw.applied),
        dims: Array.isArray(raw.dims) ? raw.dims.map(String) : [],
        questions: Array.isArray(raw.questions)
          ? raw.questions.map((q) => {
              if (!isRecord(q)) return { type: "?", text: "" };
              return { type: String(q.type), text: String(q.text) };
            })
          : [],
        terms: Array.isArray(raw.terms) ? raw.terms.map(String) : [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "JD 解析失败");
    } finally {
      setBusy(false);
    }
  }

  const emptyHint = (() => {
    if (discover?.weights_error) {
      return `权重配置非法（${discover.weights_error}）：请检查岗位 dims_json，禁止使用内置兜底权重。`;
    }
    if (!discover) return "正在发现可用评分口径…";
    if (discover.available_cohorts.length === 0) {
      return "该岗位暂无可用评分口径（无已完成且含 input_mode/scoring_version 的训练）。";
    }
    if (!selectedCohortKey) return "请先显式选择评分口径（cohort），不会自动混排。";
    if (list && list.candidates.length === 0) {
      return "当前口径下暂无合格候选（需 valid_dim_count≥3；legacy 不入选）。";
    }
    return null;
  })();

  return (
    <main className="min-h-dvh bg-[#050912] px-3 py-4 text-[#d7e3f7] sm:px-6 sm:py-6 lg:px-8">
      <header className="mb-6 flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs tracking-[0.2em] text-[#7eb6ff]">RECRUITER · 同源候选</p>
          <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">企业初筛看板</h1>
          <p className="mt-2 max-w-2xl text-sm text-[#9fb4d4]">
            候选仅来自学生端真实 sessions/reports；排序键为岗位 dims_json 企业加权，不等于报告等权 overall。
          </p>
        </div>
        <Link
          href="/"
          className="rounded-full border border-[#2f6fed] px-4 py-2 text-sm text-[#7eb6ff]"
        >
          返回学生端
        </Link>
      </header>

      {error ? (
        <p className="mb-4 rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]" role="alert">
          {error}
        </p>
      ) : null}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(280px,320px)_minmax(0,1fr)_minmax(280px,320px)]">
        <section className="rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <h2 className="text-lg text-white">岗位与 JD 草案</h2>
          <label className="mt-3 flex flex-col gap-2 text-sm text-[#9fb4d4]">
            种子岗位
            <select
              className="rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white"
              value={jobId ?? ""}
              onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : null)}
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.family} · {j.title}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-3 flex flex-col gap-2 text-sm text-[#9fb4d4]">
            粘贴 JD（解析不写库、不扩岗）
            <textarea
              className="min-h-28 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-sm text-white"
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="至少 20 字…"
            />
          </label>
          <button
            type="button"
            disabled={busy || jobId === null || jdText.trim().length < 20}
            className="mt-3 rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:opacity-50"
            onClick={() => void runParse()}
          >
            解析草案
          </button>
          {parseDraft ? (
            <div className="mt-4 space-y-2 text-xs text-[#9fb4d4]">
              <p>
                job_id={parseDraft.job_id} · source={parseDraft.job_id_source} · applied=
                {String(parseDraft.applied)}
              </p>
              <p>dims: {parseDraft.dims.join(" / ")}</p>
              <p>questions: {parseDraft.questions.length} 题（不入库）</p>
              <p>terms: {parseDraft.terms.join("、") || "—"}</p>
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg text-white">候选列表</h2>
            <label className="flex items-center gap-2 text-sm text-[#9fb4d4]">
              评分口径
              <select
                className="rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white"
                value={selectedCohortKey}
                onChange={(e) => setSelectedCohortKey(e.target.value)}
                disabled={!discover || discover.available_cohorts.length === 0}
              >
                <option value="">请选择 cohort</option>
                {(discover?.available_cohorts ?? []).map((c) => (
                  <option key={cohortKey(c)} value={cohortKey(c)}>
                    {cohortLabel(c)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="mb-3 text-xs text-[#7eb6ff]">
            企业加权（岗位 dims_json）· eligibility={discover?.eligibility ?? "—"}
          </p>
          {emptyHint ? (
            <p className="rounded-xl border border-[#2f6fed]/40 bg-[#050912] px-4 py-6 text-sm text-[#9fb4d4]">
              {emptyHint}
            </p>
          ) : (
            <ul className="space-y-3">
              {(list?.candidates ?? []).map((c) => (
                <li key={c.user_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedUserId(c.user_id)}
                    className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                      selectedUserId === c.user_id
                        ? "border-[#ff8a2a] bg-[#1a1208]"
                        : "border-[#2f6fed]/50 bg-[#050912]"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-white">{c.name_masked ?? `学生#${c.user_id}`}</p>
                        <p className="text-xs text-[#9fb4d4]">
                          {c.major ?? "专业未填"} · {c.grade ?? "年级未填"} · sid={c.session_id}
                        </p>
                      </div>
                      <div className="text-right text-sm">
                        <p className="text-[#ffb067]">
                          加权 {formatScore(c.weighted_score)}
                        </p>
                        <p className="text-xs text-[#9fb4d4]">
                          等权 overall {formatScore(c.overall)}
                        </p>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[#9fb4d4]">
                      {REQUIRED_DIMENSIONS.map((k) => (
                        <span key={k} className="rounded-full border border-[#2f6fed]/40 px-2 py-0.5">
                          {DIMENSION_LABEL_MAP[k]} {formatScore(c.dimensions[k].score)}
                        </span>
                      ))}
                    </div>
                    <Link
                      href={c.report_path}
                      className="mt-2 inline-block text-xs text-[#7eb6ff] underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      查看原报告
                    </Link>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <h2 className="text-lg text-white">雷达预览</h2>
          {selected ? (
            <>
              <p className="mt-2 text-sm text-[#9fb4d4]">
                {selected.name_masked} · 有效维 {selected.valid_dim_count}
              </p>
              <div ref={chartRef} className="mt-3 h-56 w-full min-w-0 sm:h-64" />
              <ul className="mt-3 space-y-2 text-xs text-[#9fb4d4]">
                {REQUIRED_DIMENSIONS.map((k) => {
                  const dim = selected.dimensions[k];
                  const unevaluated = dim.score === null;
                  return (
                    <li key={k} className="rounded-lg border border-[#2f6fed]/30 px-3 py-2">
                      <p className="text-white">
                        {DIMENSION_LABEL_MAP[k]} · {unevaluated ? "未评估" : dim.score!.toFixed(1)}
                      </p>
                      {!unevaluated && dim.evidence ? (
                        <p className="mt-1 text-[#7eb6ff]">「{dim.evidence}」</p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </>
          ) : (
            <p className="mt-6 text-sm text-[#9fb4d4]">选择候选人后显示四维雷达；null 维不补零。</p>
          )}
        </section>
      </div>
    </main>
  );
}
