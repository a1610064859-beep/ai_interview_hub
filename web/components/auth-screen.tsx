"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

type AccountRole = "student" | "recruiter";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string") return body.detail.message;
  } catch {
    // Use the generic fallback when a proxy returns a non-JSON error.
  }
  return "请求失败，请检查输入后重试。";
}

function assessPasswordStrength(password: string) {
  const hasLetter = /[A-Za-z]/.test(password);
  const hasDigit = /[0-9]/.test(password);
  const meetsMinimum = password.length >= 9 && hasLetter && hasDigit;
  if (!meetsMinimum) {
    const hint = password.length < 9
      ? "至少 9 位"
      : !hasLetter && !hasDigit
        ? "还需英文字母和数字"
        : !hasLetter
          ? "还需英文字母"
          : "还需数字";
    return { level: 1, label: "未达要求", hint, meetsMinimum };
  }

  const extraChecks = [
    password.length >= 12,
    /[a-z]/.test(password) && /[A-Z]/.test(password),
    /[^A-Za-z0-9]/.test(password),
    password.length >= 16,
  ].filter(Boolean).length;
  const level = extraChecks >= 3 ? 3 : extraChecks >= 1 ? 2 : 1;
  const label = level === 3 ? "强" : level === 2 ? "中" : "弱";
  const hint = level === 1
    ? "弱密码仍可注册；可增加长度或组合大小写、符号提升强度。"
    : level === 2
      ? "可以注册；增加长度或字符组合可进一步提升强度。"
      : "强度较好。";
  return { level, label, hint, meetsMinimum };
}

export default function AuthScreen({ initialRegister = false }: { initialRegister?: boolean }) {
  const router = useRouter();
  const [role, setRole] = useState<AccountRole>("student");
  const [email, setEmail] = useState("");
  const [studentName, setStudentName] = useState("");
  const [major, setMajor] = useState("");
  const [grade, setGrade] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [contactName, setContactName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordStrength = assessPasswordStrength(password);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    if (initialRegister && password !== passwordConfirm) {
      setError("两次输入的密码不一致。");
      return;
    }
    setBusy(true);
    try {
      const endpoint = initialRegister
        ? `/api/auth/register/${role}`
        : `/api/auth/login/${role}`;
      const body = role === "student"
        ? initialRegister
          ? { email, name: studentName, major, grade, password }
          : { email, password }
        : initialRegister
          ? { email, organization_name: organizationName, contact_name: contactName, password }
          : { email, password };
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const payload: unknown = await response.json();
      if (!isRecord(payload) || !isRecord(payload.user)) throw new Error("登录响应格式错误。");
      const userRole = payload.user.role;
      router.replace(userRole === "student" ? "/" : "/recruiter");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法完成请求，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-[#050912] px-4 py-8 text-[#d7e3f7]">
      <section className="auth-screen-panel w-full max-w-lg rounded-3xl border border-[#2f6fed]/60 bg-[#0c1730]/95 p-5 shadow-[0_0_32px_rgba(47,111,237,0.22)] sm:p-8">
        <p className="text-xs tracking-[0.2em] text-[#7eb6ff]">AI INTERVIEW HUB · SECURE ACCESS</p>
        <h1 className="mt-3 text-2xl font-semibold text-white">{initialRegister ? "创建账号" : "登录面试仓"}</h1>
        <p className="mt-2 text-sm text-[#9fb4d4]">学生训练记录按本人账号隔离，企业功能仅企业账号可访问。</p>

        <div className="mt-6 grid grid-cols-2 gap-2 rounded-2xl border border-[#2f6fed]/30 bg-[#050912] p-1.5" role="tablist" aria-label="账号类型">
          {([ ["student", "学生端"], ["recruiter", "企业端"] ] as const).map(([value, label]) => (
            <button key={value} type="button" role="tab" aria-selected={role === value} onClick={() => { setRole(value); setError(null); }} className={`rounded-xl px-3 py-2.5 text-sm ${role === value ? "bg-[#17428f] text-white" : "text-[#9fb4d4] hover:bg-[#0c1730]"}`}>
              {label}
            </button>
          ))}
        </div>

        <form className="mt-5 space-y-4" onSubmit={(event) => void submit(event)}>
          {role === "student" && initialRegister ? (
            <>
              <label className="block text-sm text-[#9fb4d4]">
                姓名
                <input required autoComplete="name" value={studentName} onChange={(event) => setStudentName(event.target.value)} minLength={1} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
              </label>
              <label className="block text-sm text-[#9fb4d4]">
                专业
                <input required autoComplete="organization-title" value={major} onChange={(event) => setMajor(event.target.value)} minLength={1} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
              </label>
              <label className="block text-sm text-[#9fb4d4]">
                年级
                <input required value={grade} onChange={(event) => setGrade(event.target.value)} minLength={1} maxLength={64} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
              </label>
            </>
          ) : null}
          {role === "student" ? (
            <label className="block text-sm text-[#9fb4d4]">
              邮箱
              <input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
            </label>
          ) : null}
          {role === "recruiter" ? (
            <>
              {initialRegister ? (
                <>
                  <label className="block text-sm text-[#9fb4d4]">
                    企业名称
                    <input required autoComplete="organization" value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} minLength={2} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
                  </label>
                  <label className="block text-sm text-[#9fb4d4]">
                    联系人
                    <input required autoComplete="name" value={contactName} onChange={(event) => setContactName(event.target.value)} minLength={2} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
                  </label>
                </>
              ) : null}
              <label className="block text-sm text-[#9fb4d4]">
                企业邮箱
                <input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
              </label>
            </>
          ) : null}

          <label className="block text-sm text-[#9fb4d4]">
            密码
            <input required type="password" autoComplete={initialRegister ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} minLength={initialRegister ? 9 : 1} pattern={initialRegister ? "(?=.*[A-Za-z])(?=.*[0-9]).*" : undefined} title={initialRegister ? "密码至少9位，且必须包含英文字母和数字" : undefined} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" placeholder={initialRegister ? "至少9位，包含字母和数字" : "请输入密码"} />
            {initialRegister ? (
              <span className="mt-1 block text-xs text-[#9fb4d4]">至少 9 位，且含英文字母和数字；强度仅作提示，弱密码也能注册。</span>
            ) : null}
          </label>

          {initialRegister && password ? (
            <div className="-mt-2 rounded-lg bg-[#071225] px-3 py-2 text-xs text-[#9fb4d4]" aria-live="polite">
              <div className="flex items-center gap-2">
                <div className="flex flex-1 gap-1" role="img" aria-label={`密码强度：${passwordStrength.label}`}>
                  {[1, 2, 3].map((segment) => (
                    <span
                      key={segment}
                      className={`h-1.5 flex-1 rounded-full ${
                        segment > passwordStrength.level
                          ? "bg-slate-700"
                          : !passwordStrength.meetsMinimum
                            ? "bg-rose-500"
                            : passwordStrength.level === 1
                              ? "bg-rose-400"
                              : passwordStrength.level === 2
                                ? "bg-amber-400"
                                : "bg-emerald-400"
                      }`}
                    />
                  ))}
                </div>
                <strong className={passwordStrength.meetsMinimum ? "text-white" : "text-rose-300"}>{passwordStrength.label}</strong>
              </div>
              <p className="mt-1">{passwordStrength.hint}</p>
            </div>
          ) : null}

          {initialRegister ? (
            <label className="block text-sm text-[#9fb4d4]">
              确认密码
              <input required type="password" autoComplete="new-password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} minLength={9} maxLength={128} className="mt-2 w-full rounded-xl border border-[#2f6fed]/60 bg-[#050912] px-3 py-3 text-white outline-none focus:border-[#7eb6ff]" />
            </label>
          ) : null}

          {initialRegister ? (
            <p className="rounded-xl border border-[#2f6fed]/30 bg-[#071225] px-3 py-2 text-xs leading-5 text-[#9fb4d4]">
              {role === "student" ? "学生姓名仅以脱敏形式保存；邮箱目前作为登录账号，不发送验证邮件。" : "企业邮箱目前作为登录账号，不发送验证邮件。"}
            </p>
          ) : null}

          {error ? <p className="rounded-xl border border-[#ff8a2a] bg-[#2a1608] px-3 py-2 text-sm text-[#ffd0a8]" role="alert">{error}</p> : null}
          <button type="submit" disabled={busy} className="auth-primary w-full rounded-full bg-[#ff8a2a] px-4 py-3 font-semibold text-[#1a0d04] disabled:opacity-50">
            {busy ? "正在处理…" : initialRegister ? "注册并进入" : "登录"}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-[#9fb4d4]">
          {initialRegister ? "已有账号？" : "还没有账号？"}{" "}
          <Link href={initialRegister ? "/login" : "/register"} className="text-[#7eb6ff] underline underline-offset-4">
            {initialRegister ? "返回登录" : "立即注册"}
          </Link>
        </p>
      </section>
    </main>
  );
}
