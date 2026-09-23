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

describe("ActionLock（双击选岗、自检开始与自检通过同步锁）", () => {
  it("首发获取成功，快速并发第二次获取被拒绝（防双击）", async () => {
    const { ActionLock } = await import("../lib/recorder.ts");
    const lock = new ActionLock();
    assert.equal(lock.acquire(), true);
    assert.equal(lock.acquire(), false);
    assert.equal(lock.isLocked, true);
  });

  it("明确释放后允许再次获取", async () => {
    const { ActionLock } = await import("../lib/recorder.ts");
    const lock = new ActionLock();
    assert.equal(lock.acquire(), true);
    lock.release();
    assert.equal(lock.isLocked, false);
    assert.equal(lock.acquire(), true);
  });

  it("自检通过锁锁定后拒绝重复触发 enterInterview", async () => {
    const { ActionLock } = await import("../lib/recorder.ts");
    const passLock = new ActionLock();
    let sessionCreateCount = 0;
    const triggerEnterInterview = () => {
      if (!passLock.acquire()) {
        return;
      }
      sessionCreateCount += 1;
    };
    // 模拟快速连续点击 3 次
    triggerEnterInterview();
    triggerEnterInterview();
    triggerEnterInterview();
    assert.equal(sessionCreateCount, 1);
  });
});

describe("TransitionAudioTracker（过渡语单次播放与主问/追问轮转防重）", () => {
  const transitions = [
    "/audio/trans_0.mp3",
    "/audio/trans_1.mp3",
    "/audio/trans_2.mp3",
  ];

  it("提交时立即播放并记录，响应返回时严格拒绝二次重复播放", async () => {
    const { TransitionAudioTracker } = await import("../lib/recorder.ts");
    const tracker = new TransitionAudioTracker();

    // 1. 提交第 1 题回答：立即播发
    const playUrl1 = tracker.onSubmissionPlay(transitions, 0);
    assert.equal(playUrl1, "/audio/trans_0.mp3");
    assert.equal(tracker.hasPlayedThisTurn, true);

    // 2. 服务端响应返回带有 transition_audio_url：拒绝二次播放
    const responsePlay1 = tracker.shouldPlayOnResponse("/audio/trans_0.mp3");
    assert.equal(responsePlay1, null);
    assert.equal(tracker.hasPlayedThisTurn, false);

    // 3. 再次重复渲染：依然不播放
    const repeatRenderPlay = tracker.shouldPlayOnResponse("/audio/trans_0.mp3");
    assert.equal(repeatRenderPlay, null);
  });

  it("主问题与追问使用 answerCount 轮转，避免相同 seq 重复播放同一音频", async () => {
    const { TransitionAudioTracker } = await import("../lib/recorder.ts");
    const tracker = new TransitionAudioTracker();

    // 回答 Q1 主问题（此时 answerCount = 0）
    const q1Audio = tracker.onSubmissionPlay(transitions, 0);
    assert.equal(q1Audio, "/audio/trans_0.mp3");
    tracker.shouldPlayOnResponse("/audio/trans_0.mp3"); // 消费响应

    // 回答 Q1 追问（此时 seq 依然为 1，但已提交 1 次回答，answerCount = 1）
    const q1FollowupAudio = tracker.onSubmissionPlay(transitions, 1);
    assert.equal(q1FollowupAudio, "/audio/trans_1.mp3");
    assert.notEqual(q1FollowupAudio, q1Audio); // 严格不同！
    tracker.shouldPlayOnResponse("/audio/trans_1.mp3");

    // 回答 Q2 主问题（此时 answerCount = 2）
    const q2Audio = tracker.onSubmissionPlay(transitions, 2);
    assert.equal(q2Audio, "/audio/trans_2.mp3");
  });

  it("提交时无预生成列表时，响应返回允许兜底播放一次", async () => {
    const { TransitionAudioTracker } = await import("../lib/recorder.ts");
    const tracker = new TransitionAudioTracker();

    // 提交时列表为空（未能立即播放）
    const playUrl = tracker.onSubmissionPlay([], 0);
    assert.equal(playUrl, null);
    assert.equal(tracker.hasPlayedThisTurn, false);

    // 响应返回了兜底音频：允许播放一次
    const responsePlay = tracker.shouldPlayOnResponse("/audio/trans_fallback.mp3");
    assert.equal(responsePlay, "/audio/trans_fallback.mp3");

    // 随后的重渲染不得再次播放
    assert.equal(tracker.shouldPlayOnResponse("/audio/trans_fallback.mp3"), null);
  });
});

describe("QuestionAudioPlayer（固定题音频每道新题仅自动播放一次）", () => {
  it("新题首次加载尝试自动播放一次，重渲染不重复触发", async () => {
    const { QuestionAudioPlayer } = await import("../lib/recorder.ts");
    const player = new QuestionAudioPlayer();

    // 第 1 题初次加载
    assert.equal(player.shouldAutoplay(1, false, "/audio/q1.mp3"), true);
    // 第 1 题页面重新渲染（如录音电平变化）
    assert.equal(player.shouldAutoplay(1, false, "/audio/q1.mp3"), false);

    // 推进到第 1 题追问（同一 seq，但 isFollowup 为 true）
    assert.equal(player.shouldAutoplay(1, true, "/audio/q1_followup.mp3"), true);
    assert.equal(player.shouldAutoplay(1, true, "/audio/q1_followup.mp3"), false);

    // 推进到第 2 题
    assert.equal(player.shouldAutoplay(2, false, "/audio/q2.mp3"), true);
    assert.equal(player.shouldAutoplay(2, false, "/audio/q2.mp3"), false);

    // 音频 URL 为空时不自动播放
    assert.equal(player.shouldAutoplay(3, false, null), false);
    assert.equal(player.shouldAutoplay(3, false, ""), false);
  });
});

function validReportPayload(sessionId = 5) {
  return {
    id: 1,
    session_id: sessionId,
    job_title: "智驾测试",
    overall: 80.5,
    dimensions: {
      professional_match: { score: 80, evidence: "用CANoe做总线", reason: "匹配" },
      logic_structure: { score: 75, evidence: null, reason: "结构尚可" },
      expression_fluency: { score: 91.3, evidence: null, reason: "语速正常" },
      job_competence: { score: 78, evidence: null, reason: "素养合格" },
    },
    highlights: ["表达清晰"],
    concerns: [],
    improvement: ["补充场景覆盖细节"],
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("session-recovery（中途断连）", () => {
  it("只读查询已提交的下一题，不等待不存在的最终报告", async () => {
    const { resolveAfterAnswerSubmit, createVirtualClock } = await import("../lib/session-recovery.ts");
    const clock = createVirtualClock();
    const urls: string[] = [];
    const result = await resolveAfterAnswerSubmit({ kind: "network" }, 7, {
      ...clock, expectedAnswerCount: 0,
      fetch: async (url: string) => {
        urls.push(url);
        return jsonResponse(200, { sid: 7, status: "active", answer_count: 1,
          question: { seq: 2, text: "下一题", audio_url: null }, is_followup: false, report_id: null });
      },
    });
    assert.deepEqual(urls, ["/api/sessions/7/state"]);
    assert.equal(result.outcome, "answer_ok");
    if (result.outcome === "answer_ok") assert.equal((result.value as { type: string }).type, "next");
  });

  it("后台尚未接受请求或仍处理中时保持锁定，绝不自动重发", async () => {
    const { resolveAfterAnswerSubmit, createVirtualClock } = await import("../lib/session-recovery.ts");
    for (const status of ["active", "answering"]) {
      const clock = createVirtualClock();
      const result = await resolveAfterAnswerSubmit({ kind: "http", status: 504, code: null, serverMessage: null }, 7, {
        ...clock, expectedAnswerCount: 0, maxMs: 20, intervalMs: 10,
        fetch: async (url: string) => {
          assert.equal(url, "/api/sessions/7/state");
          return jsonResponse(200, { sid: 7, status, answer_count: 0,
            question: { seq: 1, text: "当前题", audio_url: null }, is_followup: false, report_id: null });
        },
      });
      assert.equal(result.outcome, "still_unknown");
    }
  });
});

describe("session-recovery（最终评分断连后只读报告恢复）", () => {
  it("A. POST 只调用一次；网络异常后报告 404→404→200，最终返回成功报告", async () => {
    const {
      submitOnceThenResolve,
      createVirtualClock,
      REPORT_POLL_INTERVAL_MS,
    } = await import("../lib/session-recovery.ts");
    const clock = createVirtualClock();
    let postCalls = 0;
    let reportCalls = 0;
    const fetchMock = async (input: string) => {
      if (String(input).includes("/answers")) {
        throw new Error("should not POST via fetch in this test");
      }
      reportCalls += 1;
      if (reportCalls <= 2) {
        return jsonResponse(404, {
          detail: { code: "REPORT_NOT_FOUND", message: "报告尚未生成" },
        });
      }
      return jsonResponse(200, validReportPayload(5));
    };
    const result = await submitOnceThenResolve(
      async () => {
        postCalls += 1;
        return { kind: "network" };
      },
      5,
      {
        fetch: fetchMock,
        sleep: clock.sleep,
        now: clock.now,
        intervalMs: REPORT_POLL_INTERVAL_MS,
        maxMs: 120_000,
      },
    );
    assert.equal(postCalls, 1);
    assert.equal(reportCalls, 3);
    assert.equal(result.outcome, "report_ready");
    if (result.outcome === "report_ready") {
      assert.equal(result.report.session_id, 5);
      assert.equal(result.report.dimensions.expression_fluency.score, 91.3);
    }
  });

  it("B. HTTP 500 未知错误后报告立即 200，进入报告恢复", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let postCalls = 0;
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => {
        postCalls += 1;
        return { kind: "http", status: 500, code: null, serverMessage: null };
      },
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(200, validReportPayload(5));
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(postCalls, 1);
    assert.equal(reportCalls, 1);
    assert.equal(result.outcome, "report_ready");
  });

  it("C. 503 SCORING_UNAVAILABLE 不进入轮询", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({
        kind: "http",
        status: 503,
        code: "SCORING_UNAVAILABLE",
        serverMessage: "评分不可用",
      }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(200, validReportPayload(5));
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(reportCalls, 0);
    assert.equal(result.outcome, "scoring_unavailable");
  });

  it("D. 409 ANSWER_IN_PROGRESS 不重发 POST、不解除未知状态锁（不进入轮询）", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let postCalls = 0;
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => {
        postCalls += 1;
        return {
          kind: "http",
          status: 409,
          code: "ANSWER_IN_PROGRESS",
          serverMessage: "处理中",
        };
      },
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(200, validReportPayload(5));
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(postCalls, 1);
    assert.equal(reportCalls, 0);
    assert.equal(result.outcome, "answer_in_progress");
  });

  it("E. 报告轮询遇到 SESSION_NOT_FOUND 立即停止", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({ kind: "network" }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(404, {
            detail: { code: "SESSION_NOT_FOUND", message: "会话不存在" },
          });
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(reportCalls, 1);
    assert.equal(result.outcome, "session_not_found");
  });

  it("F. 报告返回非法 JSON/结构错误时停止并判定未知", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({ kind: "http", status: 500, code: null, serverMessage: null }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(200, { id: "bad", session_id: 5 });
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(reportCalls, 1);
    assert.equal(result.outcome, "still_unknown");
    if (result.outcome === "still_unknown") {
      assert.equal(result.reason, "invalid_report");
    }
  });

  it("G. 超过最大轮询次数后停止，绝不重发 POST", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let postCalls = 0;
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => {
        postCalls += 1;
        return { kind: "network" };
      },
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(404, {
            detail: { code: "REPORT_NOT_FOUND", message: "尚未生成" },
          });
        },
        sleep: clock.sleep,
        now: clock.now,
        intervalMs: 2000,
        maxMs: 4000,
      },
    );
    assert.equal(postCalls, 1);
    assert.ok(reportCalls >= 2);
    assert.equal(result.outcome, "still_unknown");
    if (result.outcome === "still_unknown") {
      assert.equal(result.reason, "timeout");
    }
  });

  it("H. AbortSignal 取消后不继续轮询", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    const controller = new AbortController();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({ kind: "network" }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          if (reportCalls === 1) {
            return jsonResponse(404, {
              detail: { code: "REPORT_NOT_FOUND", message: "尚未生成" },
            });
          }
          controller.abort();
          return jsonResponse(404, {
            detail: { code: "REPORT_NOT_FOUND", message: "尚未生成" },
          });
        },
        sleep: async (ms, signal) => {
          controller.abort();
          return clock.sleep(ms, signal);
        },
        now: clock.now,
        signal: controller.signal,
        intervalMs: 2000,
        maxMs: 120_000,
      },
    );
    assert.equal(result.outcome, "aborted");
    assert.ok(reportCalls <= 2);
  });

  it("I. 已完成会话 409 SESSION_COMPLETED 时允许只读确认报告", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let postCalls = 0;
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => {
        postCalls += 1;
        return {
          kind: "http",
          status: 409,
          code: "SESSION_COMPLETED",
          serverMessage: "面试已结束",
        };
      },
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(200, validReportPayload(5));
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(postCalls, 1);
    assert.equal(reportCalls, 1);
    assert.equal(result.outcome, "report_ready");
  });

  it("J. 未知 404（无 code 或非 REPORT_NOT_FOUND）立即停止，只 GET 一次", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({ kind: "http", status: 500, code: null, serverMessage: null }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(404, { detail: { message: "not found" } });
        },
        sleep: clock.sleep,
        now: clock.now,
        intervalMs: 2000,
        maxMs: 120_000,
      },
    );
    assert.equal(reportCalls, 1);
    assert.equal(result.outcome, "still_unknown");
    if (result.outcome === "still_unknown") {
      assert.equal(result.reason, "unexpected_http");
    }

    reportCalls = 0;
    const bare = await submitOnceThenResolve(
      async () => ({ kind: "network" }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          return jsonResponse(404, { detail: { code: "SOME_OTHER_404", message: "x" } });
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(reportCalls, 1);
    assert.equal(bare.outcome, "still_unknown");
    if (bare.outcome === "still_unknown") {
      assert.equal(bare.reason, "unexpected_http");
    }
  });

  it("K. 仅明确 REPORT_NOT_FOUND 的 404 才继续轮询", async () => {
    const { submitOnceThenResolve, createVirtualClock } = await import(
      "../lib/session-recovery.ts"
    );
    const clock = createVirtualClock();
    let reportCalls = 0;
    const result = await submitOnceThenResolve(
      async () => ({ kind: "network" }),
      5,
      {
        fetch: async () => {
          reportCalls += 1;
          if (reportCalls === 1) {
            return jsonResponse(404, {
              detail: { code: "REPORT_NOT_FOUND", message: "尚未生成" },
            });
          }
          return jsonResponse(200, validReportPayload(5));
        },
        sleep: clock.sleep,
        now: clock.now,
      },
    );
    assert.equal(reportCalls, 2);
    assert.equal(result.outcome, "report_ready");
  });
});
