export type LearningTopic = "hear" | "star" | "intro" | "followup" | "unknown" | "review";

export type AnswerFeedback = {
  answerId: number;
  qSeq: number;
  isFollowup: boolean;
  questionText: string;
  feedback: {
    practiceScore: number | null;
    problemAnalysis: string;
    evidenceQuote: string | null;
    improvementSuggestion: string;
    learningTopic: LearningTopic;
  };
};

export type ParseAnswerFeedbackResult =
  | { ok: true; value: AnswerFeedback }
  | { ok: false; message: string };

export type AnswerFeedbackRequestResult =
  | { kind: "ok"; value: AnswerFeedback }
  | { kind: "http"; status: number; message: string }
  | { kind: "invalid"; message: string }
  | { kind: "network"; message: string }
  | { kind: "aborted" };

const learningTopics = new Set<LearningTopic>([
  "hear",
  "star",
  "intro",
  "followup",
  "unknown",
  "review",
]);

export function parseAnswerFeedbackResponse(payload: unknown): ParseAnswerFeedbackResult {
  if (!isRecord(payload) || !isPositiveInt(payload.answer_id) || !isPositiveInt(payload.q_seq)) {
    return invalidFeedback();
  }
  if (
    payload.q_seq > 6 ||
    typeof payload.is_followup !== "boolean" ||
    typeof payload.question_text !== "string" ||
    !payload.question_text.trim() ||
    !isRecord(payload.feedback)
  ) {
    return invalidFeedback();
  }

  const feedback = payload.feedback;
  const practiceScore = feedback.practice_score;
  const evidenceQuote = feedback.evidence_quote;
  if (
    !(practiceScore === null ||
      (typeof practiceScore === "number" && Number.isFinite(practiceScore) && practiceScore >= 0 && practiceScore <= 100)) ||
    typeof feedback.problem_analysis !== "string" ||
    !feedback.problem_analysis.trim() ||
    !(evidenceQuote === null || (typeof evidenceQuote === "string" && evidenceQuote.trim().length > 0)) ||
    typeof feedback.improvement_suggestion !== "string" ||
    !feedback.improvement_suggestion.trim() ||
    typeof feedback.learning_topic !== "string" ||
    !learningTopics.has(feedback.learning_topic as LearningTopic)
  ) {
    return invalidFeedback();
  }

  return {
    ok: true,
    value: {
      answerId: payload.answer_id,
      qSeq: payload.q_seq,
      isFollowup: payload.is_followup,
      questionText: payload.question_text.trim(),
      feedback: {
        practiceScore,
        problemAnalysis: feedback.problem_analysis.trim(),
        evidenceQuote: typeof evidenceQuote === "string" ? evidenceQuote.trim() : null,
        improvementSuggestion: feedback.improvement_suggestion.trim(),
        learningTopic: feedback.learning_topic as LearningTopic,
      },
    },
  };
}

export async function requestAnswerFeedback(
  sid: number,
  signal?: AbortSignal,
): Promise<AnswerFeedbackRequestResult> {
  let response: Response;
  try {
    response = await fetch(`/api/sessions/${sid}/feedback`, {
      method: "POST",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    return signal?.aborted
      ? { kind: "aborted" }
      : { kind: "network", message: "本题反馈暂时无法加载。" };
  }

  if (!response.ok) {
    let message = "本题反馈暂时无法加载。";
    try {
      const payload: unknown = await response.json();
      if (
        isRecord(payload) &&
        isRecord(payload.detail) &&
        typeof payload.detail.message === "string" &&
        payload.detail.message.trim()
      ) {
        message = payload.detail.message.trim();
      }
    } catch {
      // 保留通用提示；错误响应正文不是反馈数据。
    }
    return { kind: "http", status: response.status, message };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "invalid", message: "本题反馈格式错误，可以继续面试。" };
  }
  const parsed = parseAnswerFeedbackResponse(payload);
  return parsed.ok
    ? { kind: "ok", value: parsed.value }
    : { kind: "invalid", message: parsed.message };
}

export function buildAnswerFeedbackLearningHref(topic: LearningTopic): string {
  return `/learn#${topic}`;
}

function invalidFeedback(): ParseAnswerFeedbackResult {
  return {
    ok: false,
    message: "本题反馈格式错误，可以继续面试。",
  };
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
