import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  countPauses,
  levelToUnit,
  SILENCE_DB_THRESHOLD,
  SILENCE_RUN_SECONDS,
} from "../lib/recorder.ts";

const LOUD = -20; // 明显有声
const QUIET = -55; // 低于 -45dB 阈值的静音

function samples(count: number, db: number): number[] {
  return Array.from({ length: count }, () => db);
}

describe("countPauses（AGENTS §6.3：<-45dB 持续 >1.5s 计 1 次停顿）", () => {
  it("全程有声 → 0 次停顿", () => {
    assert.equal(countPauses(samples(50, LOUD), 0.1), 0);
  });

  it("静音但未超过 1.5s → 0 次停顿", () => {
    // 1.4s 静音（14 个 0.1s 采样）
    const seq = [...samples(5, LOUD), ...samples(14, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("恰好 1.5s 静音不计数（阈值是严格大于）", () => {
    const seq = [...samples(5, LOUD), ...samples(15, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("超过 1.5s 的静音 → 1 次停顿", () => {
    const seq = [...samples(5, LOUD), ...samples(16, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 1);
  });

  it("一段很长的静音只计 1 次（不重复累计）", () => {
    const seq = [...samples(5, LOUD), ...samples(80, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 1);
  });

  it("两段独立静音 → 2 次停顿", () => {
    const seq = [
      ...samples(5, LOUD),
      ...samples(20, QUIET),
      ...samples(8, LOUD),
      ...samples(20, QUIET),
      ...samples(5, LOUD),
    ];
    assert.equal(countPauses(seq, 0.1), 2);
  });

  it("阈值边界：-45dB 本身不算静音（严格小于）", () => {
    const seq = [...samples(5, LOUD), ...samples(30, SILENCE_DB_THRESHOLD), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("非法采样间隔 → 0", () => {
    assert.equal(countPauses(samples(10, QUIET), 0), 0);
    assert.equal(countPauses(samples(10, QUIET), -0.1), 0);
  });

  it("阈值与时长常量与 AGENTS §6.3 一致", () => {
    assert.equal(SILENCE_DB_THRESHOLD, -45);
    assert.equal(SILENCE_RUN_SECONDS, 1.5);
  });
});

describe("levelToUnit（电平环归一化）", () => {
  it("映射 -60..0 dB → 0..1", () => {
    assert.equal(levelToUnit(-60), 0);
    assert.equal(levelToUnit(-30), 0.5);
    assert.equal(levelToUnit(0), 1);
  });

  it("越界值被钳制", () => {
    assert.equal(levelToUnit(-120), 0);
    assert.equal(levelToUnit(10), 1);
  });
});

describe("parseSessionResponse（会话创建与过渡语数组提取）", () => {
  it("正常解析包含 transition_audio_urls 的会话响应", async () => {
    const { parseSessionResponse } = await import("../lib/recorder.ts");
    const raw = {
      sid: 1,
      question: {
        text: "请介绍你的专业背景？",
        audio_url: "/audio/sess_1_q1.mp3",
        seq: 1,
      },
      transition_audio_urls: [
        "/audio/sess_1_trans_0.mp3",
        "/audio/sess_1_trans_1.mp3",
      ],
    };
    const res = parseSessionResponse(raw);
    assert.equal(res.ok, true);
    if (res.ok) {
      assert.equal(res.value.sid, 1);
      assert.equal(res.value.question.text, "请介绍你的专业背景？");
      assert.equal(res.value.question.audioUrl, "/audio/sess_1_q1.mp3");
      assert.equal(res.value.question.seq, 1);
      assert.deepEqual(res.value.transitionAudioUrls, [
        "/audio/sess_1_trans_0.mp3",
        "/audio/sess_1_trans_1.mp3",
      ]);
    }
  });

  it("缺失 transition_audio_urls 时降级为空数组，不报错", async () => {
    const { parseSessionResponse } = await import("../lib/recorder.ts");
    const raw = {
      sid: 2,
      question: {
        text: "请回答第二题",
        audio_url: null,
        seq: 2,
      },
    };
    const res = parseSessionResponse(raw);
    assert.equal(res.ok, true);
    if (res.ok) {
      assert.deepEqual(res.value.transitionAudioUrls, []);
    }
  });

  it("非法 sid 或 question 严格拒绝", async () => {
    const { parseSessionResponse } = await import("../lib/recorder.ts");
    assert.equal(parseSessionResponse({ sid: 0, question: {} }).ok, false);
    assert.equal(parseSessionResponse({ sid: 1, question: { text: "", seq: 1 } }).ok, false);
    assert.equal(parseSessionResponse(null).ok, false);
  });
});

describe("parseAnswerResponse（回答推进与过渡语响应解析）", () => {
  it("正常解析 followup 响应与过渡音频", async () => {
    const { parseAnswerResponse } = await import("../lib/recorder.ts");
    const raw = {
      type: "followup",
      question: {
        text: "能否进一步展开说明？",
        audio_url: "/audio/sess_1_f1.mp3",
        seq: 1,
      },
      transition_audio_url: "/audio/sess_1_trans_0.mp3",
    };
    const res = parseAnswerResponse(raw);
    assert.equal(res.ok, true);
    if (res.ok) {
      assert.equal(res.value.type, "followup");
      if (res.value.type === "followup") {
        assert.equal(res.value.question.text, "能否进一步展开说明？");
        assert.equal(res.value.transitionAudioUrl, "/audio/sess_1_trans_0.mp3");
      }
    }
  });

  it("正常解析 done 响应与 report_id", async () => {
    const { parseAnswerResponse } = await import("../lib/recorder.ts");
    const raw = {
      type: "done",
      report_id: 10,
      transition_audio_url: null,
    };
    const res = parseAnswerResponse(raw);
    assert.equal(res.ok, true);
    if (res.ok) {
      assert.equal(res.value.type, "done");
      if (res.value.type === "done") {
        assert.equal(res.value.reportId, 10);
        assert.equal(res.value.transitionAudioUrl, null);
      }
    }
  });

  it("非法 type 或缺失 report_id 严格拒绝", async () => {
    const { parseAnswerResponse } = await import("../lib/recorder.ts");
    assert.equal(parseAnswerResponse({ type: "unknown" }).ok, false);
    assert.equal(parseAnswerResponse({ type: "done", report_id: 0 }).ok, false);
  });
});

describe("pickTransitionAudioUrl（过渡语轮转选择纯函数）", () => {
  it("正常从列表中按序号轮转选择", async () => {
    const { pickTransitionAudioUrl } = await import("../lib/recorder.ts");
    const list = [
      "/audio/trans_0.mp3",
      "/audio/trans_1.mp3",
      "/audio/trans_2.mp3",
    ];
    assert.equal(pickTransitionAudioUrl(list, 0), "/audio/trans_0.mp3");
    assert.equal(pickTransitionAudioUrl(list, 1), "/audio/trans_1.mp3");
    assert.equal(pickTransitionAudioUrl(list, 2), "/audio/trans_2.mp3");
    // 轮转回到第 0 项
    assert.equal(pickTransitionAudioUrl(list, 3), "/audio/trans_0.mp3");
  });

  it("空列表或非法参数安全返回 null，不抛异常", async () => {
    const { pickTransitionAudioUrl } = await import("../lib/recorder.ts");
    assert.equal(pickTransitionAudioUrl([], 0), null);
    // @ts-expect-error 测试非数组输入
    assert.equal(pickTransitionAudioUrl(null, 0), null);
    // 包含空白字符的安全处理
    assert.equal(pickTransitionAudioUrl(["  ", ""], 0), null);
  });
});