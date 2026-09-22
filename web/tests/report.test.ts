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
