"use client";

import { useEffect, useState } from "react";

type Student = { id: number; name_masked: string; major: string | null; grade: string | null };
type CounselResult = {
  mode: "新生"; degraded: boolean; recommended_job_id: number;
  train_hint: { job_id: number; mode: "新生" };
  job_map: Array<{ job_id: number; family: string; title: string; chain_role: string; core_skills: string[]; fit_summary: string }>;
  gaps: Array<{ job_id: number; skill: string; current_hint: string; target_hint: string; suggested_action: string }>;
  learning_path: { grade: string; theme: string; milestones: Array<{ term: string; items: string[] }> };
};

export default function CounselPage() {
  const [students, setStudents] = useState<Student[]>([]);
  const [userId, setUserId] = useState<number | null>(null);
  const [interests, setInterests] = useState("");
  const [result, setResult] = useState<CounselResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const student = students.find((item) => item.id === userId) ?? null;

  useEffect(() => {
    void fetch("/api/students").then(async (response) => {
      if (!response.ok) throw new Error("学生档案加载失败");
      const body = await response.json() as { students: Student[] };
      setStudents(body.students);
      setUserId(body.students[0]?.id ?? null);
    }).catch(() => setMessage("无法加载学生档案，暂不能开始咨询。"));
  }, []);

  async function submit() {
    if (!student || busy) return;
    setBusy(true); setMessage(null); setResult(null);
    try {
      const response = await fetch("/api/counsel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ major: student.major, grade: student.grade, interests: interests.split(/[，,]/).map((x) => x.trim()).filter(Boolean) }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.detail?.message ?? `咨询失败（HTTP ${response.status}）`);
      setResult(body as CounselResult);
    } catch (error) { setMessage(error instanceof Error ? error.message : "咨询失败"); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto max-w-5xl px-4 py-8 text-white">
    <a href="/" className="text-sm text-[#7eb6ff]">← 返回面试仓</a>
    <h1 className="mt-4 text-3xl font-semibold">新生 · 智能汽车岗位路径</h1>
    <p className="mt-2 text-[#9fb4d4]">咨询输入不会修改学生档案</p>
    <section className="mt-6 grid gap-4 rounded-3xl border border-[#2f6fed] bg-[#0c1730]/90 p-6 md:grid-cols-2">
      <label className="text-sm text-[#9fb4d4]">学生档案<select className="mt-2 w-full rounded-xl bg-[#050912] p-3 text-white" value={userId ?? ""} onChange={(e) => setUserId(Number(e.target.value))}>{students.map((s) => <option key={s.id} value={s.id}>{s.name_masked}</option>)}</select></label>
      <div className="text-sm text-[#9fb4d4]">专业 / 年级（只读）<div className="mt-2 rounded-xl border border-white/10 p-3 text-white">{student?.major ?? "未填写"} · {student?.grade ?? "未填写"}</div></div>
      <label className="text-sm text-[#9fb4d4] md:col-span-2">兴趣（逗号分隔，可留空）<input className="mt-2 w-full rounded-xl bg-[#050912] p-3 text-white" value={interests} onChange={(e) => setInterests(e.target.value)} /></label>
      <button className="rounded-full bg-[#ff8a2a] px-5 py-3 text-[#170b02] disabled:opacity-50" disabled={!student || !student.major || !student.grade || busy} onClick={() => void submit()}>{busy ? "生成中…" : "生成岗位路径"}</button>
    </section>
    {message ? <p role="alert" className="mt-4 rounded-xl border border-[#ff8a2a] p-4 text-[#ffd0a8]">{message}</p> : null}
    {result ? <section className="mt-6 space-y-5">
      {result.degraded ? <p className="rounded-xl border border-[#ff8a2a] p-3 text-[#ffd0a8]">当前使用静态路径建议，训练功能不受影响。</p> : null}
      <div className="grid gap-4 md:grid-cols-2">{result.job_map.map((job) => <article key={job.job_id} className="rounded-2xl border border-[#2f6fed]/60 bg-[#0c1730] p-5"><h2 className="text-xl">{job.title}</h2><p className="mt-2 text-sm text-[#9fb4d4]">{job.chain_role}</p><p className="mt-3 text-sm">{job.fit_summary}</p><p className="mt-3 text-xs text-[#7eb6ff]">{job.core_skills.join(" · ")}</p><a className="mt-4 inline-block rounded-full border border-[#ff8a2a] px-4 py-2 text-[#ffb067]" href={`/?user_id=${userId}&job_id=${job.job_id}&mode=${encodeURIComponent("新生")}`}>进入该岗位训练</a></article>)}</div>
      <article className="rounded-2xl border border-white/10 p-5"><h2 className="text-xl">{result.learning_path.theme}</h2>{result.learning_path.milestones.map((m) => <div key={m.term} className="mt-3"><strong>{m.term}</strong><p className="text-sm text-[#9fb4d4]">{m.items.join(" · ")}</p></div>)}</article>
    </section> : null}
  </main>;
}
