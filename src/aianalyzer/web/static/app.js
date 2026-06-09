(() => {
  const $ = (s) => document.querySelector(s);
  const charts = {};
  const PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#79c0ff", "#56d364", "#e3b341", "#ff7b72", "#bc8cff"];

  // marked v12 dropped the built-in `sanitize` option. Install a renderer that
  // strips raw HTML so we can safely innerHTML the narrative markdown.
  if (window.marked && window.marked.use) {
    window.marked.use({ renderer: { html() { return ""; } } });
  }

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
    const eb = $(".hero-eyebrow");
    if (eb) eb.textContent = p.macro_label || "Your AI archetype";
    $("#hero-summary").textContent =
      `${conf}% confidence · ${p.totals.sessions} sessions · ` +
      `${p.totals.turns} turns · ${pretty(p.totals.hours)}h engaged with AI.`;

    const tagsEl = $("#hero-tags");
    tagsEl.innerHTML = "";
    for (const t of (p.tags || [])) {
      const s = document.createElement("span");
      s.className = "tag"; s.textContent = t;
      tagsEl.appendChild(s);
    }

    const axesEl = $("#hero-axes");
    axesEl.innerHTML = "";
    const AXIS_META = {
      planning: {
        label: "Planning",
        help: "How much you plan, spec or todo-ify work before coding. " +
          "Positive = you think before you type; negative = you ask AI to act first.",
      },
      control: {
        label: "Control",
        help: "How hands-on you stay while the AI works. Positive = you " +
          "drive the tools yourself; negative = you let the AI run.",
      },
    };
    for (const [k, meta] of Object.entries(AXIS_META)) {
      const v = p.axes?.[k];
      if (v == null) continue;
      const div = document.createElement("div");
      div.className = `axis ${v >= 0 ? "pos" : "neg"}`;
      div.title = meta.help;
      div.innerHTML = `
        <div class="name">${meta.label}</div>
        <div class="value">${v >= 0 ? "+" : ""}${v.toFixed(2)}</div>
        <div class="axis-sub">${v >= 0 ? "leaning positive" : "leaning negative"}</div>
      `;
      axesEl.appendChild(div);
    }

    renderQuadrantMap(p);
  }

  function renderQuadrantMap(p) {
    const dot = $("#quadrant-dot");
    if (!dot) return;
    // axes.planning and axes.control are both in [-1, +1]. Map planning -> Y
    // (top is positive) and control -> X (right is positive) so the four
    // corner labels match the canonical archetype grid:
    //   top-left  = Pilot      (planning +, control -)
    //   top-right = Architect  (planning +, control +)
    //   bot-left  = Vibe Coder (planning -, control -)
    //   bot-right = Tinkerer   (planning -, control +)
    const planning = p.axes?.planning ?? 0;
    const control = p.axes?.control ?? 0;
    const xPct = 50 + control * 50;           // -1 -> 0%, +1 -> 100%
    const yPct = 50 - planning * 50;          // +1 -> 0% (top), -1 -> 100%
    dot.style.left = xPct + "%";
    dot.style.top = yPct + "%";
    dot.title =
      `You: planning ${planning >= 0 ? "+" : ""}${planning.toFixed(2)}, ` +
      `control ${control >= 0 ? "+" : ""}${control.toFixed(2)}`;
  }

  function renderBehaviorRadar(p) {
    destroyChart("chart-behavior-radar");
    const radar = p.behavior_radar || [];
    if (!radar.length) return;
    const labels = radar.map(r => r.label);
    const data = radar.map(r => r.score);
    charts["chart-behavior-radar"] = new Chart($("#chart-behavior-radar"), {
      type: "radar",
      data: {
        labels,
        datasets: [{
          label: "You (0–1)",
          data,
          backgroundColor: "rgba(88,166,255,0.28)",
          borderColor: "#58a6ff",
          borderWidth: 2,
          pointBackgroundColor: "#58a6ff",
          pointRadius: 5,
          pointHoverRadius: 7,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (ctx) => ctx[0].label,
              label: (ctx) => {
                const row = radar[ctx.dataIndex];
                return [
                  `Score: ${(ctx.parsed.r * 100).toFixed(0)}%  (raw ${row.raw} / ${row.ceiling})`,
                ];
              },
              afterLabel: (ctx) => radar[ctx.dataIndex].help,
            },
          },
        },
        scales: {
          r: {
            angleLines: { color: "rgba(154,164,175,0.25)" },
            grid: { color: "rgba(154,164,175,0.2)" },
            pointLabels: { color: "#e6edf3", font: { size: 13, weight: "600" } },
            ticks: {
              backdropColor: "transparent",
              color: "#9aa4af",
              stepSize: 0.25,
              callback: (v) => `${Math.round(v * 100)}%`,
            },
            min: 0,
            max: 1,
          },
        },
      },
    });

    const legend = $("#behavior-radar-legend");
    legend.innerHTML = "";
    for (const row of radar) {
      const li = document.createElement("li");
      const pct = Math.round((row.score || 0) * 100);
      li.innerHTML = `
        <div class="legend-row">
          <span class="legend-dot"></span>
          <span class="legend-label">${row.label}</span>
          <span class="legend-score">${pct}%</span>
        </div>
        <div class="legend-help">${row.help}</div>
        <div class="legend-raw">raw value: <b>${row.raw}</b> &nbsp;·&nbsp; full scale at <b>${row.ceiling}</b></div>
      `;
      legend.appendChild(li);
    }
  }

  // KPI metadata: every card declares its label, unit, tooltip and how to
  // extract the value from the /api/profile payload. Add a new card by
  // pushing one entry — no HTML edit required.
  const KPI_CARDS = [
    {
      id: "sessions", label: "Sessions", unit: "sessions",
      get: p => p.totals.sessions,
      help: "Total number of AI coding sessions ever recorded across all collectors.",
    },
    {
      id: "turns", label: "Turns", unit: "user prompts",
      get: p => p.totals.turns,
      help: "Number of user prompts you have sent. One turn = one round-trip with the AI.",
    },
    {
      id: "hours", label: "Engaged time", unit: "hours",
      get: p => pretty(p.totals.hours),
      help: "Sum of time you were actively interacting. Gaps longer than 5 min count as a break, not engagement, so this excludes overnight idle.",
    },
    {
      id: "days", label: "Active days", unit: "days",
      get: p => p.totals.days_active,
      help: "Distinct calendar days on which you ran at least one AI session.",
    },
    {
      id: "streak", label: "Longest streak", unit: "consecutive days",
      get: p => p.totals.longest_streak_days,
      help: "Longest run of consecutive days with at least one session — your most disciplined stretch.",
    },
    {
      id: "avg-turns", label: "Avg turns / session", unit: "turns",
      get: p => pretty(p.averages.turns_per_session),
      help: "How long your average session is, in user prompts. High = deep work sessions; low = quick one-shot questions.",
    },
    {
      id: "avg-min", label: "Avg session length", unit: "minutes (engaged)",
      get: p => pretty(p.averages.session_minutes),
      help: "Average engaged minutes per session (gaps > 5 min skipped). The real coding time, not wall-clock.",
    },
    {
      id: "avg-prompt", label: "Avg prompt length", unit: "words",
      get: p => pretty(p.averages.prompt_words),
      help: "Mean word count of your prompts. High = you give context-rich instructions; low = terse commands.",
    },
    {
      id: "median-prompt", label: "Median prompt length", unit: "words",
      get: p => pretty(p.averages.median_prompt_words),
      help: "Median word count of your prompts. Less affected by occasional long specs than the average.",
    },
    {
      id: "p90-prompt", label: "P90 prompt length", unit: "words",
      get: p => pretty(p.averages.p90_prompt_words),
      help: "90th percentile prompt length — what your longest 10% of prompts look like.",
    },
    {
      id: "acceptance", label: "Acceptance rate", unit: "% of suggestions",
      get: p => (p.averages.acceptance_rate * 100).toFixed(0) + "%",
      help: "Share of AI tool calls / edits you accept (no abort, no rework). Low = you push back a lot; high = you trust the AI's output.",
    },
    {
      id: "firstseen", label: "First session", unit: "date",
      get: p => p.first_session_at ? new Date(p.first_session_at).toLocaleDateString() : "–",
      help: "Date of your earliest recorded AI session across all collectors.",
    },
  ];

  function renderKpis(p) {
    const grid = $("#kpi-grid");
    grid.innerHTML = "";
    for (const card of KPI_CARDS) {
      const div = document.createElement("div");
      div.className = "card kpi";
      div.title = card.help;
      div.innerHTML = `
        <h3>${card.label}</h3>
        <div class="big">${card.get(p)}</div>
        <div class="unit">${card.unit}</div>
        <div class="kpi-help">${card.help}</div>
      `;
      grid.appendChild(div);
    }
  }

  function renderLists(p) {
    const renderList = (selector, items, limit = 10) => {
      const ol = $(selector);
      ol.innerHTML = "";
      for (const [label, count] of items.slice(0, limit)) {
        const li = document.createElement("li");
        const labelSpan = document.createElement("span");
        labelSpan.className = "label";
        labelSpan.textContent = label;
        const countSpan = document.createElement("span");
        countSpan.className = "count";
        countSpan.textContent = count;
        li.append(labelSpan, countSpan);
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

  // Plain-English explanation for each signal name.
  const SIGNAL_HELP = {
    planning_language_ratio: "Share of your prompts that contain planning words like 'plan', 'design', 'spec', 'first'.",
    test_or_spec_mentions: "Average number of times each prompt mentions tests, specs or requirements.",
    todo_density: "Average number of explicit TODO items you create per session.",
    revision_depth: "How many follow-up turns you typically spend refining a single thread.",
    question_ratio: "Share of prompts containing a question mark or starting with a question word.",
    thinks_before_prompt_sec_avg: "Mean idle seconds between AI replies and your next prompt (capped at 5 min to ignore breaks).",
    tool_diversity: "Distinct tool types you invoke per session — bigger = you reach for many tools.",
    edited_files_per_turn: "Average number of files touched per user turn.",
    accept_and_go_rate: "Share of turns where you ship the AI's first response without revisions.",
    tool_error_rate: "Share of tool calls that returned an error.",
    parallel_tool_call_rate: "Share of turns issuing more than one tool call in parallel.",
    abort_rate: "Share of tool calls you aborted mid-flight.",
  };

  function renderBehavior(p) {
    const behavior = p.behavior || {};
    const renderSignalList = (selector, signals) => {
      const ul = $(selector);
      ul.innerHTML = "";
      for (const sig of signals || []) {
        const li = document.createElement("li");
        li.className = "signal";
        const max = sig.norm_max;
        let pct = 0;
        let scaleNote = "";
        if (typeof max === "number" && max > 0) {
          pct = Math.max(0, Math.min(1, (sig.value || 0) / max));
          scaleNote = ` / ${max}`;
        } else {
          pct = Math.max(0, Math.min(1, sig.value || 0));
        }
        const help = SIGNAL_HELP[sig.name] || "";
        li.innerHTML = `
          <div class="signal-row">
            <span class="signal-name" title="${help}">${sig.label}</span>
            <span class="signal-value">${(sig.value ?? 0).toFixed(2)}${scaleNote}</span>
          </div>
          <div class="signal-bar"><div class="signal-fill" style="width:${(pct * 100).toFixed(0)}%"></div></div>
          ${help ? `<div class="signal-help">${help}</div>` : ""}
        `;
        ul.appendChild(li);
      }
    };
    renderSignalList("#behavior-planning", behavior.planning);
    renderSignalList("#behavior-control", behavior.control);
    renderSignalList("#behavior-other", behavior.other);

    const effortUl = $("#behavior-effort");
    effortUl.innerHTML = "";
    const efforts = behavior.reasoning_effort_distribution || {};
    const entries = Object.entries(efforts).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
      const li = document.createElement("li");
      li.className = "signal muted";
      li.textContent = "no reasoning-effort events captured";
      effortUl.appendChild(li);
    } else {
      for (const [name, share] of entries) {
        const li = document.createElement("li");
        li.className = "signal";
        const pct = Math.max(0, Math.min(1, share));
        li.innerHTML = `
          <div class="signal-row">
            <span class="signal-name">${name}</span>
            <span class="signal-value">${(pct * 100).toFixed(0)}%</span>
          </div>
          <div class="signal-bar"><div class="signal-fill effort" style="width:${(pct * 100).toFixed(0)}%"></div></div>
        `;
        effortUl.appendChild(li);
      }
    }

    const modUl = $("#behavior-modifiers");
    modUl.innerHTML = "";
    for (const m of behavior.modifiers || []) {
      const li = document.createElement("li");
      li.className = `modifier ${m.met ? "met" : "miss"}`;
      const ratio = m.threshold > 0 ? (m.value || 0) / m.threshold : 0;
      const pct = Math.max(0, Math.min(1.15, ratio));
      const pctOfThreshold = Math.round(ratio * 100);
      li.innerHTML = `
        <div class="modifier-row">
          <span class="modifier-tag">${m.tag}</span>
          <span class="modifier-status">${m.met ? "applied" : `${pctOfThreshold}% of threshold`}</span>
        </div>
        <div class="modifier-bar"><div class="modifier-fill" style="width:${(pct * 100 / 1.15).toFixed(0)}%"></div></div>
        <div class="modifier-meta">${m.label}: ${(m.value ?? 0).toFixed(2)} vs ≥ ${m.threshold.toFixed(2)}</div>
      `;
      modUl.appendChild(li);
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
    const buttons = [$("#narrate-btn"), $("#narrate-btn-inline")].filter(Boolean);
    if (!buttons.length) return;
    const section = $("#narrative-section");

    const run = async () => {
      const status = $("#narrative-status");
      // Section is now always visible; just refresh in-place.
      section.classList.remove("hidden");
      section.classList.add("loading");
      status.textContent = "Asking copilot CLI to write your profile… (this can take 1–3 minutes)";
      $("#narrative-md").innerHTML = "";
      for (const b of buttons) b.disabled = true;
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
        for (const b of buttons) b.disabled = false;
        section.classList.remove("loading");
      }
    };

    for (const btn of buttons) btn.addEventListener("click", run);
  }

  async function load() {
    try {
      const profile = await fetchJson("/api/profile");
      renderHero(profile);
      renderBehaviorRadar(profile);
      renderKpis(profile);
      renderLists(profile);
      renderCharts(profile);
      renderBehavior(profile);
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
