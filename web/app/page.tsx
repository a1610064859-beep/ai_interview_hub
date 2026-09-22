"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  VoiceRecorder,
  type VoiceRecording,
  parseSessionResponse,
  parseAnswerResponse,
  type SessionCreateData,
  type AnswerData,
} from "../lib/recorder";

const TOTAL_QUESTIONS = 6;
const MOCK_FOLLOWUP_SEQ = 2;
const MIN_ANSWER_LEN = 1;
const MAX_ANSWER_LEN = 5000;
/** 进入面试舱的过场动画时长（AGENTS §9）。 */
const TRANSITION_MS = 1500;
/** 设备自检录音时长（秒，AGENTS §9：录 3s 回放）。 */
const SELF_CHECK_SECONDS = 3;

type ApiMode = "mock" | "real";

type Job = {
  id: number;
  family: string;
  title: string;
  jdDigest: string;
};

type Question = {
  text: string;
  audioUrl: string | null;
  seq: number;
};

type AnswerLogEntry = {
  key: string;
  seq: number;
  kind: "voice" | "text";
  durationS?: number;
  pauseCnt?: number;
  isFollowup: boolean;
};

type View =
  | { phase: "config"; message: string }
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "jobs"; mode: ApiMode; jobs: Job[] }
  | { phase: "device_check"; job: Job }
  | { phase: "transition"; mode: ApiMode; job: Job }
  | {
      phase: "interview";
      mode: "mock";
      job: Job;
      question: Question;
      isFollowup: boolean;
      followupIssued: boolean;
    }
  | {
      phase: "interview";
      mode: "real";
      job: Job;
      sid: number;
      question: Question;
      isFollowup: boolean;
      startedAtMs: number;
      transitionAudioUrls: string[];
      transitionAudioUrl: string | null;
    }
  | { phase: "mock_done"; job: Job };

type ParseOk<T> = { ok: true; value: T };
type ParseErr = { ok: false; message: string };

type RealInterviewView = Extract<View, { phase: "interview"; mode: "real" }>;

export default function HomePage() {
  const router = useRouter();
  const [view, setView] = useState<View>(() => initialView());
  const [busy, setBusy] = useState(false);
  const [hold, setHold] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [answerHint, setAnswerHint] = useState<string | null>(null);
  const createLock = useRef(false);
  const submitLock = useRef(false);
  const [answerLog, setAnswerLog] = useState<AnswerLogEntry[]>([]);

  const recorderRef = useRef<VoiceRecorder | null>(null);
  const levelTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [voicePhase, setVoicePhase] = useState<"idle" | "recording" | "sending">("idle");
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [voiceMeta, setVoiceMeta] = useState<string | null>(null);
  const voiceSubmitLockRef = useRef(false);
  const playedTransitionRef = useRef<string | null>(null);

  useEffect(() => {
    const mode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
    if (!mode.ok || mode.mode !== "real") {
      return;
    }
    let alive = true;
    void loadRealJobList().then((result) => {
      if (!alive) {
        return;
      }
      if (!result.ok) {
        setView({ phase: "error", message: result.message });
        return;
      }
      if (result.value.length === 0) {
        setView({ phase: "empty" });
        return;
      }
      setView({ phase: "jobs", mode: "real", jobs: result.value });
    });
    return () => {
      alive = false;
    };
  }, []);

  // 组件卸载时释放录音与计时资源
  useEffect(() => {
    return () => {
      stopLevelTimer();
      recorderRef.current?.dispose();
      recorderRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopLevelTimer() {
    if (levelTimerRef.current !== null) {
      clearInterval(levelTimerRef.current);
      levelTimerRef.current = null;
    }
  }

  function resetSessionState() {
    setAnswerText("");
    setAnswerHint(null);
    setAnswerLog([]);
    setVoicePhase("idle");
    setVoiceMeta(null);
    setLevel(0);
    setElapsed(0);
    setHold(false);
    setNotice(null);
    playedTransitionRef.current = null;
    voiceSubmitLockRef.current = false;
    submitLock.current = false;
    createLock.current = false;
  }

  async function choose(mode: ApiMode, job: Job) {
    if (createLock.current) {
      return;
    }
    createLock.current = true;
    setBusy(true);
    setNotice(null);
    setAnswerHint(null);
    resetSessionState();

    if (mode === "mock") {
      // mock 为纯前端演示，跳过设备自检，仅保留 1.5s 过场
      await enterInterview(mode, job);
      return;
    }

    // real 模式：先做 3 秒设备自检（录 3s → 回放 → 确认），通过后才进入面试舱
    setView({ phase: "device_check", job });
    setBusy(false);
  }

  async function enterInterview(mode: ApiMode, job: Job) {
    // 1.5s 座舱过场（AGENTS §9）；real 模式同时并行创建会话
    setView({ phase: "transition", mode, job });
    const transition = sleep(TRANSITION_MS);

    if (mode === "mock") {
      await transition;
      setView({
        phase: "interview",
        mode: "mock",
        job,
        question: mockMainQuestion(1),
        isFollowup: false,
        followupIssued: false,
      });
      setBusy(false);
      return;
    }

    const [result] = await Promise.all([requestRealSession(job.id), transition]);
    if (result.kind === "network") {
      setView({
        phase: "error",
        message: "网络失败，无法确认会话是否已创建。未自动重试。请刷新页面后再试。",
      });
      return;
    }
    if (result.kind === "http") {
      setView({
        phase: "error",
        message: formatApiError(result, "创建会话失败", "未进入面试，未自动重试。请刷新页面后再试。"),
      });
      return;
    }
    if (result.kind === "invalid") {
      setView({ phase: "error", message: result.message });
      return;
    }

    setView({
      phase: "interview",
      mode: "real",
      job,
      sid: result.sid,
      question: result.question,
      isFollowup: false,
      startedAtMs: Date.now(),
      transitionAudioUrl: null,
    });
    setBusy(false);
  }

  function sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function startRecording() {
    if (
      view.phase !== "interview" ||
      view.mode !== "real" ||
      voicePhase !== "idle" ||
      busy ||
      hold ||
      voiceSubmitLockRef.current
    ) {
      return;
    }
    try {
      const rec = await VoiceRecorder.create();
      rec.start();
      recorderRef.current = rec;
      setVoicePhase("recording");
      setVoiceMeta(null);
      setNotice(null);
      levelTimerRef.current = setInterval(() => {
        setLevel(rec.level01);
        setElapsed(rec.elapsedS);
      }, 100);
    } catch (error) {
      setNotice(formatMicError(error));
    }
  }

  async function stopRecordingAndSend() {
    // 同步 ref 锁：快速双击「停止并发送」只执行一次停止与上传
    if (voiceSubmitLockRef.current) {
      return;
    }
    const rec = recorderRef.current;
    if (!rec || view.phase !== "interview" || view.mode !== "real" || voicePhase !== "recording") {
      return;
    }
    voiceSubmitLockRef.current = true;
    stopLevelTimer();
    setVoicePhase("sending");
    setLevel(0);
    let recording: VoiceRecording;
    try {
      recording = await rec.stop();
    } catch {
      recorderRef.current = null;
      setVoicePhase("idle");
      voiceSubmitLockRef.current = false;
      setNotice("录音结束处理失败，请重新录音。");
      return;
    }
    recorderRef.current = null;
    setVoiceMeta(`本次录音：时长 ${recording.durationS} 秒 · 停顿 ${recording.pauseCnt} 次`);
    await submitAudioAnswer(view, recording);
  }

  async function submitAudioAnswer(view: RealInterviewView, recording: VoiceRecording) {
    const result = await requestAudioAnswer(
      view.sid,
      recording.blob,
      recording.durationS,
      recording.pauseCnt,
    );
    setVoicePhase("idle");

    if (result.kind === "network") {
      // 结果不明：保持锁页与 ref 锁，绝不自动重发
      setHold(true);
      setNotice("网络失败，无法确认语音回答是否已提交。结果不明，请刷新确认后再试。未自动重发。");
      return;
    }
    if (result.kind === "http") {
      const code = result.code ?? "";
      if (code === "ANSWER_IN_PROGRESS") {
        setHold(true);
        setNotice(
          formatApiError(result, "语音提交失败", "结果不明，请刷新确认后再试。未自动重发。"),
        );
        return;
      }
      if (
        code === "ASR_UNAVAILABLE" ||
        code === "AUDIO_PROCESS_FAILED" ||
        code === "SCORING_UNAVAILABLE"
      ) {
        voiceSubmitLockRef.current = false;
        setBusy(false);
        setNotice(
          formatApiError(result, "语音提交失败", "服务暂时不可用，请稍后重新录音再试。未自动重发。"),
        );
        return;
      }
      if (code === "AUDIO_INVALID" || code === "AUDIO_TOO_LARGE") {
        voiceSubmitLockRef.current = false;
        setBusy(false);
        setNotice(formatApiError(result, "语音提交失败", "录音未被接受，请重新录音。"));
        return;
      }
      voiceSubmitLockRef.current = false;
      setBusy(false);
      setNotice(formatApiError(result, "语音提交失败", "未推进题目。未自动重试。"));
      return;
    }
    if (result.kind === "invalid") {
      setHold(true);
      setNotice(`${result.message} 结果不明，请刷新确认后再试。未自动重发。`);
      return;
    }

    setAnswerLog((log) => [
      ...log,
      {
        key: `${view.question.seq}-voice-${Date.now()}`,
        seq: view.question.seq,
        kind: "voice",
        durationS: recording.durationS,
        pauseCnt: recording.pauseCnt,
        isFollowup: view.isFollowup,
      },
    ]);

    if (result.value.type === "done") {
      voiceSubmitLockRef.current = false;
      // 路由必须用创建会话得到的 sid，禁止把 report_id 当作路径参数。
      router.push(`/reports/${view.sid}`);
      return;
    }

    setView({
      phase: "interview",
      mode: "real",
      job: view.job,
      sid: view.sid,
      question: result.value.question,
      isFollowup: result.value.type === "followup",
      startedAtMs: view.startedAtMs,
      transitionAudioUrl: result.value.transitionAudioUrl,
    });
    setVoiceMeta(null);
    voiceSubmitLockRef.current = false;
    setBusy(false);
  }

  async function submitAnswer() {
    if (view.phase !== "interview" || submitLock.current || hold) {
      return;
    }

    const normalized = answerText.trim();
    if (normalized.length < MIN_ANSWER_LEN) {
      setAnswerHint("回答不能为空（去除首尾空白后至少 1 个字符）。");
      return;
    }
    if (normalized.length > MAX_ANSWER_LEN) {
      setAnswerHint(`回答过长（去除首尾空白后最多 ${MAX_ANSWER_LEN} 字符）。`);
      return;
    }

    submitLock.current = true;
    setBusy(true);
    setAnswerHint(null);
    setNotice(null);

    if (view.mode === "mock") {
      const next = advanceMockInterview(view, normalized);
      if (next.phase === "mock_done") {
        setView(next);
        setAnswerText("");
        setBusy(false);
        return;
      }
      setView(next);
      setAnswerText("");
      submitLock.current = false;
      setBusy(false);
      return;
    }

    const seq = view.question.seq;
    const wasFollowup = view.isFollowup;
    const result = await requestTextAnswer(view.sid, normalized);
    if (result.kind === "network") {
      setBusy(false);
      setHold(true);
      setNotice("网络失败，无法确认回答是否已提交。未自动重试。请刷新确认后再试。");
      return;
    }
    if (result.kind === "http") {
      const code = result.code ?? "";
      if (code === "ANSWER_IN_PROGRESS") {
        // 后端可能仍在处理或已被接管；结果未知，禁止再次提交。
        setBusy(false);
        setHold(true);
        setNotice(
          formatApiError(
            result,
            "提交失败",
            "已保留当前输入。结果不明，请刷新确认后再试。未自动重发。",
          ),
        );
        return;
      }
      submitLock.current = false;
      setBusy(false);
      if (code === "SCORING_UNAVAILABLE") {
        setNotice(
          formatApiError(result, "提交失败", "已保留当前输入，可人工重试。未自动重发。"),
        );
        return;
      }
      setNotice(formatApiError(result, "提交失败", "已保留当前输入。未自动重试。"));
      return;
    }
    if (result.kind === "invalid") {
      // HTTP 200 但无法解析时，后端很可能已推进；锁页禁止重复提交。
      setBusy(false);
      setHold(true);
      setNotice(`${result.message} 结果不明，请刷新确认后再试。未自动重发。`);
      return;
    }

    setAnswerLog((log) => [
      ...log,
      {
        key: `${seq}-text-${Date.now()}`,
        seq,
        kind: "text",
        isFollowup: wasFollowup,
      },
    ]);

    if (result.value.type === "done") {
      // 路由必须用创建会话得到的 sid，禁止把 report_id 当作路径参数。
      router.push(`/reports/${view.sid}`);
      return;
    }

    setView({
      phase: "interview",
      mode: "real",
      job: view.job,
      sid: view.sid,
      question: result.value.question,
      isFollowup: result.value.type === "followup",
      startedAtMs: view.startedAtMs,
      transitionAudioUrl: result.value.transitionAudioUrl,
    });
    setAnswerText("");
    submitLock.current = false;
    setBusy(false);
  }

  // 过渡语自动播放：仅播一次；任何失败静默降级，绝不阻断录音与题目推进（T6 审查建议项）
  useEffect(() => {
    if (view.phase !== "interview" || view.mode !== "real") {
      return;
    }
    const url = view.transitionAudioUrl;
    if (!url || playedTransitionRef.current === url) {
      return;
    }
    playedTransitionRef.current = url;
    try {
      new Audio(url).play().catch(() => undefined);
    } catch {
      // 静默降级
    }
  }, [view]);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <header className="mb-8 min-w-0 max-w-full">
        <p className="text-sm tracking-[0.18em] text-[#7eb6ff]">智能汽车座舱</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">智驾未来 · AI面试仓</h1>
        <p className="mt-2 max-w-full text-sm text-[#9fb4d4]">
          选择岗位，语音或文本作答，查看首题与进度。
        </p>
      </header>

      {view.phase === "config" ? <MessagePanel title="配置错误" message={view.message} /> : null}
      {view.phase === "loading" ? <StatusPanel title="正在加载岗位" /> : null}
      {view.phase === "empty" ? (
        <StatusPanel title="暂无岗位" detail="岗位列表为空。未进入面试。" />
      ) : null}
      {view.phase === "error" ? <MessagePanel title="无法加载岗位" message={view.message} /> : null}

      {view.phase === "jobs" ? (
        <section className="min-w-0 max-w-full">
          <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg text-white">岗位列表</h2>
            <ModeBadge mode={view.mode} />
          </div>
          {notice ? (
            <p
              className="mb-4 max-w-full break-anywhere rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]"
              role="alert"
            >
              {notice}
            </p>
          ) : null}
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
            {view.jobs.map((job) => (
              <article
                key={job.id}
                className="min-w-0 max-w-full rounded-2xl border border-[#2f6fed] bg-[#0c1730]/90 p-5 shadow-[0_0_24px_rgba(47,111,237,0.28)]"
              >
                <p className="text-xs tracking-wide text-[#7eb6ff]">{job.family}</p>
                <h3 className="mt-2 break-anywhere text-xl text-white">{job.title}</h3>
                <p className="mt-3 break-anywhere text-sm leading-6 text-[#b7c8e2]">{job.jdDigest}</p>
                <button
                  type="button"
                  className="mt-5 max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={busy || hold}
                  onClick={() => {
                    void choose(view.mode, job);
                  }}
                >
                  {view.mode === "real" ? "选择并自检设备" : "选择此岗位"}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {view.phase === "device_check" ? (
        <DeviceCheckPanel
          job={view.job}
          onPass={() => {
            void enterInterview("real", view.job);
          }}
        />
      ) : null}

      {view.phase === "transition" ? (
        <section
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#050912]/95"
          role="status"
        >
          <div className="cockpit-sweep h-40 w-40 rounded-full border-2 border-[#2f6fed]" />
          <p className="mt-8 text-lg text-white">正在进入面试舱…</p>
          <p className="mt-2 text-sm text-[#9fb4d4]">
            {view.mode === "real" ? "设备自检已通过 · 会话建立中" : "演示模式 · 非正式数据"}
          </p>
        </section>
      ) : null}

      {view.phase === "interview" ? (
        <InterviewPanel
          mode={view.mode}
          job={view.job}
          question={view.question}
          isFollowup={view.isFollowup}
          sid={view.mode === "real" ? view.sid : null}
          startedAtMs={view.mode === "real" ? view.startedAtMs : null}
          answerText={answerText}
          answerHint={answerHint}
          notice={notice}
          busy={busy}
          hold={hold}
          voicePhase={voicePhase}
          level={level}
          elapsed={elapsed}
          voiceMeta={voiceMeta}
          answerLog={answerLog}
          onAnswerChange={(value) => {
            setAnswerText(value);
            setAnswerHint(null);
          }}
          onSubmit={() => {
            void submitAnswer();
          }}
          onStartRecording={() => {
            void startRecording();
          }}
          onStopSendRecording={() => {
            void stopRecordingAndSend();
          }}
        />
      ) : null}

      {view.phase === "mock_done" ? (
        <section className="min-w-0 max-w-full rounded-3xl border border-[#ff8a2a] bg-[#0c1730]/95 p-6">
          <ModeBadge mode="mock" />
          <h2 className="mt-4 text-2xl text-white">演示完成</h2>
          <p className="mt-3 break-anywhere text-sm leading-6 text-[#b7c8e2]">
            【非正式】已走完 6 题及固定一次追问。本模式不伪造真实 report_id，也不请求真实报告接口。岗位：
            {view.job.title}
          </p>
        </section>
      ) : null}
    </main>
  );
}

function DeviceCheckPanel({
  job,
  onPass,
}: {
  job: Job;
  onPass: () => void;
}) {
  const [status, setStatus] = useState<
    "idle" | "recording" | "playing" | "confirm" | "playback_failed"
  >("idle");
  const [message, setMessage] = useState<string | null>(null);
  const recorderRef = useRef<VoiceRecorder | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackUrlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (stopTimerRef.current !== null) {
        clearTimeout(stopTimerRef.current);
      }
      recorderRef.current?.dispose();
      recorderRef.current = null;
      if (playbackUrlRef.current) {
        URL.revokeObjectURL(playbackUrlRef.current);
        playbackUrlRef.current = null;
      }
    };
  }, []);

  async function begin() {
    setStatus("recording");
    setMessage(null);
    try {
      const rec = await VoiceRecorder.create();
      recorderRef.current = rec;
      rec.start();
      stopTimerRef.current = setTimeout(() => {
        void finishRecording();
      }, SELF_CHECK_SECONDS * 1000);
    } catch (error) {
      setStatus("idle");
      setMessage(`${formatMicError(error)} 自检未通过，可重试。`);
    }
  }

  async function finishRecording() {
    const rec = recorderRef.current;
    if (!rec) {
      return;
    }
    const recording = await rec.stop();
    recorderRef.current = null;
    if (recording.blob.size === 0) {
      setStatus("idle");
      setMessage("自检录音为空，请重试。");
      return;
    }
    const url = URL.createObjectURL(recording.blob);
    playbackUrlRef.current = url;
    const audio = new Audio(url);
    audio.onended = () => {
      setStatus((current) => (current === "playing" ? "confirm" : current));
    };
    audio.onerror = () => {
      setStatus("playback_failed");
      setMessage("回放失败：未能捕获自检音频。请重试自检。");
    };
    setStatus("playing");
    try {
      await audio.play();
    } catch {
      setStatus("playback_failed");
      setMessage("回放失败：浏览器阻止了播放。请重试自检。");
    }
  }

  function retry() {
    if (playbackUrlRef.current) {
      URL.revokeObjectURL(playbackUrlRef.current);
      playbackUrlRef.current = null;
    }
    setStatus("idle");
    setMessage(null);
  }

  return (
    <section className="min-w-0 max-w-full rounded-3xl border border-[#2f6fed] bg-[#0c1730]/95 p-6 shadow-[0_0_32px_rgba(47,111,237,0.35)]">
      <h2 className="text-xl text-white">设备自检</h2>
      <p className="mt-2 break-anywhere text-sm leading-6 text-[#b7c8e2]">
        岗位「{job.title}」已选择。开始前请完成 3 秒麦克风自检：录音后回放，确认能听到自己的声音。
      </p>

      {message ? (
        <p
          className="mt-4 max-w-full break-anywhere rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]"
          role="alert"
        >
          {message}
        </p>
      ) : null}

      <div className="mt-5 flex min-w-0 flex-wrap items-center gap-3">
        {status === "idle" ? (
          <button
            type="button"
            className="max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04]"
            onClick={() => {
              void begin();
            }}
          >
            开始 3 秒自检录音
          </button>
        ) : null}
        {status === "recording" ? (
          <span className="text-sm text-[#ffb067]" role="status">
            正在录制自检语音（{SELF_CHECK_SECONDS} 秒）…
          </span>
        ) : null}
        {status === "playing" ? (
          <span className="text-sm text-[#7eb6ff]" role="status">
            正在回放你的录音…
          </span>
        ) : null}
        {status === "confirm" ? (
          <>
            <span className="text-sm text-[#b7c8e2]">能清楚听到自己的声音吗？</span>
            <button
              type="button"
              className="max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04]"
              onClick={onPass}
            >
              自检通过，进入面试舱
            </button>
            <button
              type="button"
              className="max-w-full rounded-full border border-[#2f6fed] bg-transparent px-4 py-2 text-sm text-[#7eb6ff]"
              onClick={retry}
            >
              重试自检
            </button>
          </>
        ) : null}
        {status === "playback_failed" ? (
          <button
            type="button"
            className="max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04]"
            onClick={retry}
          >
            重试自检
          </button>
        ) : null}
      </div>
    </section>
  );
}

function InterviewPanel({
  mode,
  job,
  question,
  isFollowup,
  sid,
  startedAtMs,
  answerText,
  answerHint,
  notice,
  busy,
  hold,
  voicePhase,
  level,
  elapsed,
  voiceMeta,
  answerLog,
  onAnswerChange,
  onSubmit,
  onStartRecording,
  onStopSendRecording,
}: {
  mode: ApiMode;
  job: Job;
  question: Question;
  isFollowup: boolean;
  sid: number | null;
  startedAtMs: number | null;
  answerText: string;
  answerHint: string | null;
  notice: string | null;
  busy: boolean;
  hold: boolean;
  voicePhase: "idle" | "recording" | "sending";
  level: number;
  elapsed: number;
  voiceMeta: string | null;
  answerLog: AnswerLogEntry[];
  onAnswerChange: (value: string) => void;
  onSubmit: () => void;
  onStartRecording: () => void;
  onStopSendRecording: () => void;
}) {
  const trimmedLen = answerText.trim().length;

  return (
    <section className="min-w-0 max-w-full rounded-3xl border border-[#2f6fed] bg-[#0c1730]/95 p-6 shadow-[0_0_32px_rgba(47,111,237,0.35)]">
      <div className="flex min-w-0 gap-6">
        <ProgressRail seq={question.seq} isFollowup={isFollowup} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
            <ModeBadge mode={mode} />
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {isFollowup ? (
                <span className="rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-3 py-1 text-sm font-medium text-[#1a0d04]">
                  追问
                </span>
              ) : null}
              <p className="rounded-full border border-[#ff8a2a] bg-[#ff8a2a]/15 px-3 py-1 text-sm text-[#ffb067]">
                第{question.seq}题 / 共{TOTAL_QUESTIONS}题
              </p>
              {startedAtMs !== null ? <InterviewTimer startedAtMs={startedAtMs} /> : null}
            </div>
          </div>
          <p className="mt-6 text-sm text-[#7eb6ff]">{job.family}</p>
          <h2 className="mt-1 break-anywhere text-2xl text-white">{job.title}</h2>
          {sid !== null ? <p className="mt-2 text-sm text-[#9fb4d4]">会话 {sid}</p> : null}
          <QuestionSubtitle text={question.text} />
          {question.audioUrl !== null ? (
            <audio className="mt-4 max-w-full" controls src={question.audioUrl} preload="none">
              当前浏览器不支持音频播放。
            </audio>
          ) : null}

          {notice ? (
            <p
              className="mt-4 max-w-full break-anywhere rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-4 py-3 text-sm text-[#ffd0a8]"
              role="alert"
            >
              {notice}
            </p>
          ) : null}

          {mode === "real" ? (
            <div className="mt-6 rounded-2xl border border-[#1d4ed8]/60 bg-[#070b14] p-4">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-[#9fb4d4]">
                  语音回答（webm/opus，随录音提交时长与停顿统计）
                </span>
                <div className="flex items-center gap-2">
                  <span className="relative flex h-9 w-9 items-center justify-center">
                    <span
                      className="absolute inset-0 rounded-full border border-[#2f6fed]/70"
                      style={{
                        transform: `scale(${1 + level * 0.7})`,
                        boxShadow: `0 0 ${8 + level * 24}px rgba(47,111,237,${0.3 + level * 0.5})`,
                        transition: "transform 90ms linear",
                      }}
                    />
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{
                        background:
                          voicePhase === "recording" && level > 0.05 ? "#ff8a2a" : "#2f6fed",
                      }}
                    />
                  </span>
                  {voicePhase === "recording" ? (
                    <span className="text-sm text-[#ffb067]">{elapsed.toFixed(1)}s</span>
                  ) : null}
                </div>
              </div>
              <div className="mt-3 flex min-w-0 flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={busy || hold || voicePhase !== "idle"}
                  onClick={onStartRecording}
                >
                  开始录音
                </button>
                {voicePhase === "recording" ? (
                  <button
                    type="button"
                    className="max-w-full rounded-full border border-[#ff5a5a] bg-[#2a0d0d] px-4 py-2 text-sm font-medium text-[#ffb0b0]"
                    onClick={onStopSendRecording}
                  >
                    停止并发送
                  </button>
                ) : null}
                {voicePhase === "sending" ? (
                  <span className="text-sm text-[#7eb6ff]" role="status">
                    正在上传与识别…（首次可能较久，请勿关闭页面）
                  </span>
                ) : null}
              </div>
              {voiceMeta ? (
                <p className="mt-2 break-anywhere text-xs text-[#b7c8e2]" role="status">
                  {voiceMeta}
                </p>
              ) : null}
            </div>
          ) : null}

          <label className="mt-6 block min-w-0 max-w-full">
            <span className="text-sm text-[#9fb4d4]">文本回答</span>
            <textarea
              className="mt-2 min-h-36 w-full max-w-full resize-y rounded-2xl border border-[#2f6fed] bg-[#070b14] px-4 py-3 text-sm leading-6 text-white outline-none focus:border-[#ff8a2a]"
              value={answerText}
              disabled={busy || hold || voicePhase !== "idle"}
              onChange={(event) => {
                onAnswerChange(event.target.value);
              }}
              placeholder="输入回答后提交。前后空白会被忽略，长度需在 1–5000 字。"
            />
          </label>
          <div className="mt-2 flex min-w-0 flex-wrap items-center justify-between gap-3 text-xs text-[#9fb4d4]">
            <span>
              已输入（去空白）{trimmedLen} / {MAX_ANSWER_LEN}
            </span>
            {answerHint ? (
              <span className="break-anywhere text-[#ffb067]" role="alert">
                {answerHint}
              </span>
            ) : null}
          </div>
          <button
            type="button"
            className="mt-4 max-w-full rounded-full border border-[#ff8a2a] bg-[#ff8a2a] px-4 py-2 text-sm font-medium text-[#1a0d04] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy || hold || voicePhase !== "idle"}
            onClick={onSubmit}
          >
            {busy ? "正在提交…" : "提交文本回答"}
          </button>

          <div className="mt-6 border-t border-[#1d2c4e] pt-4">
            <p className="text-xs text-[#5b6b85]">回答记录（本会话）</p>
            {answerLog.length === 0 ? (
              <p className="mt-2 text-xs text-[#5b6b85]">暂无已提交回答。</p>
            ) : (
              <div className="mt-2 flex min-w-0 gap-2 overflow-x-auto pb-1">
                {answerLog.map((entry) => (
                  <span
                    key={entry.key}
                    className="whitespace-nowrap rounded-full border border-[#2f6fed]/60 bg-[#0c1730] px-3 py-1 text-xs text-[#9fb4d4]"
                  >
                    第{entry.seq}题 ·{" "}
                    {entry.kind === "voice"
                      ? `🎙 ${entry.durationS?.toFixed(1)}s / 停顿${entry.pauseCnt}`
                      : "⌨ 文本"}
                    {entry.isFollowup ? " · 追问" : ""}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function ProgressRail({ seq, isFollowup }: { seq: number; isFollowup: boolean }) {
  return (
    <ol className="hidden shrink-0 flex-col gap-3 md:flex" aria-label="题目进度轨道">
      {Array.from({ length: TOTAL_QUESTIONS }, (_, i) => i + 1).map((n) => {
        const done = n < seq;
        const current = n === seq;
        return (
          <li key={n} className="flex items-center gap-2">
            <span
              className={`flex h-8 w-8 items-center justify-center rounded-full border text-xs ${
                done
                  ? "border-[#2f6fed] bg-[#2f6fed]/30 text-[#bcd7ff]"
                  : current
                    ? isFollowup
                      ? "cockpit-pulse border-[#ff8a2a] bg-[#ff8a2a]/25 text-[#ffd0a8]"
                      : "border-[#ff8a2a] bg-[#ff8a2a]/15 text-[#ffb067]"
                    : "border-[#33415e] text-[#5b6b85]"
              }`}
            >
              {n}
            </span>
            <span className={`text-xs ${current ? "text-white" : "text-[#5b6b85]"}`}>
              {done ? "已完成" : current ? (isFollowup ? "追问中" : "作答中") : "待作答"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function QuestionSubtitle({ text }: { text: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0);
    if (!text) {
      return;
    }
    const timer = setInterval(() => {
      setShown((n) => {
        if (n >= text.length) {
          clearInterval(timer);
          return n;
        }
        return n + 1;
      });
    }, 40);
    return () => clearInterval(timer);
  }, [text]);
  return (
    <p className="mt-6 min-h-24 break-anywhere text-lg leading-8">
      <span className="text-white">{text.slice(0, shown)}</span>
      <span className="text-[#3a4a66]">{text.slice(shown)}</span>
      {shown < text.length ? <span className="subtitle-caret text-[#ff8a2a]">▍</span> : null}
    </p>
  );
}

function InterviewTimer({ startedAtMs }: { startedAtMs: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const total = Math.max(0, Math.floor((now - startedAtMs) / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return (
    <p className="rounded-full border border-[#2f6fed] px-3 py-1 text-xs text-[#7eb6ff]">
      ⏱ {mm}:{ss}
    </p>
  );
}

function ModeBadge({ mode }: { mode: ApiMode }) {
  if (mode === "mock") {
    return (
      <span className="rounded-full border border-[#ff8a2a] px-3 py-1 text-xs text-[#ffb067]">
        演示模式 · 非正式数据
      </span>
    );
  }
  return (
    <span className="rounded-full border border-[#2f6fed] px-3 py-1 text-xs text-[#7eb6ff]">
      后端联调
    </span>
  );
}

function MessagePanel({ title, message }: { title: string; message: string }) {
  return (
    <section className="max-w-full rounded-2xl border border-[#ff8a2a] bg-[#2a1608] p-5" role="alert">
      <h2 className="text-lg text-[#ffb067]">{title}</h2>
      <p className="mt-2 break-anywhere text-sm leading-6 text-[#ffd0a8]">{message}</p>
    </section>
  );
}

function StatusPanel({ title, detail }: { title: string; detail?: string }) {
  return (
    <section className="max-w-full rounded-2xl border border-[#2f6fed] bg-[#0c1730]/90 p-5" role="status">
      <h2 className="text-lg text-white">{title}</h2>
      {detail ? <p className="mt-2 break-anywhere text-sm text-[#b7c8e2]">{detail}</p> : null}
    </section>
  );
}

function initialView(): View {
  const mode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
  if (!mode.ok) {
    return { phase: "config", message: mode.message };
  }
  if (mode.mode === "mock") {
    return { phase: "jobs", mode: "mock", jobs: mockJobs() };
  }
  return { phase: "loading" };
}

function readApiMode(raw: string | undefined): { ok: true; mode: ApiMode } | { ok: false; message: string } {
  if (raw === undefined) {
    return { ok: true, mode: "mock" };
  }
  if (raw === "mock" || raw === "real") {
    return { ok: true, mode: raw };
  }
  return {
    ok: false,
    message: `配置错误：NEXT_PUBLIC_API_MODE 只能是 mock 或 real，当前值为 ${JSON.stringify(raw)}`,
  };
}

function mockJobs(): Job[] {
  return [
    {
      id: 1,
      family: "演示",
      title: "演示岗位·智驾测试",
      jdDigest: "【非正式演示】这不是后端题库数据，仅用于 mock 模式界面联调。",
    },
    {
      id: 2,
      family: "演示",
      title: "演示岗位·三电系统",
      jdDigest: "【非正式演示】这不是后端题库数据，仅用于 mock 模式界面联调。",
    },
  ];
}

function mockMainTexts(): string[] {
  return [
    "【非正式占位·第1题】请用一两句话介绍自己与智能汽车相关的学习或项目经历。",
    "【非正式占位·第2题】你如何理解智驾测试中的场景覆盖？",
    "【非正式占位·第3题】遇到传感器数据异常时，你会先检查哪些环节？",
    "【非正式占位·第4题】请说明一次你排查问题的思路（非正式演示题）。",
    "【非正式占位·第5题】团队协作中你如何同步风险与进度？（非正式）",
    "【非正式占位·第6题】如果入职后前三个月，你会优先补齐哪项能力？",
  ];
}

function mockMainQuestion(seq: number): Question {
  const texts = mockMainTexts();
  return {
    text: texts[seq - 1] ?? texts[0],
    audioUrl: null,
    seq,
  };
}

function mockFollowupQuestion(seq: number): Question {
  return {
    text: `【非正式追问·沿用第${seq}题】请再补充一个具体例子（演示固定追问，非正式数据）。`,
    audioUrl: null,
    seq,
  };
}

type MockInterviewView = Extract<View, { phase: "interview"; mode: "mock" }>;

function advanceMockInterview(
  current: MockInterviewView,
  _normalizedAnswer: string,
): MockInterviewView | Extract<View, { phase: "mock_done" }> {
  if (current.isFollowup) {
    if (current.question.seq >= TOTAL_QUESTIONS) {
      return { phase: "mock_done", job: current.job };
    }
    return {
      phase: "interview",
      mode: "mock",
      job: current.job,
      question: mockMainQuestion(current.question.seq + 1),
      isFollowup: false,
      followupIssued: current.followupIssued,
    };
  }

  if (current.question.seq === MOCK_FOLLOWUP_SEQ && !current.followupIssued) {
    return {
      phase: "interview",
      mode: "mock",
      job: current.job,
      question: mockFollowupQuestion(MOCK_FOLLOWUP_SEQ),
      isFollowup: true,
      followupIssued: true,
    };
  }

  if (current.question.seq >= TOTAL_QUESTIONS) {
    return { phase: "mock_done", job: current.job };
  }

  return {
    phase: "interview",
    mode: "mock",
    job: current.job,
    question: mockMainQuestion(current.question.seq + 1),
    isFollowup: false,
    followupIssued: current.followupIssued,
  };
}

type ApiErrorInfo = {
  status: number;
  code: string | null;
  serverMessage: string | null;
};

function formatApiError(info: ApiErrorInfo, action: string, tail: string): string {
  const codeText = info.code ? `，${info.code}` : "";
  const messageText = info.serverMessage ? `：${info.serverMessage}` : "";
  return `${action}（HTTP ${info.status}${codeText}）${messageText}。${tail}`;
}

async function readApiError(response: Response): Promise<ApiErrorInfo> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { status: response.status, code: null, serverMessage: null };
  }
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return { status: response.status, code: null, serverMessage: null };
  }
  const code = nonEmptyString(payload.detail.code);
  const serverMessage = nonEmptyString(payload.detail.message);
  return { status: response.status, code, serverMessage };
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

async function loadRealJobList(): Promise<ParseOk<Job[]> | ParseErr> {
  let response: Response;
  try {
    response = await fetch("/api/jobs", {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return { ok: false, message: "网络失败，未能获取岗位列表。未改用演示数据。" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return {
      ok: false,
      message: formatApiError(info, "岗位列表请求失败", "未改用演示数据。"),
    };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, message: "岗位响应不是合法 JSON。未进入面试。" };
  }
  return parseJobs(payload);
}

type RealSessionResult =
  | { kind: "network" }
  | { kind: "http"; status: number; code: string | null; serverMessage: string | null }
  | { kind: "invalid"; message: string }
  | { kind: "ok"; sid: number; question: Question };

async function requestRealSession(jobId: number): Promise<RealSessionResult> {
  let response: Response;
  try {
    response = await fetch("/api/sessions", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id: jobId }),
      cache: "no-store",
    });
  } catch {
    return { kind: "network" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return { kind: "http", ...info };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "invalid", message: "会话响应不是合法 JSON。未进入面试。" };
  }
  const parsed = parseSession(payload);
  if (!parsed.ok) {
    return { kind: "invalid", message: parsed.message };
  }
  return { kind: "ok", sid: parsed.value.sid, question: parsed.value.question };
}

type AnswerOk =
  | { type: "followup"; question: Question; transitionAudioUrl: string | null }
  | { type: "next"; question: Question; transitionAudioUrl: string | null }
  | { type: "done"; reportId: number; transitionAudioUrl: string | null };

type TextAnswerResult =
  | { kind: "network" }
  | { kind: "http"; status: number; code: string | null; serverMessage: string | null }
  | { kind: "invalid"; message: string }
  | { kind: "ok"; value: AnswerOk };

async function requestTextAnswer(sid: number, answerText: string): Promise<TextAnswerResult> {
  let response: Response;
  try {
    response = await fetch(`/api/sessions/${sid}/answers/text`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ answer_text: answerText }),
      cache: "no-store",
    });
  } catch {
    return { kind: "network" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return { kind: "http", ...info };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "invalid", message: "回答响应不是合法 JSON。未推进题目。" };
  }
  const parsed = parseAnswerResponse(payload);
  if (!parsed.ok) {
    return { kind: "invalid", message: parsed.message };
  }
  return { kind: "ok", value: parsed.value };
}

type AudioAnswerResult = TextAnswerResult;

/**
 * 语音答题：multipart 提交 webm/opus 与客户端声学统计（duration_s/pause_cnt）。
 * 不设置 Content-Type（由浏览器自动带 multipart boundary）。
 */
async function requestAudioAnswer(
  sid: number,
  blob: Blob,
  durationS: number,
  pauseCnt: number,
): Promise<AudioAnswerResult> {
  const form = new FormData();
  form.append("audio", new File([blob], "answer.webm", { type: blob.type || "audio/webm" }));
  form.append("duration_s", durationS.toFixed(1));
  form.append("pause_cnt", String(pauseCnt));

  let response: Response;
  try {
    response = await fetch(`/api/sessions/${sid}/answers`, {
      method: "POST",
      body: form,
      cache: "no-store",
    });
  } catch {
    return { kind: "network" };
  }
  if (!response.ok) {
    const info = await readApiError(response);
    return { kind: "http", ...info };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "invalid", message: "语音回答响应不是合法 JSON。未推进题目。" };
  }
  const parsed = parseAnswerResponse(payload);
  if (!parsed.ok) {
    return { kind: "invalid", message: parsed.message };
  }
  return { kind: "ok", value: parsed.value };
}

function formatMicError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "麦克风权限被拒绝。请在浏览器地址栏允许麦克风后重新开始录音。";
    }
    if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
      return "未检测到可用麦克风设备，无法进行语音回答。";
    }
  }
  return "麦克风初始化失败，请检查设备后重试。";
}

function parseJobs(payload: unknown): ParseOk<Job[]> | ParseErr {
  if (!isRecord(payload) || !Array.isArray(payload.jobs)) {
    return {
      ok: false,
      message: "岗位响应格式不正确：jobs 必须是数组。未进入面试。",
    };
  }
  const jobs: Job[] = [];
  for (const item of payload.jobs) {
    if (!isRecord(item) || !isPositiveInt(item.id)) {
      return {
        ok: false,
        message: "岗位响应格式不正确：id 必须为正整数。未进入面试。",
      };
    }
    if (typeof item.family !== "string" || typeof item.title !== "string" || typeof item.jd_digest !== "string") {
      return {
        ok: false,
        message: "岗位响应格式不正确：family、title、jd_digest 必须为字符串。未进入面试。",
      };
    }
    jobs.push({
      id: item.id,
      family: item.family,
      title: item.title,
      jdDigest: item.jd_digest,
    });
  }
  return { ok: true, value: jobs };
}

function parseSession(payload: unknown): ParseOk<{ sid: number; question: Question }> | ParseErr {
  const invalid =
    "会话响应格式不正确：sid 须为正整数，question.text 须为非空字符串，seq 须为 1–6 的整数，audio_url 须为 null 或非空字符串。未进入面试。";
  if (!isRecord(payload) || !isPositiveInt(payload.sid) || !isRecord(payload.question)) {
    return { ok: false, message: invalid };
  }
  const question = parseQuestion(payload.question);
  if (!question) {
    return { ok: false, message: invalid };
  }
  return {
    ok: true,
    value: {
      sid: payload.sid,
      question,
    },
  };
}

function parseAnswerResponse(payload: unknown): ParseOk<AnswerOk> | ParseErr {
  const invalid =
    "回答响应格式不正确：type 须为 followup/next/done；followup/next 须含合法 question；done.report_id 须为正整数；transition_audio_url 若存在须为 null 或非空字符串。未推进题目。";
  if (!isRecord(payload) || typeof payload.type !== "string") {
    return { ok: false, message: invalid };
  }
  if (!isOptionalAudioUrl(payload.transition_audio_url)) {
    return { ok: false, message: invalid };
  }
  const transitionAudioUrl = isAudioUrl(payload.transition_audio_url)
    ? payload.transition_audio_url
    : null;

  if (payload.type === "done") {
    if (!isPositiveInt(payload.report_id)) {
      return { ok: false, message: invalid };
    }
    return {
      ok: true,
      value: { type: "done", reportId: payload.report_id, transitionAudioUrl },
    };
  }

  if (payload.type === "followup" || payload.type === "next") {
    if (!isRecord(payload.question)) {
      return { ok: false, message: invalid };
    }
    const question = parseQuestion(payload.question);
    if (!question) {
      return { ok: false, message: invalid };
    }
    return {
      ok: true,
      value: { type: payload.type, question, transitionAudioUrl },
    };
  }

  return { ok: false, message: invalid };
}

function parseQuestion(value: Record<string, unknown>): Question | null {
  if (typeof value.text !== "string" || value.text.trim().length === 0) {
    return null;
  }
  if (!isQuestionSeq(value.seq)) {
    return null;
  }
  if (!isAudioUrl(value.audio_url)) {
    return null;
  }
  return {
    text: value.text,
    audioUrl: value.audio_url,
    seq: value.seq,
  };
}

function isOptionalAudioUrl(value: unknown): boolean {
  return value === undefined || isAudioUrl(value);
}

function isAudioUrl(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length > 0);
}

function isQuestionSeq(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= TOTAL_QUESTIONS;
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
