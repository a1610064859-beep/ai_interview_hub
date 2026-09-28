import assert from "node:assert/strict";
import { test } from "node:test";
import { buildStarDraft, reviewStarDraft, questionExercises } from "../lib/learning.ts";

test("真实经历四段可拼成回答；填写完整不等于回答质量获评分", () => {
  const draft = { situation: "课程展示前资料分散。", task: "我负责汇总。", action: "我建清单并逐项核对来源。", result: "按时提交，也发现应更早约定格式。" };
  assert.equal(buildStarDraft(draft), Object.values(draft).join("\n"));
  assert.deepEqual(reviewStarDraft(draft), []);
});
test("空白与只有空格的行动段仍提示补充本人做法", () => {
  assert.deepEqual(reviewStarDraft({ situation: "课程作业", task: "整理", action: "  ", result: "完成" }), ["action"]);
  assert.equal(buildStarDraft({ situation: " ", task: "", action: " 我核对来源。 ", result: "" }), "我核对来源。");
});
test("听题练习覆盖经历题和知识题，提供原因而非只报对错", () => {
  assert.ok(questionExercises.some((q) => q.kind === "experience"));
  assert.ok(questionExercises.some((q) => q.kind === "knowledge"));
  for (const q of questionExercises) {
    assert.ok(q.options.some((o) => o.correct));
    assert.ok(q.options.some((o) => !o.correct));
    assert.ok(q.options.every((o) => o.explanation.trim().length > 15));
  }
});
