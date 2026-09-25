export type DimensionKey =
  | "professional_match"
  | "logic_structure"
  | "expression_fluency"
  | "job_competence";

export interface DimensionData {
  score: number | null;
  evidence: string | null;
  reason: string;
}

export interface ReportData {
  id: number;
  session_id: number;
  job_title: string;
  overall: number | null;
  dimensions: Record<DimensionKey, DimensionData>;
  highlights: string[];
  concerns: string[];
  improvement: string[];
}

export interface RadarTransformResult {
  canRenderRadar: boolean;
  radarOptions: Record<string, unknown> | null;
  validCount: number;
}

export const REQUIRED_DIMENSIONS: readonly DimensionKey[] = [
  "professional_match",
  "logic_structure",
  "expression_fluency",
  "job_competence",
] as const;

export const DIMENSION_LABEL_MAP: Record<DimensionKey, string> = {
  professional_match: "专业匹配度",
  logic_structure: "逻辑结构",
  expression_fluency: "表达流畅度",
  job_competence: "岗位素养",
};

function isPositiveInteger(val: unknown): val is number {
  return typeof val === "number" && Number.isInteger(val) && val > 0;
}

function isValidScore(val: unknown): val is number | null {
  if (val === null) return true;
  return typeof val === "number" && Number.isFinite(val) && val >= 0 && val <= 100;
}

function isEvidence(val: unknown): val is string | null {
  if (val === null) return true;
  return typeof val === "string" && val.length >= 1 && val.length <= 25;
}

function isStringArray(val: unknown): val is string[] {
  return Array.isArray(val) && val.every((item) => typeof item === "string");
}

function isRecord(val: unknown): val is Record<string, unknown> {
  return typeof val === "object" && val !== null && !Array.isArray(val);
}

/**
 * 严格校验并解析后端报告响应；拒绝非法格式，严禁默认值掩盖坏响应。
 * evidence 原文字面值原样保留（含首尾空格与符号）。
 */
export function parseReportResponse(raw: unknown): ReportData {
  if (!isRecord(raw)) {
    throw new Error("Invalid report response: root must be a non-null object");
  }

  if (!isPositiveInteger(raw.id)) {
    throw new Error("Invalid report response: 'id' must be a positive integer");
  }
  if (!isPositiveInteger(raw.session_id)) {
    throw new Error("Invalid report response: 'session_id' must be a positive integer");
  }
  if (typeof raw.job_title !== "string" || raw.job_title.length === 0) {
    throw new Error("Invalid report response: 'job_title' must be a non-empty string");
  }
  if (!isValidScore(raw.overall)) {
    throw new Error(
      "Invalid report response: 'overall' must be null or finite number within [0, 100]",
    );
  }
  if (!isRecord(raw.dimensions)) {
    throw new Error("Invalid report response: 'dimensions' must be an object");
  }

  const dimensions = {} as ReportData["dimensions"];
  for (const key of REQUIRED_DIMENSIONS) {
    if (!(key in raw.dimensions)) {
      throw new Error(`Invalid report response: missing required dimension '${key}'`);
    }
    const d = raw.dimensions[key];
    if (!isRecord(d)) {
      throw new Error(`Invalid report response: dimension '${key}' must be an object`);
    }
    if (!isValidScore(d.score)) {
      throw new Error(
        `Invalid report response: dimension '${key}.score' must be null or finite number within [0, 100]`,
      );
    }
    if (!isEvidence(d.evidence)) {
      throw new Error(
        `Invalid report response: dimension '${key}.evidence' must be null or a string of length 1–25`,
      );
    }
    if (typeof d.reason !== "string") {
      throw new Error(`Invalid report response: dimension '${key}.reason' must be a string`);
    }
    dimensions[key] = {
      score: d.score,
      evidence: d.evidence,
      reason: d.reason,
    };
  }

  if (!isStringArray(raw.highlights)) {
    throw new Error("Invalid report response: 'highlights' must be an array of strings");
  }
  if (!isStringArray(raw.concerns)) {
    throw new Error("Invalid report response: 'concerns' must be an array of strings");
  }
  if (!isStringArray(raw.improvement)) {
    throw new Error("Invalid report response: 'improvement' must be an array of strings");
  }

  return {
    id: raw.id,
    session_id: raw.session_id,
    job_title: raw.job_title,
    overall: raw.overall,
    dimensions,
    highlights: raw.highlights,
    concerns: raw.concerns,
    improvement: raw.improvement,
  };
}

export function transformDimensionsToRadar(
  dimensions: Record<string, DimensionData>,
  theme: "day" | "night" = "night",
): RadarTransformResult {
  const validDims = REQUIRED_DIMENSIONS.filter((key) => {
    const d = dimensions[key];
    return d != null && typeof d.score === "number" && Number.isFinite(d.score);
  });
  const validCount = validDims.length;

  if (validCount < 3) {
    return {
      canRenderRadar: false,
      radarOptions: null,
      validCount,
    };
  }

  const isDay = theme === "day";
  const labelColor = isDay ? "#626b7d" : "#94A3B8";
  const gridColor = isDay ? "rgba(105, 84, 190, 0.2)" : "rgba(51, 65, 85, 0.5)";
  const indicators = validDims.map((key) => ({
    name: DIMENSION_LABEL_MAP[key],
    max: 100,
    min: 0,
    color: labelColor,
  }));
  const values = validDims.map((key) => dimensions[key].score as number);

  const radarOptions: Record<string, unknown> = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: isDay ? "rgba(255, 255, 255, 0.96)" : "rgba(15, 23, 42, 0.9)",
      borderColor: isDay ? "rgba(112, 83, 239, 0.35)" : "rgba(6, 182, 212, 0.4)",
      textStyle: { color: isDay ? "#24243a" : "#F8FAFC" },
    },
    radar: {
      indicator: indicators,
      shape: "polygon",
      splitNumber: 4,
      axisName: {
        color: labelColor,
        fontSize: 12,
        fontWeight: "bold",
      },
      splitLine: {
        lineStyle: { color: gridColor },
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: [
            isDay ? "rgba(112, 83, 239, 0.025)" : "rgba(15, 23, 42, 0.4)",
            isDay ? "rgba(238, 91, 190, 0.035)" : "rgba(30, 41, 59, 0.4)",
            isDay ? "rgba(112, 83, 239, 0.025)" : "rgba(15, 23, 42, 0.4)",
            isDay ? "rgba(238, 91, 190, 0.045)" : "rgba(30, 41, 59, 0.6)",
          ],
        },
      },
      axisLine: {
        lineStyle: { color: isDay ? "rgba(105, 84, 190, 0.28)" : "rgba(51, 65, 85, 0.6)" },
      },
    },
    series: [
      {
        name: "能力雷达",
        type: "radar",
        data: [
          {
            value: values,
            name: "本次评估得分",
            symbol: "circle",
            symbolSize: 6,
            itemStyle: {
              color: isDay ? "#7658ed" : "#06B6D4",
              borderColor: "#FFFFFF",
              borderWidth: 1.5,
            },
            lineStyle: {
              color: isDay ? "#7658ed" : "#06B6D4",
              width: 2.5,
              shadowColor: isDay ? "rgba(118, 88, 237, 0.34)" : "rgba(6, 182, 212, 0.5)",
              shadowBlur: 10,
            },
            areaStyle: {
              color: isDay ? "rgba(118, 88, 237, 0.22)" : "rgba(6, 182, 212, 0.28)",
            },
          },
        ],
      },
    ],
  };

  return {
    canRenderRadar: true,
    radarOptions,
    validCount,
  };
}

export function overallGrade(overall: number | null): string {
  if (overall === null) return "待评估";
  if (overall >= 90) return "卓越";
  if (overall >= 75) return "良好";
  if (overall >= 60) return "及格";
  return "待提升";
}

/** 后端文本模式流畅度缺失时的固定 reason 文案。 */
export const TEXT_MODE_FLUENCY_REASON = "文本模式，未评估语音流畅度";

/**
 * 仅当表达流畅度为空且 reason 明确声明文本模式时，才判定为文本面试报告。
 * 语音报告因声学数据缺失导致流畅度为 null 时不得误判。
 */
export function isTextModeReport(dimensions: ReportData["dimensions"]): boolean {
  const fluency = dimensions.expression_fluency;
  return fluency.score === null && fluency.reason === TEXT_MODE_FLUENCY_REASON;
}

/**
 * 三维雷达降级徽标：文本模式用专用文案，其他维度缺失用中性说明。
 */
export function radarDegradeBadge(
  validCount: number,
  isTextMode: boolean,
): string | null {
  if (validCount !== 3) return null;
  if (isTextMode) return "模式降级: 文本模式仅绘制 3 项有效维度";
  return "模式降级: 1 项维度未评估";
}

export function reportModeHint(isTextMode: boolean): string {
  return isTextMode ? "文本模式 · 表达流畅度未评估" : "能力评估报告";
}
