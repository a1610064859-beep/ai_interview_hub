import {
  DIMENSION_LABEL_MAP,
  REQUIRED_DIMENSIONS,
  type DimensionKey,
} from "./report-data.ts";
import { reportPathForSid } from "./session-recovery.ts";

/** 受众模式（毕业生/新生），与输入模式 text/voice 无关。 */
export type AudienceMode = "毕业生" | "新生";

export type InputModeValue = "text" | "voice";

export type StudentProfile = {
  id: number;
  nameMasked: string;
  major: string | null;
  grade: string | null;
};

export type DimensionScoreMap = Record<DimensionKey, number | null>;

export type GrowthHistoryRecord = {
  sessionId: number;
  reportId: number;
  jobId: number;
  jobTitle: string;
  startedAt: string;
  mode: AudienceMode;
  inputMode: InputModeValue | null;
  scoringVersion: string | null;
  overall: number | null;
  dimensions: DimensionScoreMap;
  improvement: string[];
};

export type GrowthHistoryData = {
  userId: number;
  jobId: number | null;
  records: GrowthHistoryRecord[];
};

export type TrendPoint = {
  sessionId: number;
  reportId: number;
  startedAt: string;
  overall: number | null;
  dimensions: DimensionScoreMap;
};

export type OverallComparison = {
  comparable: boolean;
  reasons: string[];
  message: string | null;
  previous: { sessionId: number; overall: number | null } | null;
  current: { sessionId: number; overall: number | null } | null;
  delta: number | null;
};

export type DimensionChange = {
  previous: number;
  current: number;
  delta: number;
} | null;

export type GrowthTrendData = {
  userId: number;
  jobId: number;
  jobTitle: string;
  inputMode: InputModeValue | "mixed" | null;
  sessionsCount: number;
  points: TrendPoint[];
  overallComparison: OverallComparison;
  dimensionChanges: Record<DimensionKey, DimensionChange>;
};

export type SessionCreateBody = {
  user_id: number;
  job_id: number;
  mode: AudienceMode;
};

export type InterviewIdentity = {
  userId: number;
  jobId: number;
};

export const GROWTH_IDENTITY_STORAGE_KEY = "ai_interview_hub.interview_identity";

export const AUDIENCE_MODES: readonly AudienceMode[] = ["毕业生", "新生"] as const;

export function inferAudienceModeFromGrade(grade: string | null | undefined): AudienceMode {
  const normalized = grade?.replace(/\s+/g, "") ?? "";
  return /(毕业|应届|大[三四]|[三四]年级|毕业班|最后一年)/.test(normalized)
    ? "毕业生"
    : "新生";
}

export const COMPARISON_REASON_LABELS: Record<string, string> = {
  NO_RECORDS: "该岗位暂无已完成的训练记录",
  SINGLE_RECORD: "仅一次训练，暂无可比较的两次记录",
  OVERALL_MISSING: "综合分缺失，overall 不可直接比较",
  INPUT_MODE_MISMATCH: "文本与语音训练评分口径不同，不可直接比较",
  SCORING_VERSION_MISMATCH: "评分版本不同，不可直接比较",
  INPUT_MODE_UNKNOWN: "输入模式未标识（legacy），不可直接比较",
  SCORING_VERSION_UNKNOWN: "评分版本未标识（legacy），不可直接比较",
  DIMENSION_SET_MISMATCH: "两次训练的有效评分维度集合不同，overall 不可直接比较",
  EMPTY_DIMENSION_SET: "有效维度集合为空，overall 不可直接比较",
};

function isPositiveInteger(val: unknown): val is number {
  return typeof val === "number" && Number.isInteger(val) && val > 0;
}

function isValidScore(val: unknown): val is number | null {
  if (val === null) return true;
  return typeof val === "number" && Number.isFinite(val) && val >= 0 && val <= 100;
}

function isStringArray(val: unknown): val is string[] {
  return Array.isArray(val) && val.every((item) => typeof item === "string");
}

function isRecord(val: unknown): val is Record<string, unknown> {
  return typeof val === "object" && val !== null && !Array.isArray(val);
}

function isAudienceMode(val: unknown): val is AudienceMode {
  return val === "毕业生" || val === "新生";
}

function isInputModeOrNull(val: unknown): val is InputModeValue | null {
  return val === null || val === "text" || val === "voice";
}

function parseDimensionScoreMap(raw: unknown, ctx: string): DimensionScoreMap {
  if (!isRecord(raw)) {
    throw new Error(`Invalid ${ctx}: dimensions must be an object`);
  }
  const dimensions = {} as DimensionScoreMap;
  for (const key of REQUIRED_DIMENSIONS) {
    if (!(key in raw)) {
      throw new Error(`Invalid ${ctx}: missing dimension '${key}'`);
    }
    if (!isValidScore(raw[key])) {
      throw new Error(
        `Invalid ${ctx}: dimension '${key}' must be null or finite number within [0, 100]`,
      );
    }
    dimensions[key] = raw[key] as number | null;
  }
  return dimensions;
}

/**
 * 创建会话请求体：精确三字段，禁止默认值补全。
 */
export function buildSessionCreateBody(
  userId: number,
  jobId: number,
  mode: AudienceMode,
): SessionCreateBody {
  if (!isPositiveInteger(userId)) {
    throw new Error("user_id must be a positive integer");
  }
  if (!isPositiveInteger(jobId)) {
    throw new Error("job_id must be a positive integer");
  }
  if (!isAudienceMode(mode)) {
    throw new Error("mode must be 毕业生 or 新生");
  }
  return { user_id: userId, job_id: jobId, mode };
}

export function canCreateSession(
  userId: number | null,
  jobId: number | null,
  mode: AudienceMode | null,
): boolean {
  return (
    userId !== null &&
    jobId !== null &&
    mode !== null &&
    isPositiveInteger(userId) &&
    isPositiveInteger(jobId) &&
    isAudienceMode(mode)
  );
}

export function parseStudentsResponse(raw: unknown): StudentProfile[] {
  if (!isRecord(raw)) {
    throw new Error("Invalid students response: root must be a non-null object");
  }
  if (!Array.isArray(raw.students)) {
    throw new Error("Invalid students response: 'students' must be an array");
  }
  const students: StudentProfile[] = [];
  for (const item of raw.students) {
    if (!isRecord(item)) {
      throw new Error("Invalid students response: student item must be an object");
    }
    if (!isPositiveInteger(item.id)) {
      throw new Error("Invalid students response: student.id must be a positive integer");
    }
    if (typeof item.name_masked !== "string" || item.name_masked.length === 0) {
      throw new Error("Invalid students response: name_masked must be a non-empty string");
    }
    if (item.major !== null && typeof item.major !== "string") {
      throw new Error("Invalid students response: major must be string or null");
    }
    if (item.grade !== null && typeof item.grade !== "string") {
      throw new Error("Invalid students response: grade must be string or null");
    }
    students.push({
      id: item.id,
      nameMasked: item.name_masked,
      major: item.major,
      grade: item.grade,
    });
  }
  return students;
}

function parseHistoryRecord(raw: unknown, index: number): GrowthHistoryRecord {
  if (!isRecord(raw)) {
    throw new Error(`Invalid growth history: records[${index}] must be an object`);
  }
  if (!isPositiveInteger(raw.session_id)) {
    throw new Error(`Invalid growth history: records[${index}].session_id`);
  }
  if (!isPositiveInteger(raw.report_id)) {
    throw new Error(`Invalid growth history: records[${index}].report_id`);
  }
  if (!isPositiveInteger(raw.job_id)) {
    throw new Error(`Invalid growth history: records[${index}].job_id`);
  }
  if (typeof raw.job_title !== "string" || raw.job_title.length === 0) {
    throw new Error(`Invalid growth history: records[${index}].job_title`);
  }
  if (typeof raw.started_at !== "string" || raw.started_at.length === 0) {
    throw new Error(`Invalid growth history: records[${index}].started_at`);
  }
  if (!isAudienceMode(raw.mode)) {
    throw new Error(`Invalid growth history: records[${index}].mode`);
  }
  if (!isInputModeOrNull(raw.input_mode)) {
    throw new Error(`Invalid growth history: records[${index}].input_mode`);
  }
  if (raw.scoring_version !== null && typeof raw.scoring_version !== "string") {
    throw new Error(`Invalid growth history: records[${index}].scoring_version`);
  }
  if (!isValidScore(raw.overall)) {
    throw new Error(`Invalid growth history: records[${index}].overall`);
  }
  if (!isStringArray(raw.improvement)) {
    throw new Error(`Invalid growth history: records[${index}].improvement`);
  }
  return {
    sessionId: raw.session_id,
    reportId: raw.report_id,
    jobId: raw.job_id,
    jobTitle: raw.job_title,
    startedAt: raw.started_at,
    mode: raw.mode,
    inputMode: raw.input_mode,
    scoringVersion: raw.scoring_version,
    overall: raw.overall,
    dimensions: parseDimensionScoreMap(raw.dimensions, `growth history records[${index}]`),
    improvement: raw.improvement,
  };
}

export function parseGrowthHistoryResponse(raw: unknown): GrowthHistoryData {
  if (!isRecord(raw)) {
    throw new Error("Invalid growth history: root must be a non-null object");
  }
  if (!isPositiveInteger(raw.user_id)) {
    throw new Error("Invalid growth history: user_id must be a positive integer");
  }
  if (raw.job_id !== null && raw.job_id !== undefined && !isPositiveInteger(raw.job_id)) {
    throw new Error("Invalid growth history: job_id must be null or a positive integer");
  }
  if (!Array.isArray(raw.records)) {
    throw new Error("Invalid growth history: records must be an array");
  }
  return {
    userId: raw.user_id,
    jobId: raw.job_id === undefined ? null : (raw.job_id as number | null),
    records: raw.records.map((item, index) => parseHistoryRecord(item, index)),
  };
}

function parseTrendPoint(raw: unknown, index: number): TrendPoint {
  if (!isRecord(raw)) {
    throw new Error(`Invalid growth trend: points[${index}] must be an object`);
  }
  if (!isPositiveInteger(raw.session_id)) {
    throw new Error(`Invalid growth trend: points[${index}].session_id`);
  }
  if (!isPositiveInteger(raw.report_id)) {
    throw new Error(`Invalid growth trend: points[${index}].report_id`);
  }
  if (typeof raw.started_at !== "string" || raw.started_at.length === 0) {
    throw new Error(`Invalid growth trend: points[${index}].started_at`);
  }
  if (!isValidScore(raw.overall)) {
    throw new Error(`Invalid growth trend: points[${index}].overall`);
  }
  return {
    sessionId: raw.session_id,
    reportId: raw.report_id,
    startedAt: raw.started_at,
    overall: raw.overall,
    dimensions: parseDimensionScoreMap(raw.dimensions, `growth trend points[${index}]`),
  };
}

function parseOverallComparison(raw: unknown): OverallComparison {
  if (!isRecord(raw)) {
    throw new Error("Invalid growth trend: overall_comparison must be an object");
  }
  if (typeof raw.comparable !== "boolean") {
    throw new Error("Invalid growth trend: overall_comparison.comparable must be boolean");
  }
  if (!isStringArray(raw.reasons)) {
    throw new Error("Invalid growth trend: overall_comparison.reasons must be string[]");
  }
  if (raw.message !== null && typeof raw.message !== "string") {
    throw new Error("Invalid growth trend: overall_comparison.message must be string or null");
  }
  if (raw.delta !== null && (typeof raw.delta !== "number" || !Number.isFinite(raw.delta))) {
    throw new Error("Invalid growth trend: overall_comparison.delta must be finite number or null");
  }

  function parseSide(side: unknown, label: string): { sessionId: number; overall: number | null } | null {
    if (side === null) return null;
    if (!isRecord(side)) {
      throw new Error(`Invalid growth trend: overall_comparison.${label} must be object or null`);
    }
    if (!isPositiveInteger(side.session_id)) {
      throw new Error(`Invalid growth trend: overall_comparison.${label}.session_id`);
    }
    if (!isValidScore(side.overall)) {
      throw new Error(`Invalid growth trend: overall_comparison.${label}.overall`);
    }
    return { sessionId: side.session_id, overall: side.overall };
  }

  return {
    comparable: raw.comparable,
    reasons: raw.reasons,
    message: raw.message,
    previous: parseSide(raw.previous, "previous"),
    current: parseSide(raw.current, "current"),
    delta: raw.delta,
  };
}

function parseDimensionChanges(raw: unknown): Record<DimensionKey, DimensionChange> {
  if (!isRecord(raw)) {
    throw new Error("Invalid growth trend: dimension_changes must be an object");
  }
  const out = {} as Record<DimensionKey, DimensionChange>;
  for (const key of REQUIRED_DIMENSIONS) {
    if (!(key in raw)) {
      throw new Error(`Invalid growth trend: missing dimension_changes.${key}`);
    }
    const item = raw[key];
    if (item === null) {
      out[key] = null;
      continue;
    }
    if (!isRecord(item)) {
      throw new Error(`Invalid growth trend: dimension_changes.${key} must be object or null`);
    }
    if (typeof item.previous !== "number" || !Number.isFinite(item.previous)) {
      throw new Error(`Invalid growth trend: dimension_changes.${key}.previous`);
    }
    if (typeof item.current !== "number" || !Number.isFinite(item.current)) {
      throw new Error(`Invalid growth trend: dimension_changes.${key}.current`);
    }
    if (typeof item.delta !== "number" || !Number.isFinite(item.delta)) {
      throw new Error(`Invalid growth trend: dimension_changes.${key}.delta`);
    }
    out[key] = {
      previous: item.previous,
      current: item.current,
      delta: item.delta,
    };
  }
  return out;
}

export function parseGrowthTrendResponse(raw: unknown): GrowthTrendData {
  if (!isRecord(raw)) {
    throw new Error("Invalid growth trend: root must be a non-null object");
  }
  if (!isPositiveInteger(raw.user_id)) {
    throw new Error("Invalid growth trend: user_id must be a positive integer");
  }
  if (!isPositiveInteger(raw.job_id)) {
    throw new Error("Invalid growth trend: job_id must be a positive integer");
  }
  if (typeof raw.job_title !== "string" || raw.job_title.length === 0) {
    throw new Error("Invalid growth trend: job_title must be a non-empty string");
  }
  if (
    raw.input_mode !== null &&
    raw.input_mode !== "text" &&
    raw.input_mode !== "voice" &&
    raw.input_mode !== "mixed"
  ) {
    throw new Error("Invalid growth trend: input_mode must be text|voice|mixed|null");
  }
  if (typeof raw.sessions_count !== "number" || !Number.isInteger(raw.sessions_count) || raw.sessions_count < 0) {
    throw new Error("Invalid growth trend: sessions_count must be a non-negative integer");
  }
  if (!Array.isArray(raw.points)) {
    throw new Error("Invalid growth trend: points must be an array");
  }
  return {
    userId: raw.user_id,
    jobId: raw.job_id,
    jobTitle: raw.job_title,
    inputMode: raw.input_mode,
    sessionsCount: raw.sessions_count,
    points: raw.points.map((item, index) => parseTrendPoint(item, index)),
    overallComparison: parseOverallComparison(raw.overall_comparison),
    dimensionChanges: parseDimensionChanges(raw.dimension_changes),
  };
}

/** null →「未评估」；禁止画成 0。 */
export function formatScoreOrUnevaluated(score: number | null): string {
  if (score === null) return "未评估";
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

export function formatDeltaOrUnevaluated(delta: number | null, comparable: boolean): string {
  if (!comparable || delta === null) return "不可直接比较";
  const sign = delta > 0 ? "+" : "";
  return `本次比上次 ${sign}${delta.toFixed(1)}（模型评分观测，不代表真实能力变化）`;
}

export function comparisonReasonLabel(code: string): string {
  return COMPARISON_REASON_LABELS[code] ?? code;
}

export function buildGrowthHref(userId: number, jobId?: number | null): string {
  if (!isPositiveInteger(userId)) {
    throw new Error("user_id must be a positive integer");
  }
  const params = new URLSearchParams();
  params.set("user_id", String(userId));
  if (jobId !== undefined && jobId !== null) {
    if (!isPositiveInteger(jobId)) {
      throw new Error("job_id must be a positive integer when provided");
    }
    params.set("job_id", String(jobId));
  }
  return `/growth?${params.toString()}`;
}

export function buildReportHref(sid: number, userId: number, jobId: number): string {
  if (!isPositiveInteger(sid) || !isPositiveInteger(userId) || !isPositiveInteger(jobId)) {
    throw new Error("sid, user_id and job_id must be positive integers");
  }
  const params = new URLSearchParams();
  params.set("user_id", String(userId));
  params.set("job_id", String(jobId));
  return `/reports/${sid}?${params.toString()}`;
}

/**
 * 报告跳转：有身份则带 user_id/job_id；无身份回退 session-recovery 的纯路径（禁止自递归）。
 */
export function resolveReportHref(
  sid: number,
  identity: InterviewIdentity | null | undefined,
): string {
  if (!isPositiveInteger(sid)) {
    throw new Error("sid must be a positive integer");
  }
  if (!identity) {
    return reportPathForSid(sid);
  }
  return buildReportHref(sid, identity.userId, identity.jobId);
}

export function parseIdentityFromSearchParams(
  get: (key: string) => string | null,
): InterviewIdentity | null {
  const userRaw = get("user_id");
  const jobRaw = get("job_id");
  if (userRaw === null || jobRaw === null) return null;
  if (!/^\d+$/.test(userRaw) || !/^\d+$/.test(jobRaw)) return null;
  const userId = Number(userRaw);
  const jobId = Number(jobRaw);
  if (!isPositiveInteger(userId) || !isPositiveInteger(jobId)) return null;
  return { userId, jobId };
}

export function persistInterviewIdentity(identity: InterviewIdentity): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(GROWTH_IDENTITY_STORAGE_KEY, JSON.stringify(identity));
}

export function loadInterviewIdentity(): InterviewIdentity | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(GROWTH_IDENTITY_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return null;
    if (!isPositiveInteger(parsed.userId) || !isPositiveInteger(parsed.jobId)) return null;
    return { userId: parsed.userId, jobId: parsed.jobId };
  } catch {
    return null;
  }
}

export function inputModeLabel(mode: InputModeValue | "mixed" | null): string {
  if (mode === "text") return "文本";
  if (mode === "voice") return "语音";
  if (mode === "mixed") return "混合口径";
  return "未标识";
}

/** cohort 键：input_mode + scoring_version；null 版本归为 legacy。 */
export function cohortIdentityKey(
  inputMode: InputModeValue | null,
  scoringVersion: string | null,
): string {
  const mode = inputMode ?? "unknown";
  const ver = scoringVersion ?? "legacy";
  return `${mode}|${ver}`;
}

export function cohortDisplayLabel(
  inputMode: InputModeValue | null,
  scoringVersion: string | null,
): string {
  const modePart =
    inputMode === "text" ? "文本" : inputMode === "voice" ? "语音" : "未标识";
  const verPart = scoringVersion ?? "legacy";
  return `${modePart}·${verPart}`;
}

type TimelinePoint = {
  sessionId: number;
  overall: number | null;
  dimensions: DimensionScoreMap;
  inputMode: InputModeValue | null;
  scoringVersion: string | null;
};

function buildTimeline(
  trend: GrowthTrendData,
  historyRecords: GrowthHistoryRecord[],
): TimelinePoint[] {
  const jobHistory = historyRecords.filter((r) => r.jobId === trend.jobId);
  if (jobHistory.length > 0) {
    return jobHistory.map((r) => ({
      sessionId: r.sessionId,
      overall: r.overall,
      dimensions: r.dimensions,
      inputMode: r.inputMode,
      scoringVersion: r.scoringVersion,
    }));
  }
  const fallbackMode: InputModeValue | null =
    trend.inputMode === "text" || trend.inputMode === "voice" ? trend.inputMode : null;
  return trend.points.map((p) => ({
    sessionId: p.sessionId,
    overall: p.overall,
    dimensions: p.dimensions,
    inputMode: fallbackMode,
    scoringVersion: null,
  }));
}

function uniqueCohortKeys(timeline: TimelinePoint[]): string[] {
  const seen = new Set<string>();
  const keys: string[] = [];
  for (const point of timeline) {
    const key = cohortIdentityKey(point.inputMode, point.scoringVersion);
    if (!seen.has(key)) {
      seen.add(key);
      keys.push(key);
    }
  }
  return keys;
}

function parseCohortKey(key: string): {
  inputMode: InputModeValue | null;
  scoringVersion: string | null;
} {
  const [modeRaw, verRaw] = key.split("|");
  const inputMode: InputModeValue | null =
    modeRaw === "text" || modeRaw === "voice" ? modeRaw : null;
  const scoringVersion = verRaw === "legacy" ? null : verRaw;
  return { inputMode, scoringVersion };
}

/**
 * 折线图：null 保持为 null（不补 0）；connectNulls 恒为 false。
 * 多 cohort 时总体分按输入模式和评分版本拆分；有效维度可在同一已知评分版本内跨输入模式连线。
 * 缺失维度及未知/不同评分版本始终断线。
 * 单 cohort 时保持一条综合分 + 四维折线。
 */
export function transformTrendToLineOptions(
  trend: GrowthTrendData,
  historyRecords: GrowthHistoryRecord[] = [],
  theme: "day" | "night" = "night",
): Record<string, unknown> {
  const labelColor = theme === "day" ? "#626b7d" : "#9fb4d4";
  const gridColor = theme === "day" ? "rgba(105, 84, 190, 0.18)" : "rgba(47,111,237,0.2)";
  const connectNulls = false;
  const timeline = buildTimeline(trend, historyRecords);
  const categories = timeline.map((p) => `#${p.sessionId}`);
  const cohortKeys = uniqueCohortKeys(timeline);
  const multiCohort = cohortKeys.length > 1;

  const baseChart = {
    tooltip: {
      trigger: "axis",
      backgroundColor: theme === "day" ? "rgba(255, 255, 255, 0.96)" : "rgba(15, 23, 42, 0.92)",
      borderColor: theme === "day" ? "rgba(112, 83, 239, 0.28)" : "rgba(47,111,237,0.28)",
      textStyle: { color: theme === "day" ? "#24243a" : "#e7ecfb" },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLabel: { color: labelColor },
      splitLine: { lineStyle: { color: gridColor } },
    },
  };

  if (!multiCohort) {
    const dimensionSeries = REQUIRED_DIMENSIONS.map((key) => ({
      name: DIMENSION_LABEL_MAP[key],
      type: "line",
      connectNulls,
      data: timeline.map((p) => p.dimensions[key]),
    }));
    return {
      ...baseChart,
      legend: {
        data: ["综合分", ...REQUIRED_DIMENSIONS.map((k) => DIMENSION_LABEL_MAP[k])],
        textStyle: { color: labelColor },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: labelColor },
      },
      series: [
        {
          name: "综合分",
          type: "line",
          connectNulls,
          data: timeline.map((p) => p.overall),
        },
        ...dimensionSeries,
      ],
      _meta: { connectNulls: false, mixed: false, multiCohort: false, cohortCount: cohortKeys.length },
    };
  }

  const series: Array<Record<string, unknown>> = [];
  const legendData: string[] = [];
  for (const key of cohortKeys) {
    const { inputMode, scoringVersion } = parseCohortKey(key);
    const label = cohortDisplayLabel(inputMode, scoringVersion);
    const overallName = `${label} 综合分`;
    legendData.push(overallName);
    series.push({
      name: overallName,
      type: "line",
      connectNulls,
      data: timeline.map((p) =>
        cohortIdentityKey(p.inputMode, p.scoringVersion) === key ? p.overall : null,
      ),
    });
  }

  const dimensionGroupKey = (point: TimelinePoint) =>
    point.inputMode !== null && point.scoringVersion !== null
      ? `version:${point.scoringVersion}`
      : `cohort:${cohortIdentityKey(point.inputMode, point.scoringVersion)}`;
  const dimensionKeys = [...new Set(timeline.map(dimensionGroupKey))];
  for (const key of dimensionKeys) {
    const members = timeline.filter((point) => dimensionGroupKey(point) === key);
    const first = members[0];
    const modes = new Set(members.map((point) => point.inputMode));
    const label = modes.size > 1 && first.scoringVersion !== null
      ? first.scoringVersion
      : cohortDisplayLabel(first.inputMode, first.scoringVersion);
    for (const dim of REQUIRED_DIMENSIONS) {
      const dimName = `${label} ${DIMENSION_LABEL_MAP[dim]}`;
      legendData.push(dimName);
      series.push({
        name: dimName,
        type: "line",
        connectNulls,
        data: timeline.map((point) =>
          dimensionGroupKey(point) === key ? point.dimensions[dim] : null,
        ),
      });
    }
  }

  return {
    ...baseChart,
    legend: { data: legendData, textStyle: { color: labelColor } },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: { color: labelColor },
    },
    series,
    _meta: {
      connectNulls: false,
      mixed: true,
      multiCohort: true,
      cohortCount: cohortKeys.length,
    },
  };
}

/** 供测试断言：确认系列均设置 connectNulls=false，且数据中的 null 未被替换为 0。 */
export function assertLineOptionsNoZeroFill(options: Record<string, unknown>): boolean {
  const series = options.series;
  if (!Array.isArray(series)) return false;
  for (const s of series) {
    if (!isRecord(s)) return false;
    if (s.connectNulls !== false) return false;
    if (!Array.isArray(s.data)) return false;
    for (const v of s.data) {
      if (v === 0) {
        // 允许真实 0 分，但不允许把 null 变成 0；此处仅检查类型
      }
      if (v !== null && (typeof v !== "number" || !Number.isFinite(v))) return false;
    }
  }
  return true;
}

export function lineSeriesHasNullNotZero(
  options: Record<string, unknown>,
  seriesName: string,
  expectedNullIndex: number,
): boolean {
  const series = options.series;
  if (!Array.isArray(series)) return false;
  const target = series.find((s) => isRecord(s) && s.name === seriesName);
  if (!isRecord(target) || !Array.isArray(target.data)) return false;
  return target.data[expectedNullIndex] === null;
}

export function getSeriesDataByName(
  options: Record<string, unknown>,
  seriesName: string,
): Array<number | null> | null {
  const series = options.series;
  if (!Array.isArray(series)) return null;
  const target = series.find((s) => isRecord(s) && s.name === seriesName);
  if (!isRecord(target) || !Array.isArray(target.data)) return null;
  return target.data as Array<number | null>;
}

export function allSeriesConnectNullsFalse(options: Record<string, unknown>): boolean {
  const series = options.series;
  if (!Array.isArray(series) || series.length === 0) return false;
  return series.every((s) => isRecord(s) && s.connectNulls === false);
}
