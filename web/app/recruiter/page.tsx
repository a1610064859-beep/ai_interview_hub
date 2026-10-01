"use client";

import * as echarts from "echarts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppTheme } from "../../components/theme-provider";
import { sortCandidatesByEducation, sortCandidatesBySchoolTier } from "../../lib/candidate-sort";
import { extractResumeDetails, extractResumeRequirements } from "../../lib/resume-data";

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
  school_tier: string | null;
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
  school_tier: string | null;
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

type WeightKey = "professional_match" | "logic_structure" | "expression_fluency" | "job_competence" | "education_level" | "school_tier";
type WeightPercentages = Record<WeightKey, number>;
const WEIGHT_KEYS: WeightKey[] = [
  "professional_match",
  "logic_structure",
  "expression_fluency",
  "job_competence",
  "education_level",
  "school_tier",
];
const WEIGHT_LABELS: Record<WeightKey, string> = {
  professional_match: "专业匹配度",
  logic_structure: "逻辑结构",
  expression_fluency: "表达流畅度",
  job_competence: "岗位素养",
  education_level: "学历层次",
  school_tier: "学校档次",
};

function parseWeightPercentages(weights: Record<string, unknown> | null): WeightPercentages | null {
  if (!weights || WEIGHT_KEYS.some((key) => typeof weights[key] !== "number" || !Number.isFinite(weights[key]))) return null;
  const values = Object.fromEntries(WEIGHT_KEYS.map((key) => [key, Number(weights[key])])) as WeightPercentages;
  const total = WEIGHT_KEYS.reduce((sum, key) => sum + values[key], 0);
  if (Math.abs(total - 1) > 0.000001) return null;
  const exact = WEIGHT_KEYS.map((key) => values[key] * 100);
  const rounded = exact.map(Math.floor);
  const remainder = 100 - rounded.reduce((sum, value) => sum + value, 0);
  const priority = exact
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  for (let index = 0; index < remainder; index += 1) rounded[priority[index].index] += 1;
  return Object.fromEntries(WEIGHT_KEYS.map((key, index) => [key, rounded[index]])) as WeightPercentages;
}

function rebalanceWeight(current: WeightPercentages, key: WeightKey, value: number): WeightPercentages {
  const nextValue = Math.max(0, Math.min(100, Math.round(value)));
  const otherKeys = WEIGHT_KEYS.filter((item) => item !== key);
  const oldTotal = otherKeys.reduce((total, item) => total + current[item], 0);
  const remaining = 100 - nextValue;
  const next = { ...current, [key]: nextValue };
  let assigned = 0;
  otherKeys.forEach((item, index) => {
    const portion = index === otherKeys.length - 1
      ? remaining - assigned
      : oldTotal > 0
        ? Math.round((current[item] / oldTotal) * remaining)
        : Math.floor(remaining / otherKeys.length);
    next[item] = portion;
    assigned += portion;
  });
  return next;
}

type ParseDraft = {
  job_id: number;
  family: string;
  title: string;
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
      school_tier: typeof raw.school_tier === "string" ? raw.school_tier : null,
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
  const [parseBusy, setParseBusy] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [createdJd, setCreatedJd] = useState<string | null>(null);
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
  const [resumeText, setResumeText] = useState<{ studentId: number; paragraphs: string[]; images: string[] } | null>(null);
  const [resumeTextLoading, setResumeTextLoading] = useState(false);
  const [resumeTextError, setResumeTextError] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [resumeFiles, setResumeFiles] = useState<File[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<"score" | "education_desc" | "education_asc" | "school_desc" | "school_asc">("score");
  const [weightDraft, setWeightDraft] = useState<WeightPercentages | null>(null);
  const [weightSaving, setWeightSaving] = useState(false);
  const [weightMessage, setWeightMessage] = useState<string | null>(null);
  const [weightError, setWeightError] = useState<string | null>(null);
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
        school_tier: typeof raw.school_tier === "string" ? raw.school_tier : null,
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
    setWeightDraft(null);
    setWeightMessage(null);
    setWeightError(null);
    setSelectedCohortKey("");
    setSelectedUserId(null);
    try {
      const resp = await fetch(`/api/recruiter/candidates?job_id=${jid}`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      const payload = parseCandidatesPayload(await resp.json());
      setDiscover(payload);
      setWeightDraft(parseWeightPercentages(payload.weights));
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
      if (payload.candidates[0]) setProfileId(payload.candidates[0].user_id);
    } catch (e) {
      setList(null);
      setError(e instanceof Error ? e.message : "加载候选失败");
    } finally {
      setBusy(false);
    }
  }, [jobId, selectedCohortKey]);

  async function saveRecruiterWeights() {
    if (jobId === null || weightDraft === null) return;
    setWeightSaving(true);
    setWeightError(null);
    setWeightMessage(null);
    try {
      const body = Object.fromEntries(WEIGHT_KEYS.map((key) => [key, weightDraft[key] / 100]));
      const response = await fetch(`/api/jobs/${jobId}/weights`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const payload: unknown = await response.json();
      if (!isRecord(payload)) throw new Error("权重保存响应非法");
      const savedWeights = parseWeightPercentages(payload);
      if (!savedWeights) throw new Error("权重保存响应缺少有效的六项权重");
      setWeightDraft(savedWeights);
      setDiscover((current) => current ? { ...current, weights: payload } : current);
      setWeightMessage("权重已保存到当前岗位，岗位加权分已更新。");
      if (selectedCohortKey) await loadCandidates();
    } catch (e) {
      setWeightError(e instanceof Error ? e.message : "保存权重失败");
    } finally {
      setWeightSaving(false);
    }
  }

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
    if (sortMode === "school_desc" || sortMode === "school_asc") {
      return sortCandidatesBySchoolTier(candidates, sortMode === "school_desc" ? "desc" : "asc");
    }
    return sortCandidatesByEducation(candidates, sortMode === "education_desc" ? "desc" : "asc");
  }, [list, sortMode]);

  const savedWeightPercentages = parseWeightPercentages(discover?.weights ?? null);
  const weightDraftIsDirty = weightDraft !== null && savedWeightPercentages !== null
    && WEIGHT_KEYS.some((key) => weightDraft[key] !== savedWeightPercentages[key]);

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
          school_tier: typeof raw.school_tier === "string" ? raw.school_tier : null,
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
        const response = await fetch(`/api/recruiter/students/${studentId}/resume/text?include_images=true`);
        if (!response.ok) throw new Error(await readApiError(response));
        const raw: unknown = await response.json();
        if (!isRecord(raw) || raw.student_id !== studentId || !Array.isArray(raw.paragraphs) || raw.paragraphs.some((item) => typeof item !== "string")) {
          throw new Error("简历内容响应非法");
        }
        const images = Array.isArray(raw.images) ? raw.images.flatMap((item) =>
          isRecord(item) && typeof item.data_url === "string" && /^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(item.data_url) ? [item.data_url] : [],
        ) : [];
        if (!cancelled) setResumeText({ studentId, paragraphs: raw.paragraphs as string[], images });
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
    const trimmedJd = jdText.trim();
    if (parseBusy || trimmedJd.length < 20 || trimmedJd.length > 20000) return;
    setParseBusy(true);
    setParseError(null);
    setParseDraft(null);
    try {
      const resp = await fetch("/api/jobs/create-from-jd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jd_text: trimmedJd }),
      });
      if (!resp.ok) throw new Error(await readApiError(resp));
      const raw: unknown = await resp.json();
      if (!isRecord(raw)) throw new Error("解析响应非法");
      const createdJobId = Number(raw.job_id);
      if (!Number.isInteger(createdJobId) || typeof raw.family !== "string" || typeof raw.title !== "string") {
        throw new Error("新岗位信息不完整");
      }
      const createdJob = {
        id: createdJobId,
        family: raw.family,
        title: raw.title,
        jdDigest: trimmedJd,
      };
      setJobs((current) => [...current.filter((job) => job.id !== createdJobId), createdJob].sort((a, b) => a.id - b.id));
      setJobId(createdJobId);
      setCreatedJd(trimmedJd);
      setParseDraft({
        job_id: createdJobId,
        family: raw.family,
        title: raw.title,
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
      setParseError(e instanceof Error ? e.message : "JD 解析失败");
    } finally {
      setParseBusy(false);
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

  const resumeParagraphs = profile?.id === resumeText?.studentId ? resumeText?.paragraphs ?? [] : [];
  const resumeImages = profile?.id === resumeText?.studentId ? resumeText?.images ?? [] : [];
  const resumeRequirements = extractResumeRequirements(resumeParagraphs);
  const resumeDetails = extractResumeDetails(resumeParagraphs);

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

      <details className="mb-4 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
        <summary className="cursor-pointer text-sm font-medium text-white">学生档案与名单导入</summary>
        <p className="mt-1 text-sm text-[#9fb4d4]">
          下载固定 CSV 模板，填写脱敏姓名、学生编号和学校档次（C9/985、211/双一流、普通本科、高职/大专、中职/技校或其他/未知）；学校档次请按学校实际情况填写，不会根据学历推断。简历文件名填写完整文件名。请将 CSV 引用的 .docx 或 .pdf 简历集中放入一个文件夹，再选择该文件夹；文件夹内只放 CSV 引用的简历，避免多传造成不匹配。重复编号更新档案，未完成训练的学生不会进入候选榜。
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-4">
            <a href="/api/recruiter/students/template.csv" download className="text-sm text-[#7eb6ff] underline">
              下载 CSV 模板
            </a>
            <label className="mt-3 block text-sm text-[#9fb4d4]">
              选择学生名单 CSV
              <input ref={csvInputRef} type="file" accept=".csv,text/csv" className="mt-2 block w-full text-xs text-white file:mr-3 file:rounded-md file:border-0 file:bg-[#111827] file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-[#1f2937]" onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
            </label>
            <label className="mt-3 block text-sm text-[#9fb4d4]">
              选择简历文件夹
              <input ref={(input) => { resumeInputRef.current = input; input?.setAttribute("webkitdirectory", ""); }} type="file" multiple accept=".docx,.pdf" className="mt-2 block w-full text-xs text-white file:mr-3 file:rounded-md file:border-0 file:bg-[#111827] file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-[#1f2937]" onChange={(e) => setResumeFiles(Array.from(e.target.files ?? []))} />
            </label>
            <button type="button" disabled={!csvFile || importBusy} onClick={() => void runImport()} className="mt-4 rounded-full bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:opacity-50">
              {importBusy ? "正在导入…" : "一键导入名单"}
            </button>
            {importMessage ? <p className="mt-2 text-sm text-emerald-300" role="status">{importMessage}</p> : null}
          </div>
          <div className="rounded-xl border border-[#2f6fed]/30 bg-[#050912] p-4">
            <label className="block text-sm text-[#9fb4d4]">
              查看学生档案（共 {students.length} 人）
              <select className="mt-2 w-full rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" value={profileId ?? ""} onChange={(e) => { const id = e.target.value ? Number(e.target.value) : null; setProfileId(id); setSelectedUserId(id); }}>
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
      </details>

        <details className="mb-4 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <summary className="cursor-pointer text-sm font-medium text-white">粘贴 JD 新建岗位</summary>
          <p className="mt-2 text-xs leading-5 text-[#9fb4d4]">
            解析后会创建岗位并写入题库；系统从 JD 提取岗位类别和名称。评分仍使用四个固定维度，新岗位默认等权。
          </p>
          <label className="mt-3 flex flex-col gap-2 text-sm text-[#9fb4d4]">
            岗位 JD
            <textarea
              className="min-h-28 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-sm text-white"
              value={jdText}
              disabled={parseBusy}
              onChange={(e) => {
                setJdText(e.target.value);
                setParseDraft(null);
                setParseError(null);
              }}
              placeholder="粘贴岗位职责和任职要求…"
            />
          </label>
          <p className="mt-2 text-xs text-[#8ea4c7]" aria-live="polite">
            {jdText.trim().length < 20
              ? `JD 至少需要 20 字，当前 ${jdText.trim().length} 字。`
              : jdText.trim().length > 20000
                ? `JD 最多 20000 字，当前 ${jdText.trim().length} 字。`
                : `已输入 ${jdText.trim().length} 字，可解析。`}
          </p>
          <button
            type="button"
            disabled={parseBusy || jdText.trim().length < 20 || jdText.trim().length > 20000 || createdJd === jdText.trim()}
            className="mt-3 rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:opacity-50"
            onClick={() => void runParse()}
          >
            {parseBusy ? "正在解析并创建…" : createdJd === jdText.trim() ? "此 JD 已创建" : "解析并创建岗位"}
          </button>
          {parseBusy ? (
            <p className="mt-3 rounded-lg border border-[#2f6fed]/40 bg-[#071326] px-3 py-2 text-sm text-[#a9cbff]" role="status" aria-live="polite">
              正在分析 JD、生成题库并保存新岗位，请稍候…
            </p>
          ) : null}
          {parseError ? (
            <p className="mt-3 rounded-lg border border-[#ff8a2a]/60 bg-[#2a1608] px-3 py-2 text-sm text-[#ffd0a8]" role="alert">
              JD 解析失败：{parseError}
            </p>
          ) : null}
          {parseDraft ? (
            <div className="mt-4 space-y-4 rounded-xl border border-[#2f6fed]/40 bg-[#071326] p-3" aria-live="polite">
              <p className="text-sm font-medium text-emerald-300" role="status">
                已创建岗位 #{parseDraft.job_id} · {parseDraft.family} · {parseDraft.title}
              </p>
              <p className="text-xs leading-5 text-[#9fb4d4]">
                岗位和题库已保存。以下 JD 建议维度仅供参考；面试报告仍按固定四维评分。
              </p>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-[#7eb6ff]">JD 建议评估维度</h3>
                {parseDraft.dims.length ? (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {parseDraft.dims.map((dim, index) => (
                      <li key={`${dim}-${index}`} className="rounded-full border border-[#2f6fed]/50 bg-[#0c1730] px-2.5 py-1 text-xs text-[#d7e3f7]">
                        {dim}
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-sm text-[#9fb4d4]">没有生成评估维度。</p>}
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-[#7eb6ff]">已写入题库（{parseDraft.questions.length} 题）</h3>
                {parseDraft.questions.length ? (
                  <ol className="mt-2 max-h-72 space-y-2 overflow-y-auto pr-1">
                    {parseDraft.questions.map((question, index) => (
                      <li key={`${question.type}-${index}`} className="rounded-lg border border-[#2f6fed]/25 bg-[#050912]/70 p-2.5">
                        <div className="mb-1 flex items-center gap-2">
                          <span className="text-xs text-[#7eb6ff]">{index + 1}.</span>
                          <span className="rounded-full bg-[#172b4c] px-2 py-0.5 text-[11px] text-[#a9cbff]">{question.type}</span>
                        </div>
                        <p className="text-sm leading-6 text-[#d7e3f7]">{question.text}</p>
                      </li>
                    ))}
                  </ol>
                ) : <p className="mt-2 text-sm text-[#9fb4d4]">没有生成面试题。</p>}
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-[#7eb6ff]">专业术语</h3>
                <p className="mt-2 text-sm leading-6 text-[#d7e3f7]">{parseDraft.terms.join("、") || "未提取到专业术语。"}</p>
              </div>
            </div>
          ) : null}
        </details>

      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(230px,0.75fr)_minmax(0,1.65fr)] xl:grid-cols-[minmax(260px,0.8fr)_minmax(0,1.8fr)_minmax(260px,0.8fr)]">
        <section className="min-w-0 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg text-white">候选列表</h2>
            <label className="flex w-full flex-col items-start gap-2 text-sm text-[#9fb4d4]">
              排序
              <select className="w-full min-w-0 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white" value={sortMode} onChange={(e) => setSortMode(e.target.value as typeof sortMode)}>
                <option value="score">岗位加权分</option>
                <option value="school_desc">学校档次：高到低</option>
                <option value="school_asc">学校档次：低到高</option>
                <option value="education_desc">学历：高到低</option>
                <option value="education_asc">学历：低到高</option>
              </select>
            </label>
            <label className="flex w-full flex-col items-start gap-2 text-sm text-[#9fb4d4]">
              评分口径
              <select
                className="w-full min-w-0 rounded-xl border border-[#2f6fed] bg-[#050912] px-3 py-2 text-white"
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
          <details className="mb-4 rounded-xl border border-[#2f6fed]/40 bg-[#050912] p-4">
            <summary className="cursor-pointer text-sm font-medium text-white">人才需求权重 · 展开调整</summary>
            <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-white">人才需求权重</h3>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-[#9fb4d4]">
                  调整当前岗位的面试四维、学历和学校档次占比；拖动任一项时其余五项会按现有比例自动分配，合计保持 100%。旧版岗位默认保留原面试维度的相对比例并分配学历 20%、学校档次 20%。
                </p>
              </div>
              <button type="button" disabled={!weightDraft || !weightDraftIsDirty || weightSaving} onClick={() => void saveRecruiterWeights()} className="rounded-lg bg-[#ff8a2a] px-3 py-2 text-xs font-medium text-[#1a0d04] disabled:cursor-not-allowed disabled:opacity-50">
                {weightSaving ? "保存中…" : "保存本岗位权重"}
              </button>
            </div>
            {weightDraft ? (
              <>
                <div className="mt-3 grid gap-x-5 gap-y-3 grid-cols-1">
                  {WEIGHT_KEYS.map((key) => (
                    <label key={key} className="block text-xs text-[#d7e3f7]">
                      <span className="mb-1 flex items-center justify-between gap-2">
                        <span>{WEIGHT_LABELS[key]}</span>
                        <span className="tabular-nums text-[#7eb6ff]">{weightDraft[key]}%</span>
                      </span>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        step="1"
                        value={weightDraft[key]}
                        disabled={weightSaving}
                        aria-label={`${WEIGHT_LABELS[key]}权重`}
                        className="w-full accent-[#ff8a2a]"
                        onChange={(event) => {
                          const nextValue = Number(event.target.value);
                          setWeightDraft((current) => current ? rebalanceWeight(current, key, nextValue) : current);
                          setWeightMessage(null);
                          setWeightError(null);
                        }}
                      />
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-right text-xs text-[#7eb6ff]">
                  当前合计 {WEIGHT_KEYS.reduce((total, key) => total + weightDraft[key], 0)}%
                </p>
              </>
            ) : (
              <p className="mt-3 text-xs text-[#ffd0a8]">权重配置不可用：请先修复当前岗位的权重数据。</p>
            )}
            <p className="mt-2 text-xs text-[#9fb4d4]" aria-live="polite">
              缺失的面试维度、学历或学校档次不按零分处理，该项不参与该候选人的加权计算，其他已知项按比例折算。
            </p>
            {weightMessage ? <p className="mt-2 text-xs text-emerald-300" role="status">{weightMessage}</p> : null}
            {weightError ? <p className="mt-2 text-xs text-[#ffd0a8]" role="alert">权重保存失败：{weightError}</p> : null}
          </details>
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
                          {c.major ?? "专业未填"} · {c.grade ?? "年级未填"} · {c.education_level ?? "学历未填"} · {c.school_tier ?? "学校档次未填"} · sid={c.session_id}
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
        <section aria-label="简历详情" className="min-w-0 rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-5 shadow-[0_0_24px_rgba(47,111,237,0.2)] sm:p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[#2f6fed]/30 pb-4">
            <div><p className="text-xs tracking-widest text-[#7eb6ff]">RESUME</p><h2 className="mt-1 text-xl font-semibold text-white">候选人简历</h2></div>
            <label className="flex min-w-0 flex-col gap-1 text-xs text-[#9fb4d4]">查看学生简历
              <select className="max-w-full rounded-lg border border-[#2f6fed]/50 bg-[#050912] px-3 py-2 text-sm text-white" value={profileId ?? ""} onChange={(e) => { const id = e.target.value ? Number(e.target.value) : null; setProfileId(id); setSelectedUserId(id); }}>
                <option value="">请选择学生</option>
                {students.map((student) => <option key={student.id} value={student.id}>{student.name_masked ?? "未填写姓名"} · {student.student_no ?? `#${student.id}`}</option>)}
              </select>
            </label>
            {profile?.has_resume && <a href={`/api/recruiter/students/${profile.id}/resume`} target={profile.resume_filename?.toLowerCase().endsWith(".pdf") ? "_blank" : undefined} rel="noreferrer" className="rounded-lg border border-[#2f6fed]/60 px-3 py-2 text-sm text-[#7eb6ff] hover:border-[#7eb6ff]">查看 / 下载原件</a>}
          </div>
          {profile ? (
            <>
              <div className="flex flex-col-reverse justify-between gap-5 sm:flex-row">
                <div className="min-w-0 flex-1">
                  <h3 className="text-2xl font-semibold text-white">{profile.name_masked ?? "未填写姓名"}</h3>
                  <p className="mt-2 text-sm text-[#9fb4d4]">学生编号 {profile.student_no ?? `#${profile.id}`}</p>
                  <dl className="mt-5 grid grid-cols-2 gap-x-5 gap-y-4 text-sm">
                    {[{ label: "专业", value: profile.major }, { label: "年级", value: profile.grade }, { label: "学历", value: profile.education_level }, { label: "学校名称", value: resumeDetails.find((detail) => detail.label === "毕业院校")?.value ?? "未注明" }, { label: "籍贯", value: resumeDetails.find((detail) => detail.label === "籍贯")?.value ?? "未注明" }, { label: "现居 / 住址", value: resumeDetails.find((detail) => detail.label === "现居 / 住址")?.value ?? "未注明" }, ...resumeDetails.filter((detail) => detail.label === "年龄")].map(({ label, value }) => (
                      <div key={label}><dt className="text-xs text-[#9fb4d4]">{label}</dt><dd className="mt-1 break-words font-medium text-white">{value ?? "未填写"}</dd></div>
                    ))}
                  </dl>
                </div>
                <figure className="w-40 shrink-0 sm:w-44">
                  {resumeImages[0] ? <img src={resumeImages[0]} alt="简历原件中的照片或图片" className="h-52 w-40 rounded-xl border border-[#2f6fed]/40 bg-[#050912] object-contain sm:h-56 sm:w-44" /> : <div className="flex h-52 w-40 items-center justify-center rounded-xl border border-dashed border-[#2f6fed]/40 bg-[#050912] px-4 text-center text-sm leading-6 text-[#9fb4d4] sm:h-56 sm:w-44">{resumeTextLoading ? "正在读取照片…" : profile.resume_filename?.toLowerCase().endsWith(".pdf") ? "照片见下方 PDF 原件" : "简历未提供可显示的照片"}</div>}
                  <figcaption className="mt-2 text-center text-xs text-[#9fb4d4]">简历照片 / 原件图片</figcaption>
                </figure>
              </div>
              {(profile.internship_experience || profile.awards) && <dl className="mt-6 space-y-4 border-t border-[#2f6fed]/30 pt-5 text-sm">
                {profile.internship_experience && <div><dt className="font-medium text-[#7eb6ff]">实习经历</dt><dd className="mt-2 whitespace-pre-wrap break-words leading-7 text-white">{profile.internship_experience}</dd></div>}
                {profile.awards && <div><dt className="font-medium text-[#7eb6ff]">获奖情况</dt><dd className="mt-2 whitespace-pre-wrap break-words leading-7 text-white">{profile.awards}</dd></div>}
              </dl>}
              <div className="mt-6 border-t border-[#2f6fed]/30 pt-5" aria-live="polite">
                <h3 className="text-base font-semibold text-white">个人履历</h3>
                {profile.has_resume ? (
                  profile.resume_filename?.toLowerCase().endsWith(".pdf") ? <>
                    <p className="mt-2 text-xs text-[#9fb4d4]">PDF 原件保留照片与排版，可在下方直接阅读。</p>
                    <iframe title={`${profile.name_masked ?? "候选人"}的 PDF 简历`} src={`/api/recruiter/students/${profile.id}/resume#view=FitH`} className="mt-4 h-[75vh] min-h-[600px] w-full rounded-xl border border-[#2f6fed]/30 bg-white" />
                  </> : resumeTextLoading ? <p className="mt-4 text-sm text-[#9fb4d4]">正在读取简历正文与照片…</p> : resumeTextError ? <p className="mt-4 text-sm text-[#ffb7a8]" role="alert">{resumeTextError}。可以查看 / 下载原件。</p> : resumeParagraphs.length > 0 ? <>
                    <div className="mt-4 min-h-80 space-y-4 rounded-xl border border-[#2f6fed]/20 bg-[#050912]/70 p-5 text-base leading-8 text-white sm:p-6">
                      {resumeParagraphs.map((paragraph, index) => <p key={`${profile.id}-${index}`} className="whitespace-pre-wrap break-words">{paragraph}</p>)}
                    </div>
                    {resumeImages.length > 1 && <div className="mt-5"><h4 className="text-sm text-[#9fb4d4]">简历内其他图片</h4><div className="mt-3 flex flex-wrap gap-3">{resumeImages.slice(1).map((image, index) => <img key={index} src={image} alt={`简历内图片 ${index + 2}`} className="max-h-60 max-w-full rounded-lg border border-[#2f6fed]/30 object-contain" />)}</div></div>}
                  </> : <p className="mt-4 text-sm text-[#9fb4d4]">简历中没有可读取的正文文字，请查看原件。</p>
                ) : <div className="mt-4 rounded-xl border border-dashed border-[#2f6fed]/40 px-5 py-12 text-center text-sm text-[#9fb4d4]">该学生尚未上传简历，可在“学生档案与名单导入”中导入。</div>}
              </div>
            </>
          ) : <div className="flex min-h-96 items-center justify-center rounded-xl border border-dashed border-[#2f6fed]/40 p-8 text-center text-sm leading-7 text-[#9fb4d4]">{profileId === null ? "从左侧候选列表选择学生，或展开名单导入选择档案。" : "正在读取学生档案…"}</div>}
        </section>
        <aside className="min-w-0 space-y-4 lg:col-span-2 lg:grid lg:grid-cols-2 lg:gap-4 lg:space-y-0 xl:col-span-1 xl:block xl:space-y-4">
          <section aria-label="求职要求" className="rounded-2xl border border-[#ff8a2a]/40 bg-[#0c1730]/90 p-4">
            <p className="text-xs tracking-widest text-[#ff8a2a]">PREFERENCES</p>
            <h2 className="mt-1 text-lg font-semibold text-white">求职要求</h2>
            <p className="mt-2 text-xs leading-5 text-[#9fb4d4]">保留简历原话，面试前核对双方期望。</p>
            {profile ? profile.resume_filename?.toLowerCase().endsWith(".pdf") ? <p className="mt-4 text-sm leading-6 text-[#9fb4d4]">请在中间 PDF 原件中核对加班意愿、加班费和薪资要求；当前未读取 PDF 文字。</p> : resumeTextLoading ? <p className="mt-4 text-sm text-[#9fb4d4]">正在读取求职要求…</p> : resumeTextError ? <p className="mt-4 text-sm text-[#ffd0a8]">简历暂时无法读取，请核对原件。</p> : <dl className="mt-4 space-y-3">
              {resumeRequirements.map(({ label, quotes }) => <div key={label} className="rounded-xl border border-[#2f6fed]/30 bg-[#050912]/60 p-3"><dt className="text-xs font-medium text-[#ff8a2a]">{label}</dt><dd className="mt-2 space-y-2 text-sm leading-6 text-white">{quotes.length ? quotes.map((quote, index) => <p key={index} className="whitespace-pre-wrap break-words">{quote}</p>) : <span className="text-[#9fb4d4]">未注明</span>}</dd></div>)}
            </dl> : <p className="mt-4 text-sm text-[#9fb4d4]">选择学生后查看简历中的求职要求。</p>}
          </section>
        <section className="rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730]/90 p-4 shadow-[0_0_24px_rgba(47,111,237,0.2)]">
          <h2 className="text-lg text-white">面试能力评分</h2>
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
        </aside>
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
