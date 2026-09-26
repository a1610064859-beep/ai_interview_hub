export const EDUCATION_LEVELS = ["中职", "高职/大专", "本科", "硕士", "博士"] as const;
export const SCHOOL_TIER_LEVELS = ["中职/技校", "高职/大专", "普通本科", "211/双一流", "C9/985"] as const;

const rank = new Map<string, number>(EDUCATION_LEVELS.map((level, index) => [level, index]));

export function sortCandidatesByEducation<T extends { education_level: string | null }>(
  candidates: readonly T[],
  direction: "asc" | "desc",
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

const schoolTierRank = new Map<string, number>(SCHOOL_TIER_LEVELS.map((level, index) => [level, index]));

export function sortCandidatesBySchoolTier<T extends { school_tier: string | null }>(
  candidates: readonly T[],
  direction: "asc" | "desc",
): T[] {
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((a, b) => {
      const aRank = a.candidate.school_tier === null ? undefined : schoolTierRank.get(a.candidate.school_tier);
      const bRank = b.candidate.school_tier === null ? undefined : schoolTierRank.get(b.candidate.school_tier);
      if (aRank === undefined) return bRank === undefined ? a.index - b.index : 1;
      if (bRank === undefined) return -1;
      return (direction === "desc" ? bRank - aRank : aRank - bRank) || a.index - b.index;
    })
    .map(({ candidate }) => candidate);
}
