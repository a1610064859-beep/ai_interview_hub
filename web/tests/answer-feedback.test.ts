import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildAnswerFeedbackLearningHref,
  parseAnswerFeedbackResponse,
  requestAnswerFeedback,
} from "../lib/answer-feedback.ts";

const validFeedback = {
  answer_id: 41,
  q_seq: 2,
  is_followup: false,
  question_text: "请说明你会如何验证自动驾驶感知模块。",
  feedback: {
    practice_score: 76,
    problem_analysis: "回答提到了场景覆盖，但没有说明如何记录并复现失败案例。",
    evidence_quote: "我会多跑几次不同路况",
    improvement_suggestion: "补充测试矩阵、失败日志和复现步骤。",
    learning_topic: "star",
    basis: "ai",
  },
};

describe("answer feedback", () => {
  it("parses a successful per-answer feedback response", () => {
    const parsed = parseAnswerFeedbackResponse(validFeedback);

    assert.deepEqual(parsed, {
      ok: true,
      value: {
        answerId: 41,
        qSeq: 2,
        isFollowup: false,
        questionText: "请说明你会如何验证自动驾驶感知模块。",
        feedback: {
          practiceScore: 76,
          problemAnalysis: "回答提到了场景覆盖，但没有说明如何记录并复现失败案例。",
          evidenceQuote: "我会多跑几次不同路况",
          improvementSuggestion: "补充测试矩阵、失败日志和复现步骤。",
          learningTopic: "star",
          basis: "ai",
        },
      },
    });
  });

  it("rejects an out-of-range score and an unknown learning topic", () => {
    const badScore = structuredClone(validFeedback);
    badScore.feedback.practice_score = 101;
    assert.equal(parseAnswerFeedbackResponse(badScore).ok, false);

    const badTopic = structuredClone(validFeedback);
    badTopic.feedback.learning_topic = "other";
    assert.equal(parseAnswerFeedbackResponse(badTopic).ok, false);
  });

  it("keeps unavailable scores and evidence as null", () => {
    const unavailable = structuredClone(validFeedback);
    Reflect.set(unavailable.feedback, "practice_score", null);
    Reflect.set(unavailable.feedback, "evidence_quote", null);

    const parsed = parseAnswerFeedbackResponse(unavailable);
    assert.equal(parsed.ok, true);
    if (parsed.ok) {
      assert.equal(parsed.value.feedback.practiceScore, null);
      assert.equal(parsed.value.feedback.evidenceQuote, null);
    }
  });

  it("requests feedback once with POST and no request body", async () => {
    const originalFetch = globalThis.fetch;
    let requestUrl = "";
    let requestInit: RequestInit | undefined;
    globalThis.fetch = async (input, init) => {
      requestUrl = String(input);
      requestInit = init;
      return new Response(JSON.stringify(validFeedback), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    try {
      const result = await requestAnswerFeedback(9);
      assert.deepEqual(result.kind, "ok");
      assert.equal(requestUrl, "/api/sessions/9/feedback");
      assert.equal(requestInit?.method, "POST");
      assert.equal(requestInit?.body, undefined);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("links each feedback topic to its learning section", () => {
    for (const topic of ["hear", "star", "intro", "followup", "unknown", "review"] as const) {
      assert.equal(buildAnswerFeedbackLearningHref(topic), `/learn#${topic}`);
    }
  });

  it("does not retry a cancelled feedback request", async () => {
    const originalFetch = globalThis.fetch;
    let callCount = 0;
    globalThis.fetch = async () => {
      callCount += 1;
      throw new Error("aborted");
    };
    const controller = new AbortController();
    controller.abort();

    try {
      const result = await requestAnswerFeedback(9, controller.signal);
      assert.deepEqual(result, { kind: "aborted" });
      assert.equal(callCount, 1);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
