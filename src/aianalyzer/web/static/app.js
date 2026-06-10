(() => {
  const $ = (s) => document.querySelector(s);
  const charts = {};
  const PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#79c0ff", "#56d364", "#e3b341", "#ff7b72", "#bc8cff"];

  // marked v12 dropped the built-in `sanitize` option. Install a renderer that
  // strips raw HTML so we can safely innerHTML the narrative markdown.
  if (window.marked && window.marked.use) {
    window.marked.use({ renderer: { html() { return ""; } } });
  }

  function toast(msg, kind = "error", durationMs = 5000) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    // Preserve newlines for multi-line empty-state messages.
    el.style.whiteSpace = "pre-line";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), durationMs);
  }

  const CLIENT_LABELS = {
    "copilot-cli": "GitHub Copilot CLI",
    "vscode-copilot": "VS Code Copilot Chat",
    "claude-code": "Claude Code",
    "codex-cli": "Codex CLI",
  };

  function humanizeClient(c) {
    return CLIENT_LABELS[c] || c;
  }

  function formatBreakdown(byClient) {
    if (!byClient || typeof byClient !== "object") return "";
    const parts = Object.entries(byClient)
      .map(([c, n]) => `${n} ${humanizeClient(c)}`);
    return parts.join(", ");
  }

  function renderEmptyState(result) {
    // Inject a one-time banner in the hero summary so the empty state is
    // visible after the toast disappears. Idempotent.
    const summary = $("#hero-summary");
    if (!summary) return;
    let banner = document.getElementById("empty-state-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "empty-state-banner";
      banner.className = "empty-state-banner";
      summary.parentNode.insertBefore(banner, summary.nextSibling);
    }
    const supported = (result.supported_clients || []).map(humanizeClient);
    banner.innerHTML = `
      <strong>No sessions found yet.</strong>
      AIAnalyzer looked for AI coding sessions in these locations:
      <ul>
        <li><code>~/.copilot/session-state/</code> &mdash; GitHub Copilot CLI</li>
        <li><code>%APPDATA%/Code/User/workspaceStorage/&lt;workspace&gt;/chatSessions/</code> &mdash; VS Code Copilot Chat</li>
      </ul>
      <p><strong>Supported clients:</strong> ${supported.join(", ") || "(none configured)"}.</p>
      <p><strong>Not yet supported</strong> (no persistent on-disk log we can read):
      Visual Studio IDE Copilot Chat, Claude Code, Codex CLI.</p>
      <p>If you use one of the supported clients but still see zero, make sure you've
      had at least one chat session there since installing the tool, then click
      <em>Scan sessions</em> again.</p>
    `;
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

  // GitHub-style 7-row calendar heatmap. Renders a 7×N grid of cells where
  // each cell is one day; intensity is bucketed 0..4 relative to the max.
  function renderActivityHeatmap(activity) {
    const root = document.getElementById("activity-heatmap");
    if (!root) return;
    root.innerHTML = "";
    if (!activity || activity.length === 0) return;

    // activity is [[dateStr, count], ...] ordered oldest -> newest.
    const cells = activity.map(([dateStr, count]) => {
      const d = new Date(dateStr + "T00:00:00");
      // Monday=0..Sunday=6 so the grid starts with Monday on row 0.
      const weekday = (d.getDay() + 6) % 7;
      return { date: dateStr, count, weekday };
    });

    // Insert leading blanks so column 0 begins on Monday.
    const lead = cells[0] ? cells[0].weekday : 0;
    const filled = [...Array(lead).fill(null), ...cells];

    // Pad trailing blanks so the grid ends on a full column.
    while (filled.length % 7 !== 0) filled.push(null);

    const max = Math.max(...cells.map((c) => c.count), 0);
    const bucket = (n) => {
      if (!n || n <= 0) return 0;
      if (max <= 1) return 4;
      return Math.min(4, Math.max(1, Math.ceil((n / max) * 4)));
    };

    const cols = filled.length / 7;
    root.style.setProperty("--cols", cols);

    for (let col = 0; col < cols; col++) {
      for (let row = 0; row < 7; row++) {
        const c = filled[col * 7 + row];
        const cell = document.createElement("div");
        cell.className = "heatmap-cell";
        if (!c) {
          cell.classList.add("blank");
        } else {
          cell.dataset.level = String(bucket(c.count));
          cell.title = `${c.date}: ${c.count} session${c.count === 1 ? "" : "s"}`;
        }
        root.appendChild(cell);
      }
    }
  }

  // Comments on signal coverage per client. Surfaces tool-coverage caveats
  // when VS Code data dominates so users know why some axes may look low.
  const CLIENT_COVERAGE_NOTES = {
    "copilot-cli":
      "Full signal coverage — every prompt, tool call, file edit, terminal " +
      "run, todo and error is recorded.",
    "vscode-copilot":
      "Strong coverage — tool invocations, file edits and terminal runs are " +
      "recorded. Per-tool-call timestamps and todos are not captured, so " +
      "'Think time' and 'TODO-driver' may read lower than for Copilot CLI.",
  };

  function renderDataSources(p) {
    const section = document.getElementById("data-sources");
    if (!section) return;
    const list = document.getElementById("data-sources-list");
    const note = document.getElementById("data-sources-note");
    const byClient = (p && p.by_client) || {};
    const entries = Object.entries(byClient);
    if (!entries.length) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    // Stable ordering: most sessions first.
    entries.sort((a, b) => (b[1].sessions || 0) - (a[1].sessions || 0));
    const totals = entries.reduce(
      (acc, [, v]) => {
        acc.sessions += v.sessions || 0;
        acc.turns += v.turns || 0;
        acc.tool_calls += v.tool_calls || 0;
        return acc;
      },
      { sessions: 0, turns: 0, tool_calls: 0 }
    );
    list.innerHTML = "";
    for (const [client, v] of entries) {
      const sessPct = totals.sessions ? (v.sessions / totals.sessions) * 100 : 0;
      const turnPct = totals.turns ? (v.turns / totals.turns) * 100 : 0;
      const toolPct = totals.tool_calls ? (v.tool_calls / totals.tool_calls) * 100 : 0;
      const li = document.createElement("li");
      li.className = "source-row";
      li.innerHTML = `
        <div class="source-head">
          <span class="source-name">${humanizeClient(client)}</span>
          <span class="source-share">${Math.round(sessPct)}% of sessions</span>
        </div>
        <div class="source-bar"><span style="width:${sessPct.toFixed(1)}%"></span></div>
        <div class="source-stats">
          <span><b>${v.sessions.toLocaleString()}</b> sessions</span>
          <span><b>${v.turns.toLocaleString()}</b> turns
            <span class="muted">(${turnPct.toFixed(1)}% of all turns)</span></span>
          <span><b>${Math.round(v.tool_calls).toLocaleString()}</b> tool calls
            <span class="muted">(${toolPct.toFixed(1)}% of all tool signal)</span></span>
          <span><b>${(v.hours || 0).toFixed(1)}</b> engaged hours</span>
        </div>
        <p class="source-note muted">${CLIENT_COVERAGE_NOTES[client] || "Coverage details unavailable for this client."}</p>
      `;
      list.appendChild(li);
    }
    // Highlight tool-coverage skew if any client dominates with > 60% of tool calls.
    const dominant = entries.find(
      ([, v]) => totals.tool_calls && v.tool_calls / totals.tool_calls > 0.6
    );
    if (dominant) {
      const [client, v] = dominant;
      const pct = Math.round((v.tool_calls / totals.tool_calls) * 100);
      note.textContent =
        `Heads-up: ${pct}% of your tool-call signal comes from ${humanizeClient(client)}. ` +
        `Behaviour signals that depend on tool calls (Hands-on, Multi-tasker, ` +
        `tool error rate) are weighted toward how you use that tool.`;
    } else {
      note.textContent =
        "Your tool-call signal is reasonably balanced across clients, so " +
        "behaviour metrics reflect your overall AI usage style.";
    }
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
          "direct with specific prompts, paste code, name files; " +
          "negative = you give short prompts and let the AI run.",
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
    renderPersonality(p.personality);
  }

  function renderPersonality(personality) {
    const card = document.getElementById("personality-card");
    if (!card) return;
    if (!personality || (!personality.nickname && !(personality.badges || []).length && !(personality.did_you_know || []).length)) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    card.querySelector(".personality-nickname").textContent = personality.nickname || "";
    card.querySelector(".personality-tagline").textContent = personality.tagline || "";

    const badgesEl = card.querySelector(".personality-badges");
    badgesEl.innerHTML = "";
    for (const b of personality.badges || []) {
      const chip = document.createElement("span");
      chip.className = "badge";
      chip.title = b.detail || "";
      const icon = document.createElement("span");
      icon.className = "badge-icon"; icon.textContent = b.icon || "";
      const title = document.createElement("span");
      title.className = "badge-title"; title.textContent = b.title || "";
      chip.appendChild(icon); chip.appendChild(title);
      badgesEl.appendChild(chip);
    }

    const insightsWrap = card.querySelector(".personality-insights");
    const dykList = card.querySelector(".did-you-know-list");
    dykList.innerHTML = "";
    const items = personality.did_you_know || [];
    insightsWrap.style.display = items.length ? "" : "none";
    for (const i of items) {
      const li = document.createElement("li");
      const icon = document.createElement("span");
      icon.className = "dyk-icon"; icon.textContent = i.icon || "";
      const text = document.createElement("span");
      const strong = document.createElement("b");
      strong.textContent = i.title ? `${i.title}.` : "";
      text.appendChild(strong);
      text.appendChild(document.createTextNode(" " + (i.detail || "")));
      li.appendChild(icon); li.appendChild(text);
      dykList.appendChild(li);
    }
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
    renderActivityHeatmap(activity);

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
    prompt_specificity_avg: "Average detail in your prompts (word count / 200, capped). High = you write long, specific instructions.",
    code_block_density: "Share of prompts that paste a code block. High = you bring code to the conversation.",
    file_reference_rate: "Share of prompts that cite a file path, :line, function(), or @file. High = you direct the AI to specific places.",
    ai_agency_rate: "Average AI tool calls per user message. High = AI is doing more autonomous work per prompt (hands-off).",
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
          const r = final.result || {};
          const total = r.discovered ?? 0;
          const fresh = r.new ?? 0;
          if (total === 0) {
            // Build a clear empty-state message so users don't see a silent "0".
            const supported = (r.supported_clients || []).map(humanizeClient).join(", ");
            const longMsg =
              `Scan finished. We looked for sessions from: ${supported || "supported clients"}, ` +
              `but found 0 on disk.\n\n` +
              `Locations checked:\n` +
              `  • GitHub Copilot CLI: ~/.copilot/session-state/\n` +
              `  • VS Code Copilot Chat: AppData/Roaming/Code/User/workspaceStorage/<workspace>/chatSessions/\n\n` +
              `Not supported (no persistent on-disk log): Visual Studio IDE Copilot Chat, Claude Code, Codex CLI.`;
            toast(longMsg, "warn", 12000);
            renderEmptyState(r);
          } else {
            const breakdown = formatBreakdown(r.by_client);
            toast(`Scanned ${total} session${total === 1 ? "" : "s"} (new ${fresh}) — ${breakdown}`, "info");
          }
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

  async function wireExportPdf() {
    const btn = $("#export-pdf-btn");
    if (!btn) return;
    if (typeof window.html2pdf !== "function") {
      btn.disabled = true;
      btn.title = "PDF export library failed to load.";
      return;
    }

    // Capture-time layout overrides. We mutate inline styles directly
    // (instead of relying on a body class) because html2canvas clones
    // the document into a hidden iframe and dynamic class-toggled CSS
    // is sometimes missed by the cascade in that clone. Each entry
    // is restored after capture.
    const PDF_WIDTH = 780;
    function pinLayout() {
      const restore = [];
      const setStyle = (el, prop, value) => {
        if (!el) return;
        restore.push({ el, prop, prev: el.style[prop] });
        el.style[prop] = value;
      };
      const main = document.getElementById("app");
      setStyle(main, "width", PDF_WIDTH + "px");
      setStyle(main, "maxWidth", PDF_WIDTH + "px");
      setStyle(main, "padding", "14px");
      // Pin main to the viewport's left edge so html2canvas captures at (0,0)
      // rather than the centered offset (which leaves content clipped).
      setStyle(main, "margin", "0");
      setStyle(main, "marginLeft", "0");
      document.querySelectorAll(".hero-card, .shape-body, .axes-explainer-body, .charts, .tables, .behavior-cols")
        .forEach((el) => setStyle(el, "gridTemplateColumns", "1fr"));
      document.querySelectorAll(".chart-wide")
        .forEach((el) => setStyle(el, "gridColumn", "auto"));
      document.querySelectorAll(".charts canvas")
        .forEach((el) => setStyle(el, "maxHeight", "240px"));
      // Force the <details> blocks open so axes-explainer paragraphs render
      const opened = [];
      document.querySelectorAll("details").forEach((el) => {
        if (!el.open) { opened.push(el); el.open = true; }
      });
      // Hide the topbar + inline narrate button
      setStyle(document.querySelector(".topbar"), "display", "none");
      setStyle(document.getElementById("narrate-btn-inline"), "display", "none");
      // CSS Grid won't shrink children below their min-content. Chart cards
      // sit inside .charts with intrinsically wide canvases from a previous
      // render, so columns refuse to shrink. Force min-width: 0 + clear
      // canvas size so grid cells collapse to the pinned 780-wide row, THEN
      // resize() the chart below.
      document.querySelectorAll(".charts > .card, .tables > .card").forEach((el) => {
        setStyle(el, "minWidth", "0");
      });
      document.querySelectorAll(".charts canvas, .hero-card canvas").forEach((cnv) => {
        cnv.style.width = "";
        cnv.style.height = "";
        cnv.removeAttribute("width");
        cnv.removeAttribute("height");
      });
      // Force a synchronous layout reflow so .card widths re-compute.
      void document.body.offsetHeight;
      return { restore, opened };
    }
    function unpinLayout({ restore, opened }) {
      for (const { el, prop, prev } of restore) {
        el.style[prop] = prev || "";
      }
      for (const el of opened) el.open = false;
    }

    btn.addEventListener("click", async () => {
      const main = document.getElementById("app");
      if (!main) return;
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Preparing PDF…";

      const pinned = pinLayout();

      const stampNode = document.createElement("div");
      stampNode.className = "pdf-header";
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const ymd = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
      const hms = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
      stampNode.textContent = `AIAnalyzer report · generated ${ymd} ${hms}`;
      main.insertBefore(stampNode, main.firstChild);

      // Two RAFs so Chart.js resize observers can react to the new column width.
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      // Force every Chart.js instance to re-render at the pinned container width.
      // Chart.js's responsive ResizeObserver fires asynchronously and sometimes
      // misses our synchronous style change, so we call resize() with explicit
      // dimensions read from the actual parent .card box after pin.
      try {
        Object.values(charts).forEach((c) => {
          if (!c || typeof c.resize !== "function") return;
          const cnv = c.canvas;
          const parent = cnv && cnv.parentNode;
          if (parent) {
            cnv.style.width = "";
            cnv.style.height = "";
            cnv.removeAttribute("width");
            cnv.removeAttribute("height");
            const targetW = parent.clientWidth;
            const targetH = Math.min(240, Math.round(targetW * 0.45));
            c.resize(targetW, targetH);
          } else {
            c.resize();
          }
        });
      } catch (_) {}
      // And give Chart.js a moment to actually redraw after resize.
      await new Promise((r) => setTimeout(r, 250));

      try {
        btn.textContent = "Rendering PDF…";
        const mainRect = main.getBoundingClientRect();
        await window.html2pdf()
          .set({
            margin: [12, 10, 14, 10],
            filename: `aianalyzer-report-${ymd}.pdf`,
            image: { type: "jpeg", quality: 0.95 },
            html2canvas: {
              scale: 2,
              useCORS: true,
              backgroundColor: "#0e1117",
              width: PDF_WIDTH,
              windowWidth: PDF_WIDTH,
              // Force capture from the element's actual left/top so the canvas
              // covers main itself (not a shifted slice of the viewport).
              x: mainRect.left + window.scrollX,
              y: mainRect.top + window.scrollY,
              scrollX: 0,
              scrollY: 0,
            },
            jsPDF: { unit: "pt", format: "a4", orientation: "portrait" },
            pagebreak: { mode: ["css", "legacy"] },
          })
          .from(main)
          .save();
        toast("PDF downloaded.", "info", 3500);
      } catch (e) {
        toast(`PDF export failed: ${e.message || e}`);
      } finally {
        stampNode.remove();
        unpinLayout(pinned);
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  }

  async function load() {
    try {
      const profile = await fetchJson("/api/profile");
      renderHero(profile);
      renderDataSources(profile);
      renderBehaviorRadar(profile);
      renderKpis(profile);
      renderLists(profile);
      renderCharts(profile);
      renderBehavior(profile);
      // First-launch empty state: show banner when cache is empty.
      const banner = document.getElementById("empty-state-banner");
      if (profile && profile.totals && (profile.totals.sessions || 0) === 0) {
        renderEmptyState({ supported_clients: ["copilot-cli", "vscode-copilot"] });
      } else if (banner) {
        banner.remove();
      }
    } catch (e) {
      toast(`Failed to load profile: ${e.message}`);
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    wireScan();
    wireNarrative();
    wireExportPdf();
    await load();
  });
})();
