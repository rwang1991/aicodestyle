(() => {
  const $ = (s) => document.querySelector(s);
  const charts = {};
  const PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#79c0ff", "#56d364", "#e3b341", "#ff7b72", "#bc8cff"];

  function toast(msg, kind = "error") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  async function fetchJson(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`${url} -> ${r.status}`);
    return r.json();
  }

  function pretty(n, d = 1) {
    if (n == null || isNaN(n)) return "–";
    return Number(n).toFixed(d);
  }

  function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  }

  function renderHero(p) {
    const primary = (p.primary_archetype || "unknown").replace(/^./, c => c.toUpperCase());
    $("#hero-archetype").textContent = `You are an ${primary}`;
    const conf = Math.round((p.confidence || 0) * 100);
    $("#hero-summary").textContent =
      `${p.macro_label || primary} · ${conf}% confidence · ${p.totals.sessions} sessions, ` +
      `${p.totals.turns} turns, ${pretty(p.totals.hours)}h tracked.`;

    const tagsEl = $("#hero-tags");
    tagsEl.innerHTML = "";
    for (const t of (p.tags || [])) {
      const s = document.createElement("span");
      s.className = "tag"; s.textContent = t;
      tagsEl.appendChild(s);
    }

    const axesEl = $("#hero-axes");
    axesEl.innerHTML = "";
    const AXIS_LABEL = { planning: "Planning", control: "Control" };
    for (const [k, label] of Object.entries(AXIS_LABEL)) {
      const v = p.axes?.[k];
      if (v == null) continue;
      const div = document.createElement("div");
      div.className = `axis ${v >= 0 ? "pos" : "neg"}`;
      div.innerHTML = `<div class="name">${label}</div><div class="value">${v >= 0 ? "+" : ""}${v.toFixed(2)}</div>`;
      axesEl.appendChild(div);
    }
  }

  function renderKpis(p) {
    $("#kpi-sessions .big").textContent = p.totals.sessions;
    $("#kpi-turns .big").textContent = p.totals.turns;
    $("#kpi-hours .big").textContent = pretty(p.totals.hours);
    $("#kpi-days .big").textContent = p.totals.days_active;
    $("#kpi-streak .big").textContent = p.totals.longest_streak_days;
    $("#kpi-avg-turns .big").textContent = pretty(p.averages.turns_per_session);
    $("#kpi-avg-min .big").textContent = pretty(p.averages.session_minutes);
    $("#kpi-avg-prompt .big").textContent = pretty(p.averages.prompt_words);
    $("#kpi-median-prompt .big").textContent = pretty(p.averages.median_prompt_words);
    $("#kpi-p90-prompt .big").textContent = pretty(p.averages.p90_prompt_words);
    $("#kpi-acceptance .big").textContent = (p.averages.acceptance_rate * 100).toFixed(0) + "%";
    const firstSeen = p.first_session_at ? new Date(p.first_session_at).toLocaleDateString() : "–";
    $("#kpi-firstseen .big").textContent = firstSeen;
  }

  function renderLists(p) {
    const renderList = (selector, items, limit = 10) => {
      const ol = $(selector);
      ol.innerHTML = "";
      for (const [label, count] of items.slice(0, limit)) {
        const li = document.createElement("li");
        li.innerHTML = `<span class="label">${label}</span><span class="count">${count}</span>`;
        ol.appendChild(li);
      }
    };
    renderList("#top-projects", p.top_projects || [], 10);
    renderList("#top-models", p.top_models || [], 10);
    renderList("#top-exts", p.top_file_extensions || [], 10);
  }

  function renderCharts(p) {
    destroyChart("chart-session-types");
    destroyChart("chart-top-tools");
    destroyChart("chart-activity");
    destroyChart("chart-hour");
    destroyChart("chart-weekday");

    const stypes = p.session_type_counts || {};
    if (Object.keys(stypes).length > 0) {
      const labels = Object.keys(stypes);
      const data = Object.values(stypes);
      charts["chart-session-types"] = new Chart($("#chart-session-types"), {
        type: "doughnut",
        data: {
          labels,
          datasets: [{ data, backgroundColor: PALETTE }]
        },
        options: { responsive: true, maintainAspectRatio: false }
      });
    }

    const topTools = (p.top_tools || []).slice(0, 10);
    if (topTools.length > 0) {
      const labels = topTools.map(([name]) => name);
      const data = topTools.map(([, count]) => count);
      charts["chart-top-tools"] = new Chart($("#chart-top-tools"), {
        type: "bar",
        data: {
          labels,
          datasets: [{ data, backgroundColor: PALETTE[0] }]
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      });
    }

    const activity = p.activity_per_day_last_90 || [];
    if (activity.length > 0) {
      const labels = activity.map(([date]) => date);
      const data = activity.map(([, count]) => count);
      charts["chart-activity"] = new Chart($("#chart-activity"), {
        type: "line",
        data: {
          labels,
          datasets: [{
            data,
            borderColor: PALETTE[0],
            backgroundColor: PALETTE[0] + "33",
            fill: true,
            tension: 0.3
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { display: false } }
        }
      });
    }

    const hourHist = p.hour_histogram || [];
    if (hourHist.length === 24) {
      const labels = Array.from({ length: 24 }, (_, i) => String(i));
      charts["chart-hour"] = new Chart($("#chart-hour"), {
        type: "bar",
        data: {
          labels,
          datasets: [{ data: hourHist, backgroundColor: PALETTE[1] }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      });
    }

    const wdayHist = p.weekday_histogram || [];
    if (wdayHist.length === 7) {
      const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      charts["chart-weekday"] = new Chart($("#chart-weekday"), {
        type: "bar",
        data: {
          labels,
          datasets: [{ data: wdayHist, backgroundColor: PALETTE[2] }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      });
    }
  }

  async function pollJob(jobId, onUpdate) {
    for (;;) {
      const j = await fetchJson(`/api/jobs/${jobId}`);
      onUpdate(j);
      if (j.status === "done" || j.status === "failed") return j;
      await new Promise(r => setTimeout(r, 500));
    }
  }

  async function wireScan() {
    const btn = $("#scan-btn");
    btn.addEventListener("click", async () => {
      btn.disabled = true; btn.textContent = "Scanning…";
      try {
        const { job_id } = await fetchJson("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        const final = await pollJob(job_id, (j) => {
          btn.textContent = `Scanning… ${Math.round((j.progress || 0) * 100)}%`;
        });
        if (final.status === "failed") {
          toast(`Scan failed: ${final.error}`);
        } else {
          toast(`Scanned ${final.result.discovered} (new ${final.result.new})`, "info");
          await load();
        }
      } catch (e) {
        toast(`Scan request failed: ${e.message}`);
      } finally {
        btn.disabled = false; btn.textContent = "Scan sessions";
      }
    });
  }

  async function wireNarrative() {
    const btn = $("#narrate-btn");
    btn.addEventListener("click", async () => {
      const section = $("#narrative-section");
      const status = $("#narrative-status");
      section.classList.remove("hidden");
      status.textContent = "Asking copilot CLI to write your profile… (this can take 1–3 minutes)";
      $("#narrative-md").innerHTML = "";
      btn.disabled = true;
      try {
        const { job_id } = await fetchJson("/api/narrative/start", { method: "POST" });
        const final = await pollJob(job_id, (j) => {
          status.textContent = `Generating narrative (${j.status})…`;
        });
        if (final.status === "failed") {
          status.textContent = `Narrative failed: ${final.error}`;
        } else {
          status.textContent = "";
          $("#narrative-md").innerHTML = window.marked.parse(final.result.markdown);
        }
      } catch (e) {
        status.textContent = `Narrative request failed: ${e.message}`;
      } finally {
        btn.disabled = false;
      }
    });
  }

  async function load() {
    try {
      const profile = await fetchJson("/api/profile");
      renderHero(profile);
      renderKpis(profile);
      renderLists(profile);
      renderCharts(profile);
    } catch (e) {
      toast(`Failed to load profile: ${e.message}`);
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    wireScan();
    wireNarrative();
    await load();
  });
})();
