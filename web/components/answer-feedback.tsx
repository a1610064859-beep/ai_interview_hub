import Link from "next/link";

import {
  buildAnswerFeedbackLearningHref,
  type AnswerFeedback,
  type LearningTopic,
} from "../lib/answer-feedback";

export function AnswerFeedbackPanel({
  feedback,
  questionText,
  qSeq,
  isFollowup,
  loading,
  error,
  continueLabel,
  onContinue,
  onLearn,
}: {
  feedback: AnswerFeedback | null;
  questionText: string;
  qSeq: number;
  isFollowup: boolean;
  loading: boolean;
  error: string | null;
  continueLabel: string;
  onContinue: () => void;
  onLearn: (topic: LearningTopic) => void;
}) {
  return (
    <section
      className="answer-feedback-panel mx-auto w-full max-w-4xl rounded-3xl border border-[#4b73c5]/70 bg-[#081225]/95 p-5 shadow-[0_0_45px_rgba(47,111,237,0.16)] sm:p-8"
      aria-live="polite"
      aria-busy={loading}
    >
      <header className="border-b border-white/10 pb-5">
        <p className="feedback-kicker text-xs font-semibold uppercase tracking-[0.24em] text-[#83aaff]">
          新生训练 · 本题即时反馈
        </p>
        <h1 className="mt-3 text-xl font-semibold leading-8 text-white sm:text-2xl">
          第 {qSeq} 题{isFollowup ? " · 追问" : ""}
        </h1>
        <p className="feedback-question mt-2 leading-7 text-[#b9c8df]">{questionText}</p>
      </header>

      {loading ? (
        <div className="flex min-h-56 flex-col items-center justify-center text-center" role="status">
          <div className="cockpit-sweep h-16 w-16 rounded-full border-2 border-[#2f6fed]" />
          <p className="mt-5 text-white">正在分析本题回答…</p>
          <p className="mt-2 text-sm text-[#8fa5c6]">分析完成后可查看学习建议，再继续面试。</p>
        </div>
      ) : error ? (
        <div className="mt-6 rounded-2xl border border-[#ff9a50]/40 bg-[#3a2418]/35 p-5" role="status">
          <h2 className="font-semibold text-[#ffc18d]">本题反馈暂不可用</h2>
          <p className="mt-2 text-sm leading-6 text-[#e4c6ad]">{error}</p>
          <p className="mt-2 text-sm leading-6 text-[#b9c8df]">
            回答已经提交成功，可以跳过反馈继续训练。
          </p>
        </div>
      ) : feedback ? (
        <div className="mt-6 space-y-4">
          <div className="feedback-score-card flex flex-wrap items-center gap-4 rounded-2xl border border-[#2f6fed]/35 bg-[#0d1b35] p-4">
            <div className="flex h-20 w-20 shrink-0 flex-col items-center justify-center rounded-full border-2 border-[#55a9ff] bg-[#071326] shadow-[0_0_20px_rgba(85,169,255,0.22)]">
              <span className="text-2xl font-bold text-white">
                {feedback.feedback.practiceScore ?? "—"}
              </span>
              <span className="text-[10px] text-[#9fb4d4]">
                {feedback.feedback.basis === "rule" ? "结构估分" : "本题练习分"}
              </span>
            </div>
            <p className="max-w-2xl text-sm leading-6 text-[#b9c8df]">
              {feedback.feedback.practiceScore === null
                ? "本题回答过短，暂无法估分；可先按下方建议补充。"
                : feedback.feedback.basis === "rule"
                  ? "AI评分暂不可用。此分数只反映回答结构，不评价专业内容是否正确。"
                  : "分数用于本次练习反馈，重点看回答依据和下一步改进方向。"}
            </p>
          </div>

          <FeedbackDetail title="问题分析" body={feedback.feedback.problemAnalysis} />
          {feedback.feedback.evidenceQuote ? (
            <blockquote className="feedback-quote rounded-2xl border-l-4 border-[#ff9a50] bg-[#1e1b20] px-5 py-4">
              <h2 className="text-sm font-semibold text-[#ffc18d]">回答依据</h2>
              <p className="mt-2 whitespace-pre-wrap leading-7 text-white">{feedback.feedback.evidenceQuote}</p>
            </blockquote>
          ) : null}
          <FeedbackDetail title="改进建议" body={feedback.feedback.improvementSuggestion} />

          <Link
            href={buildAnswerFeedbackLearningHref(feedback.feedback.learningTopic)}
            onClick={(event) => {
              event.preventDefault();
              onLearn(feedback.feedback.learningTopic);
            }}
            className="feedback-learning flex items-center justify-between gap-4 rounded-2xl border border-[#ff9a50]/50 bg-[#2b1d14]/70 px-5 py-4 text-[#ffd1ab] transition hover:border-[#ffb56c] hover:bg-[#3a261a]"
          >
            <span>
              <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-[#ffad69]">
                学习建议
              </span>
              <span className="mt-1 block">打开对应知识点，完成后可返回继续训练</span>
            </span>
            <span aria-hidden="true" className="text-xl">↗</span>
          </Link>
        </div>
      ) : null}

      <footer className="mt-7 flex justify-end border-t border-white/10 pt-5">
        <button
          type="button"
          onClick={onContinue}
          className="rounded-xl bg-[#3478f6] px-6 py-3 font-semibold text-white shadow-[0_0_20px_rgba(52,120,246,0.3)] transition hover:bg-[#4d8cff] focus:outline-none focus:ring-2 focus:ring-[#9cc1ff]"
        >
          {continueLabel} <span aria-hidden="true">→</span>
        </button>
      </footer>
    </section>
  );
}

function FeedbackDetail({ title, body }: { title: string; body: string }) {
  return (
    <section className="feedback-detail rounded-2xl border border-white/10 bg-[#0b172c] p-5">
      <h2 className="text-sm font-semibold text-[#80b8ff]">{title}</h2>
      <p className="mt-2 leading-7 text-[#e2eafa]">{body}</p>
    </section>
  );
}
