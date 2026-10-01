export const EDUCATION_LEVELS = ["中职", "高职/大专", "本科", "硕士", "博士"] as const;

const rank = new Map<string, number>(EDUCATION_LEVELS.map((level, index) => [level, index]));

export type CandidateSortOption = "weighted_score" | "education_level" | "overall_score";

export const SORT_OPTIONS: { id: CandidateSortOption; label: string; desc: string }[] = [
  {
    id: "weighted_score",
    label: "岗位加权分优先",
    desc: "按企业自定义的人才需求权重综合计算，由高到低排序（推荐默认）",
  },
  {
    id: "education_level",
    label: "学历层次优先",
    desc: "按学历层次（博士 → 硕士 → 本科 → 高职 → 中职）由高到低排序",
  },
  {
    id: "overall_score",
    label: "面试总分优先",
    desc: "按面试能力报告的等权 overall 得分由高到低排序",
  },
];

export function filterCandidatesBySchoolNames<T extends { user_id: number }>(
  candidates: readonly T[],
  schoolNames: Readonly<Record<number, string | null>>,
  selectedNames: readonly (string | null)[],
): T[] {
  if (selectedNames.length === 0) return [...candidates];
  const selected = new Set(selectedNames);
  return candidates.filter((candidate) => selected.has(schoolNames[candidate.user_id] ?? null));
}

export function schoolNameOptions<T extends { user_id: number }>(
  candidates: readonly T[],
  schoolNames: Readonly<Record<number, string | null>>,
): { name: string | null; count: number }[] {
  const counts = new Map<string | null, number>();
  candidates.forEach((candidate) => {
    const name = schoolNames[candidate.user_id] ?? null;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  });
  return Array.from(counts, ([name, count]) => ({ name, count }));
}

export function sortCandidatesByEducation<T extends { education_level: string | null }>(
  candidates: readonly T[],
  direction: "asc" | "desc" = "desc",
): T[] {
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((a, b) => {
      const aRank = a.candidate.education_level === null ? undefined : rank.get(a.candidate.education_level);
      const bRank = b.candidate.education_level === null ? undefined : rank.get(b.candidate.education_level);
      if (aRank === undefined) return bRank === undefined ? a.index - b.index : 1;
      if (bRank === undefined) return -1;
      return (direction === "desc" ? bRank - aRank : aRank - bRank) || a.index - b.index;
    })
    .map(({ candidate }) => candidate);
}

export function sortCandidatesByOverall<T extends { overall: number | null }>(
  candidates: readonly T[],
): T[] {
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((a, b) => {
      const aScore = a.candidate.overall;
      const bScore = b.candidate.overall;
      if (aScore === null || aScore === undefined) return bScore === null || bScore === undefined ? a.index - b.index : 1;
      if (bScore === null || bScore === undefined) return -1;
      return bScore - aScore || a.index - b.index;
    })
    .map(({ candidate }) => candidate);
}
