import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canResumeSession,
  parseSavedSessionState,
  parseSessionProgress,
} from "../lib/session-progress.ts";

const cached = { sid: 7, userId: 2, jobId: 1, mode: "新生", startedAtMs: 1_000 };
const state = {
  sid: 7,
  status: "active",
  answer_count: 3,
  question: { text: "第三题追问", seq: 3, audio_url: null },
  is_followup: true,
  report_id: null,
  user_id: 2,
  job_id: 1,
  mode: "新生",
  input_mode: "text",
};

describe("逐题保存后的会话恢复", () => {
  it("从服务器状态恢复已保存条数与当前待答题", () => {
    const progress = parseSessionProgress(cached);
    const saved = parseSavedSessionState(state);
    assert.ok(progress);
    assert.ok(saved);
    assert.equal(saved.answerCount, 3);
    assert.deepEqual(saved.question, { text: "第三题追问", seq: 3, audioUrl: null });
    assert.equal(saved.inputMode, "text");
    assert.equal(canResumeSession(progress, saved), true);
  });

  it("拒绝跨学生、跨岗位和另一会话的缓存", () => {
    const progress = parseSessionProgress(cached);
    assert.ok(progress);
    for (const changed of [
      { ...state, user_id: 3 },
      { ...state, job_id: 2 },
      { ...state, sid: 8 },
      { ...state, mode: "毕业生" },
    ]) {
      const saved = parseSavedSessionState(changed);
      assert.ok(saved);
      assert.equal(canResumeSession(progress, saved), false);
    }
  });

  it("处理中及已完成状态不能重复进入答题页", () => {
    const progress = parseSessionProgress(cached);
    assert.ok(progress);
    for (const status of ["answering", "completed"]) {
      const saved = parseSavedSessionState({ ...state, status });
      assert.ok(saved);
      assert.equal(canResumeSession(progress, saved), false);
    }
  });

  it("拒绝非法或不完整的服务器状态", () => {
    assert.equal(parseSessionProgress({ ...cached, sid: 0 }), null);
    assert.equal(parseSavedSessionState({ ...state, answer_count: -1 }), null);
    assert.equal(parseSavedSessionState({ ...state, question: { text: "", seq: 3, audio_url: null } }), null);
    assert.equal(parseSavedSessionState({ ...state, input_mode: "other" }), null);
  });
});
