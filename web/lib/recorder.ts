/**
 * T6 语音录制器：浏览器 MediaRecorder(webm/opus) + AnalyserNode 声学统计。
 *
 * 声学口径（AGENTS §6.3，服务端禁止依赖 ASR 词级时间戳）：
 * - duration_s：录音持续秒数（回答时长）；
 * - pause_cnt：电平低于 -45dB 且持续超过 1.5s 记 1 次停顿；
 * - level01：实时电平（0..1），用于 HMI 电平环动画。
 * countPauses 为纯函数，独立于浏览器可单测。
 */

export const SILENCE_DB_THRESHOLD = -45;
export const SILENCE_RUN_SECONDS = 1.5;
/** 浮点累加容差：采样间隔逐步累加时避免 1.5000000002 之类的噪声越过 1.5s 边界。 */
const RUN_SECONDS_EPSILON = 1e-9;
const SAMPLE_INTERVAL_MS = 100;

export interface VoiceRecording {
  blob: Blob;
  durationS: number;
  pauseCnt: number;
}

/**
 * 纯函数：按固定采样间隔的电平序列（dB）统计停顿次数。
 * 一次持续静音（episode）无论多长只计 1 次；被声音打断则结束该次停顿，之后重新起算。
 */
export function countPauses(levelDbSamples: number[], intervalS: number): number {
  if (!(intervalS > 0)) {
    return 0;
  }
  let pauses = 0;
  let runSeconds = 0;
  let inPause = false;
  for (const db of levelDbSamples) {
    if (db < SILENCE_DB_THRESHOLD) {
      runSeconds += intervalS;
      if (!inPause && runSeconds > SILENCE_RUN_SECONDS + RUN_SECONDS_EPSILON) {
        pauses += 1;
        inPause = true;
      }
    } else {
      runSeconds = 0;
      inPause = false;
    }
  }
  return pauses;
}

/** 电平归一化（-60dB..0dB → 0..1），供电平环动画使用。 */
export function levelToUnit(levelDb: number): number {
  const clamped = Math.max(-60, Math.min(0, levelDb));
  return Math.round(((clamped + 60) / 60) * 100) / 100;
}

function pickRecorderMime(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm"];
  for (const mime of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return "";
}

export class VoiceRecorder {
  private stream: MediaStream;
  private context: AudioContext;
  private analyser: AnalyserNode;
  private recorder: MediaRecorder;
  private chunks: Blob[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private levelDbSamples: number[] = [];
  private startedAt = 0;
  private elapsedBase = 0;
  private stopped = false;
  latestLevelDb = -60;

  private constructor(
    stream: MediaStream,
    context: AudioContext,
    analyser: AnalyserNode,
    recorder: MediaRecorder,
  ) {
    this.stream = stream;
    this.context = context;
    this.analyser = analyser;
    this.recorder = recorder;
  }

  static async create(): Promise<VoiceRecorder> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);

    const mime = pickRecorderMime();
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    return new VoiceRecorder(stream, context, analyser, recorder);
  }

  start(): void {
    if (this.timer !== null) {
      return;
    }
    this.chunks = [];
    this.levelDbSamples = [];
    this.stopped = false;
    this.startedAt = performance.now();
    this.elapsedBase = 0;
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
      }
    };
    this.recorder.start(SAMPLE_INTERVAL_MS);

    const buffer = new Float32Array(this.analyser.fftSize);
    this.timer = setInterval(() => {
      this.analyser.getFloatTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i += 1) {
        sum += buffer[i] * buffer[i];
      }
      const rms = Math.sqrt(sum / buffer.length);
      const db = rms > 0 ? 20 * Math.log10(rms) : -120;
      this.latestLevelDb = Math.max(-120, db);
      this.levelDbSamples.push(this.latestLevelDb);
    }, SAMPLE_INTERVAL_MS);
  }

  get elapsedS(): number {
    if (this.timer === null || this.stopped) {
      return Math.round(this.elapsedBase * 10) / 10;
    }
    return Math.round(((performance.now() - this.startedAt) / 1000) * 10) / 10;
  }

  get level01(): number {
    return levelToUnit(this.latestLevelDb);
  }

  async stop(): Promise<VoiceRecording> {
    if (this.timer !== null) {
      this.elapsedBase = (performance.now() - this.startedAt) / 1000;
      clearInterval(this.timer);
      this.timer = null;
    }
    this.stopped = true;

    const blob = await new Promise<Blob>((resolve) => {
      this.recorder.onstop = () => {
        resolve(new Blob(this.chunks, { type: this.recorder.mimeType || "audio/webm" }));
      };
      if (this.recorder.state !== "inactive") {
        this.recorder.stop();
      } else {
        resolve(new Blob(this.chunks, { type: this.recorder.mimeType || "audio/webm" }));
      }
    });

    const durationS = Math.round(this.elapsedBase * 10) / 10;
    const pauseCnt = countPauses(this.levelDbSamples, SAMPLE_INTERVAL_MS / 1000);
    this.dispose();
    return { blob, durationS, pauseCnt };
  }

  dispose(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    for (const track of this.stream.getTracks()) {
      track.stop();
    }
    void this.context.close().catch(() => undefined);
  }
}

export type ParseOk<T> = { ok: true; value: T };
export type ParseErr = { ok: false; message: string };

export type QuestionData = {
  text: string;
  audioUrl: string | null;
  seq: number;
};

export type SessionCreateData = {
  sid: number;
  question: QuestionData;
  transitionAudioUrls: string[];
};

export type AnswerData =
  | { type: "followup"; question: QuestionData; transitionAudioUrl: string | null }
  | { type: "next"; question: QuestionData; transitionAudioUrl: string | null }
  | { type: "done"; reportId: number; transitionAudioUrl: string | null };

export function parseSessionResponse(payload: unknown): ParseOk<SessionCreateData> | ParseErr {
  const invalid =
    "会话响应格式不正确：sid 须为正整数，question.text 须为非空字符串，seq 须为 1–6 的整数，audio_url 须为 null 或非空字符串。未进入面试。";
  if (!isRecord(payload) || !isPositiveInt(payload.sid) || !isRecord(payload.question)) {
    return { ok: false, message: invalid };
  }
  const q = payload.question;
  if (
    typeof q.text !== "string" ||
    !q.text.trim() ||
    !isPositiveInt(q.seq) ||
    q.seq > 6 ||
    !(q.audio_url === null || (typeof q.audio_url === "string" && q.audio_url.trim().length > 0))
  ) {
    return { ok: false, message: invalid };
  }
  const transitionAudioUrls: string[] = [];
  if (Array.isArray(payload.transition_audio_urls)) {
    for (const item of payload.transition_audio_urls) {
      if (typeof item === "string" && item.trim()) {
        transitionAudioUrls.push(item.trim());
      }
    }
  }
  return {
    ok: true,
    value: {
      sid: payload.sid,
      question: {
        text: q.text.trim(),
        audioUrl: typeof q.audio_url === "string" ? q.audio_url.trim() : null,
        seq: q.seq,
      },
      transitionAudioUrls,
    },
  };
}

export function parseAnswerResponse(payload: unknown): ParseOk<AnswerData> | ParseErr {
  const invalid =
    "回答响应格式不正确：type 须为 followup/next/done；followup/next 须含合法 question；done.report_id 须为正整数；transition_audio_url 若存在须为 null 或非空字符串。未推进题目。";
  if (!isRecord(payload) || typeof payload.type !== "string") {
    return { ok: false, message: invalid };
  }
  if (!isOptionalAudioUrl(payload.transition_audio_url)) {
    return { ok: false, message: invalid };
  }
  const transitionAudioUrl =
    typeof payload.transition_audio_url === "string" && payload.transition_audio_url.trim()
      ? payload.transition_audio_url.trim()
      : null;

  if (payload.type === "done") {
    if (!isPositiveInt(payload.report_id)) {
      return { ok: false, message: invalid };
    }
    return {
      ok: true,
      value: {
        type: "done",
        reportId: payload.report_id,
        transitionAudioUrl,
      },
    };
  }

  if (payload.type === "followup" || payload.type === "next") {
    if (!isRecord(payload.question)) {
      return { ok: false, message: invalid };
    }
    const q = payload.question;
    if (
      typeof q.text !== "string" ||
      !q.text.trim() ||
      !isPositiveInt(q.seq) ||
      q.seq > 6 ||
      !(q.audio_url === null || (typeof q.audio_url === "string" && q.audio_url.trim().length > 0))
    ) {
      return { ok: false, message: invalid };
    }
    return {
      ok: true,
      value: {
        type: payload.type,
        question: {
          text: q.text.trim(),
          audioUrl: typeof q.audio_url === "string" ? q.audio_url.trim() : null,
          seq: q.seq,
        },
        transitionAudioUrl,
      },
    };
  }

  return { ok: false, message: invalid };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isPositiveInt(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v) && v > 0;
}

function isOptionalAudioUrl(v: unknown): boolean {
  if (v === undefined || v === null) {
    return true;
  }
  return typeof v === "string" && v.trim().length > 0;
}

/**
 * 纯函数：根据题号下标选取对应的预生成过渡语音频 URL（AGENTS §6.2）。
 * 数组为空或非合法字符串时返回 null。
 */
export function pickTransitionAudioUrl(urls: string[], index: number): string | null {
  if (!Array.isArray(urls) || urls.length === 0) {
    return null;
  }
  const positiveIndex = Math.max(0, Math.floor(index));
  const picked = urls[positiveIndex % urls.length];
  return typeof picked === "string" && picked.trim().length > 0 ? picked.trim() : null;
}

/**
 * 同步互斥动作锁：防止快速双击与并发操作，提供严格的获取与释放语义。
 */
export class ActionLock {
  private locked = false;

  /**
   * 尝试获取锁。若已被锁定则返回 false，否则锁定并返回 true。
   */
  acquire(): boolean {
    if (this.locked) {
      return false;
    }
    this.locked = true;
    return true;
  }

  /**
   * 释放锁。
   */
  release(): void {
    this.locked = false;
  }

  get isLocked(): boolean {
    return this.locked;
  }
}

/**
 * 过渡语播放控制器与防重追踪器（AGENTS §6.2）。
 *
 * 规则：
 * 1. 提交时按实际回答提交计数（answerCount）在预生成列表里轮转选取；
 * 2. 主问题与追问提交均累计 answerCount，避免同一 seq 重复选取相同过渡语；
 * 3. 提交时立即播放并记录 URL；
 * 4. 服务端响应返回 transition_audio_url 时，若本轮已播放过过渡语，禁止重复播放；
 * 5. 若提交时列表为空未播放，响应返回时作为兜底播放一次。
 */
export class TransitionAudioTracker {
  private lastPlayedUrl: string | null = null;
  private playedThisTurn = false;

  /**
   * 提交回答时立即触发过渡语播放：
   * 使用提交前的回答计数（answerCount）进行轮转。
   */
  onSubmissionPlay(urls: string[], answerCount: number): string | null {
    const url = pickTransitionAudioUrl(urls, answerCount);
    if (!url) {
      return null;
    }
    this.lastPlayedUrl = url;
    this.playedThisTurn = true;
    return url;
  }

  /**
   * 服务端响应返回时判定是否需要兜底播放：
   * 若提交时已播放（playedThisTurn === true），则清空标志并返回 null（禁止重复播放）；
   * 若提交时未播放且响应带有新 URL，返回该 URL 并在首次播放后记录。
   */
  shouldPlayOnResponse(responseUrl: string | null): string | null {
    if (this.playedThisTurn) {
      this.playedThisTurn = false;
      return null;
    }
    if (!responseUrl || responseUrl === this.lastPlayedUrl) {
      return null;
    }
    this.lastPlayedUrl = responseUrl;
    return responseUrl;
  }

  get hasPlayedThisTurn(): boolean {
    return this.playedThisTurn;
  }

  get lastUrl(): string | null {
    return this.lastPlayedUrl;
  }

  reset(): void {
    this.lastPlayedUrl = null;
    this.playedThisTurn = false;
  }
}

/**
 * 题目音频自动播放追踪器：
 * 每道新题（或追问）首次渲染时尝试自动播放一次，相同题目或组件重渲染不重复触发。
 */
export class QuestionAudioPlayer {
  private playedKey: string | null = null;

  shouldAutoplay(seq: number, isFollowup: boolean, audioUrl: string | null): boolean {
    if (!audioUrl || !audioUrl.trim()) {
      return false;
    }
    const key = `${seq}-${isFollowup ? "f" : "m"}-${audioUrl.trim()}`;
    if (this.playedKey === key) {
      return false;
    }
    this.playedKey = key;
    return true;
  }

  get currentKey(): string | null {
    return this.playedKey;
  }

  reset(): void {
    this.playedKey = null;
  }
}