export const NANXI_RACES: Record<string, string> = {
  "nanxi-race-20260919": "ABCDE", "nanxi-race-20260920": "FG",
};
export const NANXI_CATEGORIES: Record<string, [string, string, number, number | null]> = {
  A: ["男子单人", "individual", 1, 0], B: ["女子单人", "individual", 1, 1],
  C: ["男子双人", "doubles", 2, 0], D: ["女子双人", "doubles", 2, 2],
  E: ["混合双人", "doubles", 2, 1], F: ["双人接力", "doubles", 2, null],
  G: ["四人接力", "team", 4, null],
};
export function nanxiRegistration(payload: Record<string, unknown>, entry: {entryType: string; memberNames: string[]}) {
  const raceId = String(payload.raceId || "");
  if (!NANXI_RACES[raceId]) return {};
  const bib = String(payload.bibNumber || "").trim().toUpperCase();
  if (!/^[A-G]-[0-9]{3}$/.test(bib) || bib.endsWith("-000")) throw new Error("选手号格式为 A-001 至 G-999，不能使用 000");
  const category = bib[0];
  if (!NANXI_RACES[raceId].includes(category)) throw new Error("该选手号不属于所选比赛日期：19 日 A–E，20 日 F/G");
  const [label, type, members, defaultFemales] = NANXI_CATEGORIES[category];
  if (entry.entryType !== type || entry.memberNames.length !== members) throw new Error(`${label}需要 ${members} 位成员，参赛类型为 ${type}`);
  if (payload.categoryCode && payload.categoryCode !== category) throw new Error("组别与固定选手号不一致");
  const females = defaultFemales ?? payload.femaleCount;
  if (typeof females !== "number" || !Number.isInteger(females) || females < 0 || females > members) throw new Error(`请确认女性参赛人数（0–${members}）`);
  return {category_code: category, female_count: females};
}
export function rankNanxiCategories(results: Record<string, any>[]) {
  for (const category of Object.keys(NANXI_CATEGORIES)) {
    const entries = results.filter(row => row.categoryCode === category);
    const finished = entries.filter(row => row.status === "finished" && row.elapsedMs !== null)
      .sort((a, b) => a.elapsedMs - b.elapsedMs || String(a.bibNumber).localeCompare(String(b.bibNumber)));
    entries.forEach(row => { row.rank = null; row.categoryRank = null; row.gapMs = null; });
    let rank = 0;
    finished.forEach((row, i) => {
      if (i === 0 || row.elapsedMs !== finished[i - 1].elapsedMs) rank = i + 1;
      row.rank = rank; row.categoryRank = rank; row.gapMs = row.elapsedMs - finished[0].elapsedMs;
    });
  }
}
