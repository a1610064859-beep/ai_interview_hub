export const EDUCATION_LEVELS = ["中职", "高职/大专", "本科", "硕士", "博士"] as const;

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
