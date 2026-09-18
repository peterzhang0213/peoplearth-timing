(function () {
  "use strict";
  const races = {19: "nanxi-race-20260919", 20: "nanxi-race-20260920"};
  const groups = {
    A: {label: "男子单人", type: "individual", size: 1, day: "19"},
    B: {label: "女子单人", type: "individual", size: 1, day: "19"},
    C: {label: "男子双人", type: "doubles", size: 2, day: "19"},
    D: {label: "女子双人", type: "doubles", size: 2, day: "19"},
    E: {label: "混合双人", type: "doubles", size: 2, day: "19"},
    F: {label: "双人接力", type: "doubles", size: 2, day: "20"},
    G: {label: "四人接力", type: "team", size: 4, day: "20"},
  };
  const codes = day => day === "20" ? ["F", "G"] : ["A", "B", "C", "D", "E"];
  const stationCountForDay = day => String(day) === "20" ? 7 : 8;
  const isRace = id => Object.values(races).includes(id);
  const dayForRace = id => id === races[20] ? "20" : "19";
  const normalizeBib = value => String(value || "").normalize("NFKC").trim().toUpperCase().replace(/[‐‑–—−]/g, "-").replace(/\s+/g, "");
  const categoryForRow = row => {
    const explicit = String(row?.categoryCode || row?.category_code || "").trim().toUpperCase();
    if (groups[explicit]) return explicit;
    const legacyBib = normalizeBib(row?.bibNumber || row?.bib_number);
    const inferred = legacyBib.match(/^([A-G])-\d{3}$/)?.[1];
    return inferred && groups[inferred] ? inferred : null;
  };
  const matchesBib = (row, value) => {
    const bib = normalizeBib(value);
    const memberBibs = row?.memberBibNumbers || row?.member_bib_numbers;
    return Boolean(bib) && (normalizeBib(row?.bibNumber || row?.bib_number) === bib
      || (Array.isArray(memberBibs) && memberBibs.some(item => normalizeBib(item) === bib)));
  };
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  const memberCaption = row => {
    const members = (row.memberNames || []).join(" / ");
    return row.entryType === "individual" || row.athleteName === members ? "" : members;
  };
  function duration(ms) {
    if (ms === null || ms === undefined || !Number.isFinite(Number(ms))) return "--:--:--";
    const total = Math.max(0, Math.floor(Number(ms) / 1000));
    return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60].map(n => String(n).padStart(2, "0")).join(":");
  }
  function mock(day) {
    const names = ["林峻", "顾妍", "周凯", "沈悦", "陈一", "张晨", "李然", "王悦", "许嘉", "刘畅"];
    const stationCount = stationCountForDay(day);
    const checkpoints = ["START", ...Array.from({length: stationCount - 1}, (_, i) => `STATION_${i + 2}_START`), "END"];
    const leaderboard = codes(day).flatMap(code => Array.from({length: 20}, (_, i) => {
      const group = groups[code];
      const bibNumber = `${code}-${String(i + 1).padStart(3, "0")}`;
      const members = Array.from({length: group.size}, (_, m) => names[(i + m) % names.length]);
      const femaleCount = day === "20" ? i % (group.size + 1) : ({A: 0, B: 1, C: 0, D: 2, E: 1}[code]);
      const deductionMs = day === "20" ? Math.min(femaleCount, 2) * 300000 : 0;
      const stationSplits = Object.fromEntries(Array.from({length: stationCount}, (_, j) => [`station${j + 1}Ms`, (230 + i * 14 + j * 17 % 90) * 1000]));
      const rawElapsedMs = Object.values(stationSplits).reduce((a, b) => a + b, 0);
      const penaltyMs = i % 7 === 3 ? 60000 : 0;
      const startTime = `2026-09-${day}T09:00:00+08:00`;
      let at = Date.parse(startTime);
      const checkpointTimes = {START: new Date(at).toISOString()};
      Object.values(stationSplits).forEach((ms, j) => { at += ms; checkpointTimes[checkpoints[j + 1]] = new Date(at).toISOString(); });
      const memberBibNumbers = Array.from({length: group.size}, (_, m) => `${code}-${String(i * group.size + m + 1).padStart(3, "0")}`);
      return {participantId: bibNumber, bibNumber, memberBibNumbers, categoryCode: code, categoryLabel: group.label,
        athleteName: group.size === 1 ? members[0] : ["North Pace", "追风小队", "Nanxi 力量", "一起向前"][i % 4] + ` ${i + 1}`,
        entryType: group.type, memberNames: members, memberCount: group.size, femaleCount,
        startTime, finishTime: new Date(at).toISOString(), rawElapsedMs, baseElapsedMs: rawElapsedMs,
        deductionMs, penaltyMs, adjustmentMs: penaltyMs, elapsedMs: rawElapsedMs + penaltyMs - deductionMs,
        status: "finished", current: "Finished", latestCheckpoint: "END", progressIndex: stationCount, timerRunning: false,
        checkpointTimes, stationSplits};
    }));
    for (const code of codes(day)) {
      const rows = leaderboard.filter(row => row.categoryCode === code).sort((a,b) => a.elapsedMs - b.elapsedMs);
      rows.forEach((row, i) => { row.rank = i + 1; row.categoryRank = i + 1; row.gapMs = row.elapsedMs - rows[0].elapsedMs; });
    }
    leaderboard.sort((a,b) => a.elapsedMs - b.elapsedMs);
    return {ok: true, raceId: races[day], race: {raceId: races[day], brand: "nanxi", name: `Nanxi · 9 月 ${day} 日`, stationCount, mode: "station_checkpoints", checkpointLayout: "station_boundaries", checkpoints, status: "active", categories: codes(day).map(code => ({code, label: groups[code].label}))}, generatedAt: new Date().toISOString(), leaderboard};
  }
  async function fetchResults(day, signal) {
    const response = await window.timingApiFetch(`/api/leaderboard?raceId=${races[day]}`, {signal, cache: "no-store"});
    if (!response.ok) throw new Error(`成绩服务返回 HTTP ${response.status}`);
    let payload;
    try { payload = await response.json(); }
    catch (error) { if (signal?.aborted) throw error; throw new Error("成绩服务返回的数据格式异常"); }
    if (!payload.ok || !Array.isArray(payload.leaderboard) || !payload.race) throw new Error("成绩服务返回的数据不完整");
    if (payload.raceId !== races[day]) throw new Error("返回的赛事与所选日期不一致");
    return payload;
  }
  const resultError = error => error?.name === "AbortError" ? "成绩请求超时" : error instanceof TypeError ? "无法连接成绩服务，请检查网络" : error?.message || "成绩服务暂时不可用";
  window.Nanxi = {races, groups, codes, stationCountForDay, isRace, dayForRace, normalizeBib, categoryForRow, matchesBib, memberCaption, escape, duration, mock, fetchResults, resultError};
})();
