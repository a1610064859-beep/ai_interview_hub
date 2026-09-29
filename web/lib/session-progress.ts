/** Only an active session identifier is cached locally; the server owns answer progress. */
export const SESSION_PROGRESS_KEY = "ai-interview-active-session-v1";

export type SessionProgress = {
  sid: number;
  userId: number;
  jobId: number;
  mode: "毕业生" | "新生";
  startedAtMs: number;
};

export type SavedSessionState = {
  sid: number;
  userId: number;
  jobId: number;
  mode: "毕业生" | "新生";
  status: "active" | "answering" | "completed";
  answerCount: number;
  inputMode: "text" | "voice" | null;
  question: { text: string; seq: number; audioUrl: string | null } | null;
  isFollowup: boolean;
  reportId: number | null;
};

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function positiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

export function parseSessionProgress(value: unknown): SessionProgress | null {
  if (!record(value) || !positiveInt(value.sid) || !positiveInt(value.userId) ||
      !positiveInt(value.jobId) || (value.mode !== "毕业生" && value.mode !== "新生") ||
      typeof value.startedAtMs !== "number" || !Number.isFinite(value.startedAtMs) || value.startedAtMs <= 0) {
    return null;
  }
  return { sid: value.sid, userId: value.userId, jobId: value.jobId,
    mode: value.mode, startedAtMs: value.startedAtMs };
}

export function parseSavedSessionState(value: unknown): SavedSessionState | null {
  if (!record(value) || !positiveInt(value.sid) || !positiveInt(value.user_id) ||
      !positiveInt(value.job_id) || (value.mode !== "毕业生" && value.mode !== "新生") ||
      !["active", "answering", "completed"].includes(String(value.status)) ||
      typeof value.answer_count !== "number" || !Number.isInteger(value.answer_count) || value.answer_count < 0 ||
      (value.input_mode !== null && value.input_mode !== "text" && value.input_mode !== "voice") ||
      typeof value.is_followup !== "boolean" ||
      (value.report_id !== null && !positiveInt(value.report_id))) {
    return null;
  }
  let question: SavedSessionState["question"] = null;
  if (value.question !== null) {
    if (!record(value.question) || typeof value.question.text !== "string" ||
        value.question.text.length === 0 || !positiveInt(value.question.seq) ||
        (value.question.audio_url !== null && typeof value.question.audio_url !== "string")) return null;
    question = { text: value.question.text, seq: value.question.seq,
      audioUrl: value.question.audio_url };
  }
  return { sid: value.sid, userId: value.user_id, jobId: value.job_id,
    mode: value.mode as SavedSessionState["mode"], status: value.status as SavedSessionState["status"],
    answerCount: value.answer_count, inputMode: value.input_mode as SavedSessionState["inputMode"],
    question, isFollowup: value.is_followup, reportId: value.report_id };
}

export function canResumeSession(progress: SessionProgress, state: SavedSessionState): boolean {
  return state.sid === progress.sid && state.userId === progress.userId &&
    state.jobId === progress.jobId && state.mode === progress.mode &&
    state.status === "active" && state.question !== null;
}
