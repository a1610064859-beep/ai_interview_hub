"use client";

import * as echarts from "echarts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppTheme } from "../../components/theme-provider";
import { sortCandidatesByEducation } from "../../lib/candidate-sort";

import {
  DIMENSION_LABEL_MAP,
  REQUIRED_DIMENSIONS,
  transformDimensionsToRadar,
  type DimensionData,
  type DimensionKey,
} from "../../lib/report-data";

type JobOption = { id: number; family: string; title: string; jdDigest: string };
type QuestionKind = "通用" | "专业" | "情景";
type BankQuestion = {
  id: number;
  type: QuestionKind;
  text: string;
  followup_hint: string | null;
  active_for_interview: boolean;
};

type Cohort = { input_mode: "text" | "voice"; scoring_version: string };

type Candidate = {
  user_id: number;
  name_masked: string | null;
  major: string | null;
  grade: string | null;
  student_no: string | null;
  education_level: string | null;
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

type StudentOption = {
  id: number;
  student_no: string | null;
  name_masked: string | null;
  major: string | null;
  grade: string | null;
  education_level: string | null;
};

type StudentProfile = StudentOption & {
  internship_experience: string | null;
  awards: string | null;
  has_resume: boolean;
  resume_filename: string | null;
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
      student_no: typeof raw.student_no === "string" ? raw.student_no : null,
      education_level: typeof raw.education_level === "string" ? raw.education_level : null,
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
  const { theme } = useAppTheme();
  const [jobs, setJobs] = useState<JobOption[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [discover, setDiscover] = useState<CandidatesPayload | null>(null);
  const [selectedCohortKey, setSelectedCohortKey] = useState<string>("");
  const [list, setList] = useState<CandidatesPayload | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [jdText, setJdText] = useState("");
  const [parseDraft, setParseDraft] = useState<ParseDraft | null>(null);
  const [bankQuestions, setBankQuestions] = useState<BankQuestion[]>([]);
  const [bankLoading, setBankLoading] = useState(false);
  const [bankBusy, setBankBusy] = useState(false);
  const [bankError, setBankError] = useState<string | null>(null);
  const [bankMessage, setBankMessage] = useState<string | null>(null);
  const [newQuestionType, setNewQuestionType] = useState<QuestionKind>("专业");
  const [newQuestionText, setNewQuestionText] = useState("");
  const [newFollowupHint, setNewFollowupHint] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [students, setStudents] = useState<StudentOption[]>([]);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [profileRevision, setProfileRevision] = useState(0);
  const [resumeText, setResumeText] = useState<{ studentId: number; paragraphs: string[] } | null>(null);
  const [resumeTextLoading, setResumeTextLoading] = useState(false);
  const [resumeTextError, setResumeTextError] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [resumeFiles, setResumeFiles] = useState<File[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<"score" | "education_desc" | "education_asc">("score");
  const csvInputRef = useRef<HTMLInputElement | null>(null);
  const resumeInputRef = useRef<HTMLInputElement | null>(null);
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

  const loadStudents = useCallback(async () => {
    const resp = await fetch("/api/students");
    if (!resp.ok) throw new Error(await readApiError(resp));
    const payload: unknown = await resp.json();
    if (!isRecord(payload) || !Array.isArray(payload.students)) throw new Error("学生名单响应非法");
    setStudents(payload.students.map((raw: unknown) => {
      if (!isRecord(raw) || !Number.isInteger(raw.id)) throw new Error("学生档案响应非法");
      return {
        id: Number(raw.id),
        student_no: typeof raw.student_no === "string" ? raw.student_no : null,
        name_masked: typeof raw.name_masked === "string" ? raw.name_masked : null,
        major: typeof raw.major === "string" ? raw.major : null,
        grade: typeof raw.grade === "string" ? raw.grade : null,
        education_level: typeof raw.education_level === "string" ? raw.education_level : null,
      };
    }));
  }, []);

  const loadQuestionBank = useCallback(async (jid: number) => {
    setBankLoading(true);
    setBankError(null);
    try {
      const resp = await fetch(`/api/jobs/${jid}/questions`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      const payload: unknown = await resp.json();
      if (!isRecord(payload) || !Array.isArray(payload.questions)) throw new Error("题库响应非法");
      const parsed = payload.questions.map((raw: unknown): BankQuestion => {
        if (!isRecord(raw) || !Number.isInteger(raw.id)) throw new Error("题库题目响应非法");
        const type = String(raw.type);
        if (type !== "通用" && type !== "专业" && type !== "情景") throw new Error("题库题型非法");
        return {
          id: Number(raw.id),
          type,
          text: typeof raw.text === "string" ? raw.text : "",
          followup_hint: typeof raw.followup_hint === "string" ? raw.followup_hint : null,
          active_for_interview: raw.active_for_interview === true,
        };
      });
      setBankQuestions(parsed);
    } catch (e) {
      setBankError(e instanceof Error ? e.message : "加载题库失败");
      setBankQuestions([]);
    } finally {
      setBankLoading(false);
    }
  }, []);

  useEffect(() => {
    if (jobId !== null) void loadQuestionBank(jobId);
    else setBankQuestions([]);
  }, [jobId, loadQuestionBank]);

  async function createBankQuestion() {
    if (jobId === null || newQuestionText.trim().length < 5 || bankBusy) return;
    setBankBusy(true);
    setBankError(null);
    setBankMessage(null);
    try {
      const resp = await fetch(`/api/jobs/${jobId}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: newQuestionType,
          text: newQuestionText,
          followup_hint: newFollowupHint,
        }),
      });
      if (!resp.ok) throw new Error(await readApiError(resp));
      setNewQuestionText("");
      setNewFollowupHint("");
      await loadQuestionBank(jobId);
      setBankMessage("题目已加入题库，并按题型配额参与后续面试。");
    } catch (e) {
      setBankError(e instanceof Error ? e.message : "新增题目失败");
    } finally {
      setBankBusy(false);
    }
  }

  async function saveBankQuestion(question: BankQuestion) {
    if (jobId === null || bankBusy) return;
    setBankBusy(true);
    setBankError(null);
    setBankMessage(null);
    try {
      const resp = await fetch(`/api/jobs/${jobId}/questions/${question.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: question.text, followup_hint: question.followup_hint ?? "" }),
      });
      if (!resp.ok) throw new Error(await readApiError(resp));
      await loadQuestionBank(jobId);
      setBankMessage("题目已保存。");
    } catch (e) {
      setBankError(e instanceof Error ? e.message : "保存题目失败");
    } finally {
      setBankBusy(false);
    }
  }

  async function deleteBankQuestion(question: BankQuestion) {
    if (jobId === null || bankBusy) return;
    if (!window.confirm(`确定删除这道${question.type}题吗？每种题型会保留面试所需的最低数量。`)) return;
    setBankBusy(true);
    setBankError(null);
    setBankMessage(null);
    try {
      const resp = await fetch(`/api/jobs/${jobId}/questions/${question.id}`, { method: "DELETE" });
      if (!resp.ok) throw new Error(await readApiError(resp));
      await loadQuestionBank(jobId);
      setBankMessage("题目已删除。");
    } catch (e) {
      setBankError(e instanceof Error ? e.message : "删除题目失败");
    } finally {
      setBankBusy(false);
    }
  }

  useEffect(() => {
    void loadStudents().catch((e) => setError(e instanceof Error ? e.message : "加载学生名单失败"));
  }, [loadStudents]);

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

  const visibleCandidates = useMemo(() => {
    const candidates = list?.candidates ?? [];
    if (sortMode === "score") return candidates;
    return sortCandidatesByEducation(candidates, sortMode === "education_desc" ? "desc" : "asc");
  }, [list, sortMode]);

  useEffect(() => {
    if (profileId === null) {
      setProfile(null);
      return;
    }
    let cancelled = false;
    setProfile(null);
    (async () => {
      try {
        const resp = await fetch(`/api/recruiter/students/${profileId}`);
        if (!resp.ok) throw new Error(await readApiError(resp));
        const raw: unknown = await resp.json();
        if (!isRecord(raw) || !Number.isInteger(raw.id)) throw new Error("学生档案响应非法");
        if (!cancelled) setProfile({
          id: Number(raw.id),
          student_no: typeof raw.student_no === "string" ? raw.student_no : null,
          name_masked: typeof raw.name_masked === "string" ? raw.name_masked : null,
          major: typeof raw.major === "string" ? raw.major : null,
          grade: typeof raw.grade === "string" ? raw.grade : null,
          education_level: typeof raw.education_level === "string" ? raw.education_level : null,
          internship_experience: typeof raw.internship_experience === "string" ? raw.internship_experience : null,
          awards: typeof raw.awards === "string" ? raw.awards : null,
          has_resume: raw.has_resume === true,
          resume_filename: typeof raw.resume_filename === "string" ? raw.resume_filename : null,
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载学生档案失败");
      }
    })();
    return () => { cancelled = true; };
  }, [profileId, profileRevision]);

  useEffect(() => {
    const studentId = profile?.id;
    const filename = profile?.resume_filename;
    if (!profile?.has_resume || !filename?.toLowerCase().endsWith(".docx") || studentId === undefined) {
      setResumeText(null);
      setResumeTextError(null);
      setResumeTextLoading(false);
      return;
    }
    let cancelled = false;
    setResumeText(null);
    setResumeTextError(null);
    setResumeTextLoading(true);
    (async () => {
      try {
        const response = await fetch(`/api/recruiter/students/${studentId}/resume/text`);
        if (!response.ok) throw new Error(await readApiError(response));
        const raw: unknown = await response.json();
        if (!isRecord(raw) || raw.student_id !== studentId || !Array.isArray(raw.paragraphs) || raw.paragraphs.some((item) => typeof item !== "string")) {
          throw new Error("简历内容响应非法");
        }
        if (!cancelled) setResumeText({ studentId, paragraphs: raw.paragraphs as string[] });
      } catch (e) {
        if (!cancelled) setResumeTextError(e instanceof Error ? e.message : "读取简历内容失败");
      } finally {
        if (!cancelled) setResumeTextLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [profile?.id, profile?.has_resume, profile?.resume_filename]);

  useEffect(() => {
    if (!selected || !chartRef.current) {
      chartInstance.current?.dispose();
      chartInstance.current = null;
      return;
    }
    const chartElement = chartRef.current;
    const radar = transformDimensionsToRadar(selected.dimensions, theme);
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
  }, [selected, theme]);

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

  async function runImport() {
    if (!csvFile || importBusy) return;
    setImportBusy(true);
    setImportMessage(null);
    setError(null);
    try {
      const form = new FormData();
      form.append("csv_file", csvFile);
      for (const file of resumeFiles) form.append("resumes", file);
      const resp = await fetch("/api/recruiter/students/import", { method: "POST", body: form });
      if (!resp.ok) throw new Error(await readApiError(resp));
      const result: unknown = await resp.json();
      if (!isRecord(result)) throw new Error("导入结果非法");
      setImportMessage(`导入完成：新增 ${Number(result.created)} 人，更新 ${Number(result.updated)} 人。`);
      setCsvFile(null);
      setResumeFiles([]);
      if (csvInputRef.current) csvInputRef.current.value = "";
      if (resumeInputRef.current) resumeInputRef.current.value = "";
      await loadStudents();
      setProfileRevision((revision) => revision + 1);
      if (selectedCohortKey) await loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "学生名单导入失败");
    } finally {
      setImportBusy(false);
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
      </header>

      {error ? (
        <p className="mb-4 rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]" role="alert">
          {error}
        </p>
      ) : null}

      <section className="mb-4 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
        <h2 className="text-lg text-white">学生档案与名单导入</h2>
        <p className="mt-1 text-sm text-[#9fb4d4]">
          下载固定 CSV 模板，填写脱敏姓名及学生编号；如填写简历文件名，同时选择同名的 .docx 或 .pdf 文件。重复编号更新档案，未完成训练的学生不会进入候选榜。
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-4">
            <a href="/api/recruiter/students/template.csv" download className="text-sm text-[#7eb6ff] underline">
              下载 CSV 模板
            </a>
            <label className="mt-3 block text-sm text-[#9fb4d4]">
              选择学生名单 CSV
              <input ref={csvInputRef} type="file" accept=".csv,text/csv" className="mt-2 block w-full text-xs text-white" onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
            </label>
            <label className="mt-3 block text-sm text-[#9fb4d4]">
              选择简历文件（可多选）
              <input ref={resumeInputRef} type="file" multiple accept=".docx,.pdf" className="mt-2 block w-full text-xs text-white" onChange={(e) => setResumeFiles(Array.from(e.target.files ?? []))} />
            </label>
            <button type="button" disabled={!csvFile || importBusy} onClick={() => void runImport()} className="mt-4 rounded-full bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:opacity-50">
              {importBusy ? "正在导入…" : "一键导入名单"}
            </button>
            {importMessage ? <p className="mt-2 text-sm text-emerald-300" role="status">{importMessage}</p> : null}
          </div>
          <div className="rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-4">
            <label className="block text-sm text-[#9fb4d4]">
              查看学生档案（共 {students.length} 人）
              <select className="mt-2 w-full rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" value={profileId ?? ""} onChange={(e) => setProfileId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">请选择学生</option>
                {students.map((student) => (
                  <option key={student.id} value={student.id}>
                    {student.student_no ?? `#${student.id}`} · {student.name_masked ?? "未填姓名"} · {student.major ?? "专业未填"}
                  </option>
                ))}
              </select>
            </label>
            <p className="mt-3 text-xs text-[#9fb4d4]">候选榜继续只使用同岗位、同评分口径的真实面试报告；导入的档案不会生成虚构分数。</p>
          </div>
        </div>
      </section>

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
              排序
              <select className="rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" value={sortMode} onChange={(e) => setSortMode(e.target.value as typeof sortMode)}>
                <option value="score">岗位加权分</option>
                <option value="education_desc">学历：高到低</option>
                <option value="education_asc">学历：低到高</option>
              </select>
            </label>
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
              {visibleCandidates.map((c) => (
                <li key={c.user_id}>
                  <button
                    type="button"
                    onClick={() => { setSelectedUserId(c.user_id); setProfileId(c.user_id); }}
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
                          {c.major ?? "专业未填"} · {c.grade ?? "年级未填"} · {c.education_level ?? "学历未填"} · sid={c.session_id}
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
          <div className="mt-5 border-t border-[#2f6fed]/40 pt-4">
            <h3 className="text-base text-white">学生信息</h3>
            {profile ? (
              <dl className="mt-3 space-y-3 text-sm">
                <div><dt className="text-[#9fb4d4]">姓名 / 学生编号</dt><dd className="text-white">{profile.name_masked ?? "未填写"} / {profile.student_no ?? `#${profile.id}`}</dd></div>
                <div><dt className="text-[#9fb4d4]">专业 / 年级 / 学历</dt><dd className="text-white">{profile.major ?? "未填写"} / {profile.grade ?? "未填写"} / {profile.education_level ?? "未填写"}</dd></div>
                <div><dt className="text-[#9fb4d4]">实习经历</dt><dd className="whitespace-pre-wrap text-white">{profile.internship_experience ?? "未填写"}</dd></div>
                <div><dt className="text-[#9fb4d4]">获奖情况</dt><dd className="whitespace-pre-wrap text-white">{profile.awards ?? "未填写"}</dd></div>
                <div>
                  <dt className="text-[#9fb4d4]">简历</dt>
                  <dd>
                    {profile.has_resume ? (
                      <>
                        <a
                          href={`/api/recruiter/students/${profile.id}/resume`}
                          target={profile.resume_filename?.toLowerCase().endsWith(".pdf") ? "_blank" : undefined}
                          rel="noopener noreferrer"
                          className="text-[#7eb6ff] underline"
                        >
                          {profile.resume_filename?.toLowerCase().endsWith(".pdf") ? "浏览器预览 PDF" : "下载 Word 原件"} · {profile.resume_filename ?? "简历"}
                        </a>
                        {profile.resume_filename?.toLowerCase().endsWith(".docx") && (
                          <div className="mt-3 rounded-xl border border-[#2f6fed]/40 bg-[#050912]/80 p-3" aria-live="polite">
                            <h4 className="text-sm font-semibold text-white">简历文字内容（网页读取）</h4>
                            {resumeTextLoading ? (
                              <p className="mt-2 text-sm text-[#9fb4d4]">正在读取 DOCX 正文…</p>
                            ) : resumeTextError ? (
                              <p className="mt-2 text-sm text-[#ffb7a8]">{resumeTextError}</p>
                            ) : resumeText?.studentId === profile.id ? (
                              resumeText.paragraphs.length > 0 ? (
                                <div className="mt-2 max-h-80 space-y-2 overflow-y-auto pr-1 text-sm leading-6 text-white">
                                  {resumeText.paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph}`}>{paragraph}</p>)}
                                </div>
                              ) : <p className="mt-2 text-sm text-[#9fb4d4]">DOCX 中没有可读取的正文文字。</p>
                            ) : null}
                          </div>
                        )}
                      </>
                    ) : <span className="text-white">未上传</span>}
                  </dd>
                </div>
              </dl>
            ) : <p className="mt-2 text-sm text-[#9fb4d4]">{profileId === null ? "从名单或候选列表选择学生。" : "正在读取档案…"}</p>}
          </div>
        </section>
      </div>

      <section className="mt-4 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg text-white">自定义题库</h2>
            <p className="mt-1 max-w-3xl text-sm text-[#9fb4d4]">
              可按岗位新增、修改和删除题目。每场面试仍使用 2 道通用、3 道专业、1 道情景题；同类题目按最近加入顺序优先使用，正在进行面试时题库会锁定。
            </p>
          </div>
          <button type="button" onClick={() => jobId !== null && void loadQuestionBank(jobId)} disabled={jobId === null || bankLoading || bankBusy} className="rounded-full border border-[#2f6fed] px-3 py-2 text-sm text-[#7eb6ff] disabled:opacity-50">
            {bankLoading ? "加载中…" : "刷新题库"}
          </button>
        </div>

        <form className="mt-4 grid gap-3 rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-4 lg:grid-cols-[150px_minmax(0,1fr)_minmax(0,1fr)_auto]" onSubmit={(event) => { event.preventDefault(); void createBankQuestion(); }}>
          <label className="flex flex-col gap-2 text-sm text-[#9fb4d4]">
            题型
            <select value={newQuestionType} onChange={(event) => setNewQuestionType(event.target.value as QuestionKind)} className="rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white">
              <option value="通用">通用</option>
              <option value="专业">专业</option>
              <option value="情景">情景</option>
            </select>
          </label>
          <label className="flex flex-col gap-2 text-sm text-[#9fb4d4]">
            自定义题目
            <textarea value={newQuestionText} onChange={(event) => setNewQuestionText(event.target.value)} maxLength={500} minLength={5} required placeholder="输入 5–500 字的题目" className="min-h-20 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" />
          </label>
          <label className="flex flex-col gap-2 text-sm text-[#9fb4d4]">
            追问提示（可选）
            <textarea value={newFollowupHint} onChange={(event) => setNewFollowupHint(event.target.value)} maxLength={1000} placeholder="帮助面试官围绕回答追问" className="min-h-20 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" />
          </label>
          <button type="submit" disabled={jobId === null || bankBusy || newQuestionText.trim().length < 5} className="self-end rounded-full bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:opacity-50">
            {bankBusy ? "处理中…" : "加入题库"}
          </button>
        </form>

        {bankError ? <p className="mt-3 rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-3 py-2 text-sm text-[#ffd0a8]" role="alert">{bankError}</p> : null}
        {bankMessage ? <p className="mt-3 text-sm text-emerald-300" role="status">{bankMessage}</p> : null}

        <div className="mt-4 max-h-[680px] space-y-3 overflow-y-auto pr-1">
          {bankQuestions.map((question) => (
            <article key={question.id} className="rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-3 sm:p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm text-white">
                  <span className="rounded-full border border-[#2f6fed]/60 px-2 py-1 text-[#9fb4d4]">{question.type}</span>
                  <span className={question.active_for_interview ? "text-emerald-300" : "text-[#8292aa]"}>
                    {question.active_for_interview ? "当前面试使用" : "备用题"}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button type="button" disabled={bankBusy || question.text.trim().length < 5} onClick={() => void saveBankQuestion(question)} className="rounded-full border border-[#2f6fed] px-3 py-1.5 text-xs text-[#7eb6ff] disabled:opacity-50">保存</button>
                  <button type="button" disabled={bankBusy} onClick={() => void deleteBankQuestion(question)} className="rounded-full border border-[#ff8a2a]/60 px-3 py-1.5 text-xs text-[#ffb36b] disabled:opacity-50">删除</button>
                </div>
              </div>
              <label className="block text-xs text-[#9fb4d4]">
                题目
                <textarea value={question.text} maxLength={500} onChange={(event) => setBankQuestions((current) => current.map((item) => item.id === question.id ? { ...item, text: event.target.value } : item))} className="mt-1 min-h-16 w-full rounded-xl border border-[#2f6fed]/50 bg-[#0c1730] px-3 py-2 text-sm text-white" />
              </label>
              <label className="mt-2 block text-xs text-[#9fb4d4]">
                追问提示
                <input value={question.followup_hint ?? ""} maxLength={1000} onChange={(event) => setBankQuestions((current) => current.map((item) => item.id === question.id ? { ...item, followup_hint: event.target.value } : item))} placeholder="可选" className="mt-1 w-full rounded-xl border border-[#2f6fed]/50 bg-[#0c1730] px-3 py-2 text-sm text-white" />
              </label>
            </article>
          ))}
          {!bankLoading && bankQuestions.length === 0 ? <p className="py-6 text-center text-sm text-[#9fb4d4]">暂无题目，请先检查岗位题库是否已初始化。</p> : null}
        </div>
      </section>
    </main>
  );
}
