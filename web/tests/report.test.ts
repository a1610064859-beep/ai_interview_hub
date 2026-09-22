import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  parseReportResponse,
  transformDimensionsToRadar,
  isTextModeReport,
  radarDegradeBadge,
  reportModeHint,
  TEXT_MODE_FLUENCY_REASON,
  type DimensionData,
  type ReportData,
} from "../lib/report-data.ts";
import {
  AUDIENCE_MODES,
  allSeriesConnectNullsFalse,
  assertLineOptionsNoZeroFill,
  buildGrowthHref,
  buildReportHref,
  buildSessionCreateBody,
  canCreateSession,
  cohortDisplayLabel,
  cohortIdentityKey,
  comparisonReasonLabel,
  formatDeltaOrUnevaluated,
  formatScoreOrUnevaluated,
  getSeriesDataByName,
  lineSeriesHasNullNotZero,
  parseGrowthHistoryResponse,
  parseGrowthTrendResponse,
  parseStudentsResponse,
  resolveReportHref,
  transformTrendToLineOptions,
  type GrowthHistoryRecord,
  type GrowthTrendData,
} from "../lib/growth-data.ts";

function baseDimensions(
  overrides: Partial<Record<keyof ReportData["dimensions"], Partial<DimensionData>>> = {},
): ReportData["dimensions"] {
  const base: ReportData["dimensions"] = {
    professional_match: { score: 89, evidence: "使用CANoe分析报文", reason: "工具契合" },
    logic_structure: { score: 83, evidence: "分析报文时间戳", reason: "时序清晰" },
    expression_fluency: { score: 80, evidence: "语速稳定", reason: "表达顺畅" },
    job_competence: { score: 85, evidence: "具备安全底线意识", reason: "安全意识强" },
  };
  for (const key of Object.keys(overrides) as (keyof ReportData["dimensions"])[]) {
    base[key] = { ...base[key], ...overrides[key] };
  }
  return base;
}

function baseReport(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    session_id: 2,
    job_title: "智驾测试",
    overall: 85.7,
    dimensions: baseDimensions(),
    highlights: ["工具链契合"],
    concerns: ["边缘场景偏弱"],
    improvement: ["强化以太网实操"],
    ...overrides,
  };
}

describe("transformDimensionsToRadar", () => {
  it("R-T01: 4 维有效时绘制四轴雷达", () => {
    const result = transformDimensionsToRadar(baseDimensions());
    assert.equal(result.canRenderRadar, true);
    assert.equal(result.validCount, 4);
    assert.ok(result.radarOptions);
    const indicator = (result.radarOptions!.radar as { indicator: unknown[] }).indicator;
    assert.equal(indicator.length, 4);
  });

  it("R-T02: 文本模式剔除 expression_fluency，不补 0", () => {
    const result = transformDimensionsToRadar(
      baseDimensions({
        expression_fluency: {
          score: null,
          evidence: null,
          reason: "文本模式，未评估语音流畅度",
        },
      }),
    );
    assert.equal(result.canRenderRadar, true);
    assert.equal(result.validCount, 3);
    const indicator = (result.radarOptions!.radar as { indicator: { name: string }[] }).indicator;
    assert.equal(indicator.length, 3);
    assert.ok(!indicator.some((item) => item.name === "表达流畅度"));
    const values = (
      result.radarOptions!.series as { data: { value: number[] }[] }[]
    )[0].data[0].value;
    assert.equal(values.length, 3);
    assert.ok(!values.includes(0) || values.every((v) => v > 0));
  });

  it("R-T03: 有效维度不足 3 时隐藏雷达", () => {
    const result = transformDimensionsToRadar(
      baseDimensions({
        professional_match: { score: 90 },
        logic_structure: { score: null, evidence: null, reason: "缺失" },
        expression_fluency: { score: null, evidence: null, reason: "缺失" },
        job_competence: { score: null, evidence: null, reason: "缺失" },
      }),
    );
    assert.equal(result.canRenderRadar, false);
    assert.equal(result.radarOptions, null);
    assert.ok(result.validCount < 3);
  });

  it("R-T04: 全部维度 null 时不抛错并隐藏雷达", () => {
    const result = transformDimensionsToRadar(
      baseDimensions({
        professional_match: { score: null, evidence: null, reason: "未评估" },
        logic_structure: { score: null, evidence: null, reason: "未评估" },
        expression_fluency: { score: null, evidence: null, reason: "未评估" },
        job_competence: { score: null, evidence: null, reason: "未评估" },
      }),
    );
    assert.equal(result.canRenderRadar, false);
    assert.equal(result.validCount, 0);
    assert.equal(result.radarOptions, null);
  });
});

describe("parseReportResponse", () => {
  it("R-T05: evidence 原文字面值无损保留", () => {
    const evidence = "  CANoe,报文!  ";
    assert.ok(evidence.length >= 1 && evidence.length <= 25);
    const parsed = parseReportResponse(
      baseReport({
        dimensions: baseDimensions({
          professional_match: { evidence },
        }),
      }),
    );
    assert.equal(parsed.dimensions.professional_match.evidence, evidence);
  });

  it("R-T06: 非法顶层字段严格抛错", () => {
    assert.throws(() => parseReportResponse(null));
    assert.throws(() => parseReportResponse(baseReport({ id: 0 })));
    assert.throws(() => parseReportResponse(baseReport({ job_title: "" })));
    assert.throws(() => parseReportResponse(baseReport({ overall: 101 })));
    assert.throws(() => parseReportResponse(baseReport({ overall: Number.NaN })));
  });

  it("R-T07: 维度与数组成员类型错误严格抛错", () => {
    const dims = baseDimensions();
    const withoutMatch = { ...dims } as Record<string, unknown>;
    delete withoutMatch.professional_match;
    assert.throws(() => parseReportResponse(baseReport({ dimensions: withoutMatch })));
    assert.throws(() =>
      parseReportResponse(
        baseReport({
          dimensions: baseDimensions({ professional_match: { score: -1 } }),
        }),
      ),
    );
    assert.throws(() =>
      parseReportResponse(
        baseReport({
          dimensions: baseDimensions({ professional_match: { evidence: 12 as unknown as string } }),
        }),
      ),
    );
    assert.throws(() => parseReportResponse(baseReport({ highlights: ["ok", 1] })));
    assert.throws(() =>
      parseReportResponse(
        baseReport({
          dimensions: baseDimensions({
            professional_match: {
              evidence: "一二三四五六七八九十一二三四五六七八九十一二三四五六",
            },
          }),
        }),
      ),
    );
  });
});

describe("isTextModeReport / radarDegradeBadge", () => {
  it("R-T08: 仅文本模式 reason 才判定为文本模式；三维徽标区分文案", () => {
    const textDims = baseDimensions({
      expression_fluency: {
        score: null,
        evidence: null,
        reason: TEXT_MODE_FLUENCY_REASON,
      },
    });
    assert.equal(isTextModeReport(textDims), true);
    assert.equal(reportModeHint(true), "文本模式 · 表达流畅度未评估");
    assert.equal(
      radarDegradeBadge(3, true),
      "模式降级: 文本模式仅绘制 3 项有效维度",
    );

    const voiceMissingFluency = baseDimensions({
      expression_fluency: {
        score: null,
        evidence: null,
        reason: "声学特征不足，未能评估表达流畅度",
      },
    });
    assert.equal(isTextModeReport(voiceMissingFluency), false);
    assert.equal(reportModeHint(false), "能力评估报告");
    assert.equal(radarDegradeBadge(3, false), "模式降级: 1 项维度未评估");

    const missingProfessional = baseDimensions({
      professional_match: { score: null, evidence: null, reason: "校验未通过" },
    });
    assert.equal(isTextModeReport(missingProfessional), false);
    assert.equal(radarDegradeBadge(3, false), "模式降级: 1 项维度未评估");
    assert.equal(radarDegradeBadge(4, false), null);
  });
});

function baseDims(overrides: Partial<Record<string, number | null>> = {}): Record<string, number | null> {
  return {
    professional_match: 68,
    logic_structure: 72,
    expression_fluency: null,
    job_competence: 70,
    ...overrides,
  };
}

function historyRecord(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    session_id: 11,
    report_id: 11,
    job_id: 1,
    job_title: "智驾测试工程师",
    started_at: "2026-09-20T10:00:00",
    mode: "毕业生",
    input_mode: "text",
    scoring_version: "v1",
    overall: 70,
    dimensions: baseDims(),
    improvement: ["先给结论"],
    ...overrides,
  };
}

function trendPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 3,
    job_id: 1,
    job_title: "智驾测试工程师",
    input_mode: "text",
    sessions_count: 3,
    points: [
      {
        session_id: 11,
        report_id: 11,
        started_at: "2026-09-20T10:00:00",
        overall: 70,
        dimensions: baseDims(),
      },
      {
        session_id: 12,
        report_id: 12,
        started_at: "2026-09-20T16:00:00",
        overall: 72.5,
        dimensions: baseDims({ professional_match: 71, logic_structure: 74, job_competence: 72.5 }),
      },
      {
        session_id: 13,
        report_id: 13,
        started_at: "2026-09-21T09:00:00",
        overall: 75,
        dimensions: baseDims({ professional_match: 73, logic_structure: 76, job_competence: 76 }),
      },
    ],
    overall_comparison: {
      comparable: true,
      reasons: [],
      message: null,
      previous: { session_id: 12, overall: 72.5 },
      current: { session_id: 13, overall: 75 },
      delta: 2.5,
    },
    dimension_changes: {
      professional_match: { previous: 71, current: 73, delta: 2 },
      logic_structure: { previous: 74, current: 76, delta: 2 },
      expression_fluency: null,
      job_competence: { previous: 72.5, current: 76, delta: 3.5 },
    },
    ...overrides,
  };
}

describe("growth-data session create body", () => {
  it("G-T01: 请求体精确包含 user_id/job_id/mode 三项必填", () => {
    const body = buildSessionCreateBody(3, 1, "毕业生");
    assert.deepEqual(Object.keys(body).sort(), ["job_id", "mode", "user_id"]);
    assert.deepEqual(body, { user_id: 3, job_id: 1, mode: "毕业生" });
    assert.equal(canCreateSession(3, 1, "毕业生"), true);
    assert.equal(canCreateSession(null, 1, "毕业生"), false);
    assert.equal(canCreateSession(3, null, "新生"), false);
    assert.equal(canCreateSession(3, 1, null), false);
    assert.ok(AUDIENCE_MODES.includes("新生"));
  });
});

describe("growth-data students / isolation", () => {
  it("G-T02: 两学生解析互不串数据", () => {
    const students = parseStudentsResponse({
      students: [
        { id: 3, name_masked: "王*明", major: "车辆工程", grade: "大三" },
        { id: 4, name_masked: "李*华", major: "智能车辆工程", grade: "大二" },
      ],
    });
    assert.equal(students.length, 2);
    assert.equal(students[0].id, 3);
    assert.equal(students[1].id, 4);
    assert.equal(buildGrowthHref(3, 1).includes("user_id=3"), true);
    assert.equal(buildGrowthHref(4, 1).includes("user_id=4"), true);
    assert.equal(buildGrowthHref(3, 1).includes("user_id=4"), false);
  });
});

describe("growth-data history 0/1/3", () => {
  it("G-T03: 0/1/3 次历史解析与空列表", () => {
    const empty = parseGrowthHistoryResponse({ user_id: 3, job_id: 1, records: [] });
    assert.equal(empty.records.length, 0);

    const one = parseGrowthHistoryResponse({
      user_id: 3,
      job_id: 1,
      records: [historyRecord()],
    });
    assert.equal(one.records.length, 1);

    const three = parseGrowthHistoryResponse({
      user_id: 3,
      job_id: 1,
      records: [
        historyRecord({ session_id: 11 }),
        historyRecord({ session_id: 12, report_id: 12, overall: 72.5 }),
        historyRecord({ session_id: 13, report_id: 13, overall: 75 }),
      ],
    });
    assert.equal(three.records.length, 3);
    assert.equal(three.userId, 3);
  });
});

describe("growth-data null / connectNulls / incomparable", () => {
  it("G-T04: null 显示未评估且折线不补零、connectNulls=false", () => {
    assert.equal(formatScoreOrUnevaluated(null), "未评估");
    assert.equal(formatScoreOrUnevaluated(70), "70");
    const trend = parseGrowthTrendResponse(trendPayload());
    const options = transformTrendToLineOptions(trend);
    assert.equal(assertLineOptionsNoZeroFill(options), true);
    assert.equal(lineSeriesHasNullNotZero(options, "表达流畅度", 0), true);
    assert.equal((options._meta as { connectNulls: boolean }).connectNulls, false);
  });

  it("G-T05: 文本/语音不可比、版本不同、维度集合不同", () => {
    const mixed = parseGrowthTrendResponse(
      trendPayload({
        input_mode: "mixed",
        sessions_count: 2,
        points: [
          {
            session_id: 13,
            report_id: 13,
            started_at: "2026-09-21T09:00:00",
            overall: 75,
            dimensions: baseDims({ professional_match: 73, logic_structure: 76, job_competence: 76 }),
          },
          {
            session_id: 20,
            report_id: 20,
            started_at: "2026-09-22T15:00:00",
            overall: 78,
            dimensions: baseDims({
              professional_match: 75,
              logic_structure: 78,
              expression_fluency: 82,
              job_competence: 77,
            }),
          },
        ],
        overall_comparison: {
          comparable: false,
          reasons: ["INPUT_MODE_MISMATCH", "DIMENSION_SET_MISMATCH"],
          message: "文本与语音训练评分口径不同，overall 不可直接比较",
          previous: { session_id: 13, overall: 75 },
          current: { session_id: 20, overall: 78 },
          delta: null,
        },
        dimension_changes: {
          professional_match: { previous: 73, current: 75, delta: 2 },
          logic_structure: { previous: 76, current: 78, delta: 2 },
          expression_fluency: null,
          job_competence: { previous: 76, current: 77, delta: 1 },
        },
      }),
    );
    assert.equal(mixed.overallComparison.comparable, false);
    assert.ok(mixed.overallComparison.reasons.includes("INPUT_MODE_MISMATCH"));
    assert.equal(mixed.overallComparison.delta, null);
    assert.equal(formatDeltaOrUnevaluated(null, false), "不可直接比较");
    assert.equal(
      comparisonReasonLabel("INPUT_MODE_MISMATCH"),
      "文本与语音训练评分口径不同，不可直接比较",
    );

    const history: GrowthHistoryRecord[] = [
      {
        sessionId: 13,
        reportId: 13,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-21T09:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 75,
        dimensions: {
          professional_match: 73,
          logic_structure: 76,
          expression_fluency: null,
          job_competence: 76,
        },
        improvement: [],
      },
      {
        sessionId: 20,
        reportId: 20,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-22T15:00:00",
        mode: "毕业生",
        inputMode: "voice",
        scoringVersion: "v1",
        overall: 78,
        dimensions: {
          professional_match: 75,
          logic_structure: 78,
          expression_fluency: 82,
          job_competence: 77,
        },
        improvement: [],
      },
    ];
    const mixedOpts = transformTrendToLineOptions(mixed, history);
    assert.equal((mixedOpts._meta as { multiCohort: boolean }).multiCohort, true);
    assert.equal((mixedOpts._meta as { mixed: boolean }).mixed, true);
    assert.equal(assertLineOptionsNoZeroFill(mixedOpts), true);
    assert.equal(allSeriesConnectNullsFalse(mixedOpts), true);
    // text/voice 的 overall 与内容维度不跨模式连线
    const textOverall = getSeriesDataByName(mixedOpts, "文本·v1 综合分");
    const voiceOverall = getSeriesDataByName(mixedOpts, "语音·v1 综合分");
    const textProf = getSeriesDataByName(mixedOpts, "文本·v1 专业匹配度");
    assert.ok(textOverall && voiceOverall && textProf);
    assert.deepEqual(textOverall, [75, null]);
    assert.deepEqual(voiceOverall, [null, 78]);
    assert.deepEqual(textProf, [73, null]);
    assert.equal(voiceOverall[0], null);
    assert.equal(textOverall[1], null);

    const versionMismatch = parseGrowthTrendResponse(
      trendPayload({
        sessions_count: 2,
        overall_comparison: {
          comparable: false,
          reasons: ["SCORING_VERSION_MISMATCH"],
          message: "评分版本不同",
          previous: { session_id: 12, overall: 72.5 },
          current: { session_id: 13, overall: 75 },
          delta: null,
        },
      }),
    );
    assert.ok(versionMismatch.overallComparison.reasons.includes("SCORING_VERSION_MISMATCH"));

    const dimMismatch = parseGrowthTrendResponse(
      trendPayload({
        overall_comparison: {
          comparable: false,
          reasons: ["DIMENSION_SET_MISMATCH"],
          message: "有效维度集合不同",
          previous: { session_id: 12, overall: 68 },
          current: { session_id: 13, overall: 75 },
          delta: null,
        },
      }),
    );
    assert.ok(dimMismatch.overallComparison.reasons.includes("DIMENSION_SET_MISMATCH"));
    assert.equal(dimMismatch.overallComparison.delta, null);
  });

  it("G-T06: 单次记录不计算增减；报告与再次训练入口链接", () => {
    const single = parseGrowthTrendResponse(
      trendPayload({
        sessions_count: 1,
        points: [
          {
            session_id: 11,
            report_id: 11,
            started_at: "2026-09-20T10:00:00",
            overall: 70,
            dimensions: baseDims(),
          },
        ],
        overall_comparison: {
          comparable: false,
          reasons: ["SINGLE_RECORD"],
          message: "仅一次训练，暂无可比较的两次记录",
          previous: null,
          current: null,
          delta: null,
        },
        dimension_changes: {
          professional_match: null,
          logic_structure: null,
          expression_fluency: null,
          job_competence: null,
        },
      }),
    ) as GrowthTrendData;
    assert.equal(single.sessionsCount, 1);
    assert.equal(single.overallComparison.delta, null);
    assert.equal(formatDeltaOrUnevaluated(null, false), "不可直接比较");

    assert.equal(buildReportHref(11, 3, 1), "/reports/11?user_id=3&job_id=1");
    assert.equal(buildGrowthHref(3, 1), "/growth?user_id=3&job_id=1");
  });
});

describe("growth-data invalid responses", () => {
  it("G-T07: 非法响应严格抛错，不静默补默认值", () => {
    assert.throws(() => parseStudentsResponse(null));
    assert.throws(() => parseStudentsResponse({ students: [{ id: 0, name_masked: "x" }] }));
    assert.throws(() => parseGrowthHistoryResponse({ user_id: 3, records: "bad" }));
    assert.throws(() =>
      parseGrowthHistoryResponse({
        user_id: 3,
        job_id: 1,
        records: [historyRecord({ dimensions: { professional_match: 1 } })],
      }),
    );
    assert.throws(() => parseGrowthTrendResponse({ user_id: 3 }));
    assert.throws(() => buildSessionCreateBody(0, 1, "毕业生"));
  });
});

describe("growth-data report href + cohort 连线（Astra 定点）", () => {
  it("无身份报告地址不递归，精确返回 /reports/{sid}", () => {
    assert.equal(resolveReportHref(5, null), "/reports/5");
    assert.equal(resolveReportHref(12, undefined), "/reports/12");
  });

  it("有身份报告地址携带 user_id/job_id", () => {
    assert.equal(
      resolveReportHref(11, { userId: 3, jobId: 1 }),
      "/reports/11?user_id=3&job_id=1",
    );
    assert.equal(buildReportHref(11, 3, 1), "/reports/11?user_id=3&job_id=1");
  });

  it("text/voice 的 overall 与内容维度不跨模式连线", () => {
    const trend = parseGrowthTrendResponse(
      trendPayload({
        input_mode: "mixed",
        sessions_count: 2,
        points: [
          {
            session_id: 1,
            report_id: 1,
            started_at: "2026-09-20T10:00:00",
            overall: 70,
            dimensions: baseDims({ professional_match: 68 }),
          },
          {
            session_id: 2,
            report_id: 2,
            started_at: "2026-09-21T10:00:00",
            overall: 80,
            dimensions: baseDims({
              professional_match: 75,
              expression_fluency: 82,
            }),
          },
        ],
        overall_comparison: {
          comparable: false,
          reasons: ["INPUT_MODE_MISMATCH"],
          message: "不可比",
          previous: null,
          current: null,
          delta: null,
        },
      }),
    );
    const history: GrowthHistoryRecord[] = [
      {
        sessionId: 1,
        reportId: 1,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-20T10:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 70,
        dimensions: {
          professional_match: 68,
          logic_structure: 72,
          expression_fluency: null,
          job_competence: 70,
        },
        improvement: [],
      },
      {
        sessionId: 2,
        reportId: 2,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-21T10:00:00",
        mode: "毕业生",
        inputMode: "voice",
        scoringVersion: "v1",
        overall: 80,
        dimensions: {
          professional_match: 75,
          logic_structure: 72,
          expression_fluency: 82,
          job_competence: 70,
        },
        improvement: [],
      },
    ];
    const opts = transformTrendToLineOptions(trend, history);
    assert.deepEqual(getSeriesDataByName(opts, "文本·v1 综合分"), [70, null]);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v1 综合分"), [null, 80]);
    assert.deepEqual(getSeriesDataByName(opts, "文本·v1 专业匹配度"), [68, null]);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v1 专业匹配度"), [null, 75]);
    assert.equal(allSeriesConnectNullsFalse(opts), true);
  });

  it("voice-v1 与 voice-v2 不跨版本连线", () => {
    const trend = parseGrowthTrendResponse(
      trendPayload({
        input_mode: "voice",
        sessions_count: 2,
        points: [
          {
            session_id: 3,
            report_id: 3,
            started_at: "2026-09-20T10:00:00",
            overall: 71,
            dimensions: baseDims({ expression_fluency: 80 }),
          },
          {
            session_id: 4,
            report_id: 4,
            started_at: "2026-09-21T10:00:00",
            overall: 79,
            dimensions: baseDims({ expression_fluency: 85 }),
          },
        ],
        overall_comparison: {
          comparable: false,
          reasons: ["SCORING_VERSION_MISMATCH"],
          message: "版本不同",
          previous: null,
          current: null,
          delta: null,
        },
      }),
    );
    const history: GrowthHistoryRecord[] = [
      {
        sessionId: 3,
        reportId: 3,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-20T10:00:00",
        mode: "毕业生",
        inputMode: "voice",
        scoringVersion: "v1",
        overall: 71,
        dimensions: {
          professional_match: 68,
          logic_structure: 72,
          expression_fluency: 80,
          job_competence: 70,
        },
        improvement: [],
      },
      {
        sessionId: 4,
        reportId: 4,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-21T10:00:00",
        mode: "毕业生",
        inputMode: "voice",
        scoringVersion: "v2",
        overall: 79,
        dimensions: {
          professional_match: 68,
          logic_structure: 72,
          expression_fluency: 85,
          job_competence: 70,
        },
        improvement: [],
      },
    ];
    const opts = transformTrendToLineOptions(trend, history);
    assert.equal((opts._meta as { multiCohort: boolean }).multiCohort, true);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v1 综合分"), [71, null]);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v2 综合分"), [null, 79]);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v1 表达流畅度"), [80, null]);
    assert.deepEqual(getSeriesDataByName(opts, "语音·v2 表达流畅度"), [null, 85]);
  });

  it("legacy 与 v1 分离，不与 v1 连线", () => {
    assert.equal(cohortIdentityKey("voice", null), "voice|legacy");
    assert.equal(cohortDisplayLabel("voice", null), "语音·legacy");
    assert.equal(cohortIdentityKey("voice", "v1"), "voice|v1");

    const trend = parseGrowthTrendResponse(
      trendPayload({
        input_mode: "mixed",
        sessions_count: 2,
        points: [
          {
            session_id: 5,
            report_id: 5,
            started_at: "2026-09-20T10:00:00",
            overall: 66,
            dimensions: baseDims(),
          },
          {
            session_id: 6,
            report_id: 6,
            started_at: "2026-09-21T10:00:00",
            overall: 74,
            dimensions: baseDims({ professional_match: 72 }),
          },
        ],
        overall_comparison: {
          comparable: false,
          reasons: ["SCORING_VERSION_UNKNOWN"],
          message: "legacy",
          previous: null,
          current: null,
          delta: null,
        },
      }),
    );
    const history: GrowthHistoryRecord[] = [
      {
        sessionId: 5,
        reportId: 5,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-20T10:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: null,
        overall: 66,
        dimensions: {
          professional_match: 68,
          logic_structure: 72,
          expression_fluency: null,
          job_competence: 70,
        },
        improvement: [],
      },
      {
        sessionId: 6,
        reportId: 6,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-21T10:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 74,
        dimensions: {
          professional_match: 72,
          logic_structure: 72,
          expression_fluency: null,
          job_competence: 70,
        },
        improvement: [],
      },
    ];
    const opts = transformTrendToLineOptions(trend, history);
    assert.deepEqual(getSeriesDataByName(opts, "文本·legacy 综合分"), [66, null]);
    assert.deepEqual(getSeriesDataByName(opts, "文本·v1 综合分"), [null, 74]);
  });

  it("单 cohort 保持 overall + 四维折线", () => {
    const trend = parseGrowthTrendResponse(trendPayload());
    const history: GrowthHistoryRecord[] = [
      {
        sessionId: 11,
        reportId: 11,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-20T10:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 70,
        dimensions: {
          professional_match: 68,
          logic_structure: 72,
          expression_fluency: null,
          job_competence: 70,
        },
        improvement: [],
      },
      {
        sessionId: 12,
        reportId: 12,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-20T16:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 72.5,
        dimensions: {
          professional_match: 71,
          logic_structure: 74,
          expression_fluency: null,
          job_competence: 72.5,
        },
        improvement: [],
      },
      {
        sessionId: 13,
        reportId: 13,
        jobId: 1,
        jobTitle: "智驾测试工程师",
        startedAt: "2026-09-21T09:00:00",
        mode: "毕业生",
        inputMode: "text",
        scoringVersion: "v1",
        overall: 75,
        dimensions: {
          professional_match: 73,
          logic_structure: 76,
          expression_fluency: null,
          job_competence: 76,
        },
        improvement: [],
      },
    ];
    const opts = transformTrendToLineOptions(trend, history);
    assert.equal((opts._meta as { multiCohort: boolean }).multiCohort, false);
    assert.ok(getSeriesDataByName(opts, "综合分"));
    assert.ok(getSeriesDataByName(opts, "专业匹配度"));
    assert.equal(getSeriesDataByName(opts, "文本·v1 综合分"), null);
    assert.deepEqual(getSeriesDataByName(opts, "综合分"), [70, 72.5, 75]);
    assert.equal(allSeriesConnectNullsFalse(opts), true);
  });

  it("null 保持 null 不补零，且全部系列 connectNulls=false", () => {
    const trend = parseGrowthTrendResponse(trendPayload());
    const opts = transformTrendToLineOptions(trend);
    assert.equal(lineSeriesHasNullNotZero(opts, "表达流畅度", 0), true);
    assert.equal(lineSeriesHasNullNotZero(opts, "表达流畅度", 1), true);
    const fluency = getSeriesDataByName(opts, "表达流畅度");
    assert.ok(fluency);
    assert.equal(fluency[0], null);
    assert.equal(fluency[1], null);
    assert.equal(fluency[2], null);
    assert.equal(allSeriesConnectNullsFalse(opts), true);
    assert.equal((opts._meta as { connectNulls: boolean }).connectNulls, false);
  });
});
