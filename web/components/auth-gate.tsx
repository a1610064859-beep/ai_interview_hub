"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

type AuthUser = {
  id: number;
  role: "student" | "recruiter" | "admin";
  name_masked: string | null;
  organization_name: string | null;
};

type AuthPayload = { authenticated: boolean; user: AuthUser | null };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function roleHome(role: AuthUser["role"]): string {
  return role === "student" ? "/" : "/recruiter";
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const isPublicPage = pathname === "/login" || pathname === "/register";
  const isRecruiterPage = pathname === "/recruiter" || pathname.startsWith("/recruiter/");
  const isReportPage = pathname.startsWith("/reports/");

  useEffect(() => {
    let alive = true;
    if (isPublicPage) {
      setChecking(false);
      setUser(null);
      return () => { alive = false; };
    }

    setChecking(true);
    void (async () => {
      try {
        const response = await fetch("/api/auth/me", { cache: "no-store" });
        const payload: unknown = await response.json();
        if (!response.ok || !isRecord(payload) || payload.authenticated !== true || !isRecord(payload.user)) {
          if (alive) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        const role = payload.user.role;
        if (role !== "student" && role !== "recruiter" && role !== "admin") {
          if (alive) router.replace("/login");
          return;
        }
        const currentUser: AuthUser = {
          id: Number(payload.user.id),
          role,
          name_masked: typeof payload.user.name_masked === "string" ? payload.user.name_masked : null,
          organization_name: typeof payload.user.organization_name === "string" ? payload.user.organization_name : null,
        };
        if (alive) setUser(currentUser);
        if (isRecruiterPage && currentUser.role === "student") {
          if (alive) router.replace("/");
        } else if (!isRecruiterPage && !isReportPage && currentUser.role !== "student") {
          if (alive) router.replace(roleHome(currentUser.role));
        }
      } catch {
        if (alive) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      } finally {
        if (alive) setChecking(false);
      }
    })();

    return () => { alive = false; };
  }, [isPublicPage, isRecruiterPage, isReportPage, pathname, router]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
    router.replace("/login");
    router.refresh();
  }

  if (isPublicPage) return <>{children}</>;
  if (checking || !user) {
    return (
      <main className="grid min-h-dvh place-items-center bg-[#050912] px-4 text-[#d7e3f7]">
        <p role="status" className="rounded-xl border border-[#2f6fed]/50 bg-[#0c1730] px-5 py-3 text-sm text-[#9fb4d4]">正在验证登录状态…</p>
      </main>
    );
  }

  const roleLabel = user.role === "student" ? "学生" : "企业";
  const displayName = user.organization_name ?? user.name_masked ?? roleLabel + "账号";
  return (
    <>
      {children}
      <div className="fixed bottom-3 right-3 z-[100] flex max-w-[calc(100vw-1.5rem)] items-center gap-2 rounded-full border border-[#2f6fed]/60 bg-[#071225]/95 px-3 py-2 text-xs text-[#9fb4d4] shadow-lg backdrop-blur">
        <span className="max-w-40 truncate">{roleLabel} · {displayName}</span>
        <button type="button" onClick={() => void logout()} className="rounded-full border border-[#ff8a2a]/60 px-2.5 py-1 text-[#ffb36b]">退出</button>
      </div>
    </>
  );
}
