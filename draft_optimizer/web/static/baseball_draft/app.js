(() => {
  const root = document.getElementById("draft-app");
  if (!root) {
    return;
  }

  const endpoints = {
    upload: root.dataset.uploadUrl,
    snapshot: root.dataset.snapshotUrl,
    action: root.dataset.actionUrl,
  };
  const storageKey = root.dataset.storageKey;
  const defaultSettings = JSON.parse(root.dataset.defaultSettings || "{}");

  const elements = {
    actionPanel: document.getElementById("action-panel"),
    applySettingsButton: document.getElementById("apply-settings"),
    csvFileInput: document.getElementById("csv-file"),
    draftShell: document.getElementById("draft-shell"),
    emptyState: document.getElementById("empty-state"),
    externalForm: document.getElementById("external-form"),
    externalLabel: document.getElementById("external-label"),
    historyList: document.getElementById("history-list"),
    myPicksCount: document.getElementById("my-picks-count"),
    myPicksList: document.getElementById("my-picks-list"),
    needsSummary: document.getElementById("needs-summary"),
    recommendationsBody: document.getElementById("recommendations-body"),
    resetToolButton: document.getElementById("reset-tool"),
    restartDraftButton: document.getElementById("restart-draft"),
    runCount: document.getElementById("run-count"),
    runForm: document.getElementById("run-form"),
    searchCount: document.getElementById("search-count"),
    searchQuery: document.getElementById("search-query"),
    searchResultsBody: document.getElementById("search-results-body"),
    settingsForm: document.getElementById("settings-form"),
    sourceLabel: document.getElementById("source-label"),
    statusBanner: document.getElementById("status-banner"),
    summaryCards: document.getElementById("summary-cards"),
    teamsInput: document.getElementById("teams"),
    undoCount: document.getElementById("undo-count"),
    undoForm: document.getElementById("undo-form"),
    uploadForm: document.getElementById("upload-form"),
  };

  let state = loadStoredState();
  let snapshot = null;
  let statusTimer = null;

  function defaultState() {
    return {
      players: [],
      history: [],
      settings: { ...defaultSettings },
      sourceName: "",
    };
  }

  function loadStoredState() {
    const fallback = defaultState();
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) {
        return fallback;
      }
      const parsed = JSON.parse(raw);
      return {
        players: Array.isArray(parsed.players) ? parsed.players : [],
        history: Array.isArray(parsed.history) ? parsed.history : [],
        settings: { ...defaultSettings, ...(parsed.settings || {}) },
        sourceName: typeof parsed.sourceName === "string" ? parsed.sourceName : "",
      };
    } catch (_error) {
      return fallback;
    }
  }

  function saveState() {
    window.localStorage.setItem(storageKey, JSON.stringify(state));
  }

  function resetState() {
    state = defaultState();
    snapshot = null;
    window.localStorage.removeItem(storageKey);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatNumber(value, digits = 1) {
    return Number(value).toFixed(digits);
  }

  function formatPositions(positions) {
    return Array.isArray(positions) ? positions.join("/") : "";
  }

  function showStatus(message, kind = "info") {
    if (statusTimer) {
      window.clearTimeout(statusTimer);
    }
    elements.statusBanner.hidden = !message;
    elements.statusBanner.dataset.kind = kind;
    elements.statusBanner.textContent = message || "";
    if (message) {
      statusTimer = window.setTimeout(() => {
        elements.statusBanner.hidden = true;
      }, 4500);
    }
  }

  function syncDraftSlotBounds() {
    const teams = Math.max(2, Number(elements.teamsInput.value || defaultSettings.teams));
    const draftSlotInput = elements.settingsForm.elements.namedItem("draft_slot");
    draftSlotInput.max = String(teams);
    if (Number(draftSlotInput.value || "0") > teams) {
      draftSlotInput.value = String(teams);
    }
  }

  function applySettingsToForm(settings) {
    elements.settingsForm.elements.namedItem("teams").value = settings.teams;
    elements.settingsForm.elements.namedItem("draft_slot").value = settings.draft_slot;
    elements.settingsForm.elements.namedItem("top_n").value = settings.top_n;
    elements.settingsForm.elements.namedItem("disable_mc").checked = Boolean(settings.disable_mc);
    elements.settingsForm.elements.namedItem("mc_trials").value = settings.mc_trials;
    elements.settingsForm.elements.namedItem("mc_seed").value = settings.mc_seed;
    elements.settingsForm.elements.namedItem("mc_candidate_pool").value = settings.mc_candidate_pool;
    elements.settingsForm.elements.namedItem("mc_temperature").value = settings.mc_temperature;
    elements.settingsForm.elements.namedItem("opponent_need_bonus").value = settings.opponent_need_bonus;
    elements.settingsForm.elements.namedItem("opponent_scarcity_weight").value =
      settings.opponent_scarcity_weight;
    syncDraftSlotBounds();
  }

  function readSettingsFromForm() {
    return {
      teams: Number(elements.settingsForm.elements.namedItem("teams").value),
      draft_slot: Number(elements.settingsForm.elements.namedItem("draft_slot").value),
      top_n: Number(elements.settingsForm.elements.namedItem("top_n").value),
      disable_mc: elements.settingsForm.elements.namedItem("disable_mc").checked,
      mc_trials: Number(elements.settingsForm.elements.namedItem("mc_trials").value),
      mc_seed: Number(elements.settingsForm.elements.namedItem("mc_seed").value),
      mc_candidate_pool: Number(elements.settingsForm.elements.namedItem("mc_candidate_pool").value),
      mc_temperature: Number(elements.settingsForm.elements.namedItem("mc_temperature").value),
      opponent_need_bonus: Number(elements.settingsForm.elements.namedItem("opponent_need_bonus").value),
      opponent_scarcity_weight: Number(
        elements.settingsForm.elements.namedItem("opponent_scarcity_weight").value,
      ),
    };
  }

  async function requestJson(url, options) {
    const response = await window.fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Request failed.");
    }
    return payload;
  }

  async function refreshSnapshot() {
    if (!state.players.length) {
      snapshot = null;
      render();
      return;
    }
    const payload = await requestJson(endpoints.snapshot, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        players: state.players,
        settings: state.settings,
        history: state.history,
      }),
    });
    snapshot = payload;
    state.settings = payload.settings;
    state.history = payload.history;
    saveState();
    render();
  }

  async function applyAction(action) {
    if (!state.players.length) {
      showStatus("Upload a CSV before recording picks.", "error");
      return;
    }
    const payload = await requestJson(endpoints.action, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        players: state.players,
        settings: state.settings,
        history: state.history,
        action,
      }),
    });
    snapshot = payload.snapshot;
    state.settings = payload.snapshot.settings;
    state.history = payload.snapshot.history;
    saveState();
    render();
    showStatus(payload.result.message, "success");
  }

  function currentDraftedIds() {
    return new Set(snapshot && Array.isArray(snapshot.drafted_ids) ? snapshot.drafted_ids : []);
  }

  function availablePlayers() {
    const draftedIds = currentDraftedIds();
    return state.players
      .filter((player) => !draftedIds.has(player.player_id))
      .sort((left, right) => right.projected_points - left.projected_points);
  }

  function actionButtons(playerId) {
    return `
      <div class="table-actions">
        <button class="mini-button" data-action-type="mine" data-player-id="${escapeHtml(playerId)}" type="button">Mine</button>
        <button class="mini-button muted" data-action-type="other" data-player-id="${escapeHtml(playerId)}" type="button">Other</button>
      </div>
    `;
  }

  function renderSummary() {
    if (!snapshot) {
      elements.summaryCards.innerHTML = "";
      elements.needsSummary.textContent = "";
      return;
    }

    const summary = snapshot.summary;
    const needs = summary.active_needs || {};
    const needsText = Object.keys(needs).length
      ? `Needs: ${Object.entries(needs)
          .map(([slot, count]) => `${slot}:${count}`)
          .join("  ")}`
      : "Active lineup can already be filled with your current roster.";
    const turnText = summary.my_turn
      ? "Your turn now."
      : `Picks until your next turn: ${summary.picks_until_my_next_turn_after_current}.`;
    elements.needsSummary.textContent = `${turnText} ${needsText}`;

    const cards = [
      ["Overall Pick", summary.current_pick_number],
      ["My Picks", `${summary.my_picks_count}/${summary.total_roster_size}`],
      ["Available", summary.available_count],
      ["Next Turn Gap", summary.picks_until_my_next_turn_after_current],
    ];
    elements.summaryCards.innerHTML = cards
      .map(
        ([label, value]) => `
          <article class="summary-card">
            <p>${escapeHtml(label)}</p>
            <strong>${escapeHtml(value)}</strong>
          </article>
        `,
      )
      .join("");
  }

  function renderRecommendations() {
    if (!snapshot) {
      elements.recommendationsBody.innerHTML = "";
      return;
    }
    const recommendations = Array.isArray(snapshot.recommendations) ? snapshot.recommendations : [];
    if (!recommendations.length) {
      elements.recommendationsBody.innerHTML = `
        <tr>
          <td colspan="6" class="empty-row">No feasible recommendations available.</td>
        </tr>
      `;
      return;
    }
    elements.recommendationsBody.innerHTML = recommendations
      .map(
        (rec) => `
          <tr>
            <td>
              <strong>${escapeHtml(rec.name)}</strong>
              <span class="subtle">${escapeHtml(rec.player_id)}</span>
            </td>
            <td>${escapeHtml(formatPositions(rec.positions))}</td>
            <td>${escapeHtml(formatNumber(rec.projected_points))}</td>
            <td>${escapeHtml(formatNumber(rec.score))}</td>
            <td>${escapeHtml(rec.suggested_slot)}</td>
            <td>${actionButtons(rec.player_id)}</td>
          </tr>
        `,
      )
      .join("");
  }

  function renderSearchResults() {
    if (!snapshot) {
      elements.searchResultsBody.innerHTML = "";
      elements.searchCount.textContent = "";
      return;
    }

    const query = elements.searchQuery.value.trim().toLowerCase();
    const players = availablePlayers().filter((player) => {
      if (!query) {
        return true;
      }
      return (
        player.name.toLowerCase().includes(query) || player.player_id.toLowerCase().includes(query)
      );
    });
    const visiblePlayers = players.slice(0, 12);
    elements.searchCount.textContent = `${visiblePlayers.length} shown of ${players.length}`;

    if (!visiblePlayers.length) {
      elements.searchResultsBody.innerHTML = `
        <tr>
          <td colspan="4" class="empty-row">No matching available players.</td>
        </tr>
      `;
      return;
    }

    elements.searchResultsBody.innerHTML = visiblePlayers
      .map(
        (player) => `
          <tr>
            <td>
              <strong>${escapeHtml(player.name)}</strong>
              <span class="subtle">${escapeHtml(player.player_id)}</span>
            </td>
            <td>${escapeHtml(formatPositions(player.positions))}</td>
            <td>${escapeHtml(formatNumber(player.projected_points))}</td>
            <td>${actionButtons(player.player_id)}</td>
          </tr>
        `,
      )
      .join("");
  }

  function renderMyPicks() {
    if (!snapshot) {
      elements.myPicksList.innerHTML = "";
      elements.myPicksCount.textContent = "";
      return;
    }
    const myPicks = Array.isArray(snapshot.my_picks) ? snapshot.my_picks : [];
    elements.myPicksCount.textContent = `${myPicks.length} drafted`;
    if (!myPicks.length) {
      elements.myPicksList.innerHTML = `<li class="empty-list-item">No picks recorded yet.</li>`;
      return;
    }
    elements.myPicksList.innerHTML = myPicks
      .map(
        (player) => `
          <li>
            <div>
              <strong>${escapeHtml(player.name)}</strong>
              <span>${escapeHtml(formatPositions(player.positions))}</span>
            </div>
            <span>${escapeHtml(formatNumber(player.projected_points))}</span>
          </li>
        `,
      )
      .join("");
  }

  function renderHistory() {
    if (!snapshot) {
      elements.historyList.innerHTML = "";
      return;
    }
    const history = Array.isArray(snapshot.history) ? snapshot.history.slice().reverse() : [];
    if (!history.length) {
      elements.historyList.innerHTML = `<li class="empty-list-item">No picks yet.</li>`;
      return;
    }
    elements.historyList.innerHTML = history
      .map((event, index) => {
        const pickNumber = snapshot.summary.current_pick_number - index;
        const tone = event.side === "my" ? "mine" : "other";
        const subtitle = event.from_pool ? event.label : `Off-list: ${event.label}`;
        return `
          <li class="${tone}">
            <span class="history-pick">Pick ${escapeHtml(pickNumber)}</span>
            <strong>${event.side === "my" ? "My pick" : "Other pick"}</strong>
            <span>${escapeHtml(subtitle)}</span>
          </li>
        `;
      })
      .join("");
  }

  function render() {
    applySettingsToForm(state.settings);
    elements.sourceLabel.textContent = state.sourceName || "No CSV loaded";
    const hasPlayers = state.players.length > 0;
    elements.actionPanel.hidden = !hasPlayers;
    elements.emptyState.hidden = hasPlayers;
    elements.draftShell.hidden = !hasPlayers || !snapshot;

    if (!hasPlayers) {
      elements.searchQuery.value = "";
      elements.recommendationsBody.innerHTML = "";
      elements.searchResultsBody.innerHTML = "";
      elements.myPicksList.innerHTML = "";
      elements.historyList.innerHTML = "";
      elements.summaryCards.innerHTML = "";
      elements.needsSummary.textContent = "";
      return;
    }

    renderSummary();
    renderRecommendations();
    renderSearchResults();
    renderMyPicks();
    renderHistory();
  }

  elements.uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = elements.csvFileInput.files && elements.csvFileInput.files[0];
    if (!file) {
      showStatus("Choose a CSV file first.", "error");
      return;
    }

    const formData = new window.FormData();
    formData.append("csv_file", file);

    try {
      const payload = await requestJson(endpoints.upload, {
        method: "POST",
        body: formData,
      });
      state.players = payload.players || [];
      state.history = [];
      state.sourceName = file.name;
      state.settings = readSettingsFromForm();
      saveState();
      showStatus(payload.message, "success");
      await refreshSnapshot();
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.applySettingsButton.addEventListener("click", async () => {
    state.settings = readSettingsFromForm();
    saveState();
    if (!state.players.length) {
      render();
      showStatus("Settings saved. Upload a CSV to start the draft.", "info");
      return;
    }
    try {
      await refreshSnapshot();
      showStatus("Recommendations refreshed.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.restartDraftButton.addEventListener("click", async () => {
    if (!state.players.length) {
      return;
    }
    if (!window.confirm("Clear the draft history and restart with the current CSV and settings?")) {
      return;
    }
    state.history = [];
    saveState();
    try {
      await refreshSnapshot();
      showStatus("Draft restarted.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.resetToolButton.addEventListener("click", () => {
    if (!window.confirm("Reset the tool and remove the saved player pool from this browser?")) {
      return;
    }
    resetState();
    elements.csvFileInput.value = "";
    elements.externalLabel.value = "";
    elements.searchQuery.value = "";
    applySettingsToForm(state.settings);
    render();
    showStatus("Local draft data cleared.", "success");
  });

  elements.runForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await applyAction({
        type: "run",
        count: Number(elements.runCount.value || "1"),
      });
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.undoForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await applyAction({
        type: "undo",
        count: Number(elements.undoCount.value || "1"),
      });
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.externalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const label = elements.externalLabel.value.trim();
    if (!label) {
      showStatus("Enter a name for the off-list opponent pick.", "error");
      return;
    }
    try {
      await applyAction({
        type: "other_external",
        label,
      });
      elements.externalLabel.value = "";
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  elements.searchQuery.addEventListener("input", () => {
    renderSearchResults();
  });

  elements.teamsInput.addEventListener("input", syncDraftSlotBounds);

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action-type]");
    if (!button) {
      return;
    }
    const actionType = button.dataset.actionType;
    const playerId = button.dataset.playerId;
    if (!playerId) {
      return;
    }
    try {
      await applyAction({
        type: actionType,
        player_id: playerId,
      });
    } catch (error) {
      showStatus(error.message, "error");
    }
  });

  render();
  if (state.players.length) {
    refreshSnapshot().catch((error) => {
      showStatus(error.message, "error");
    });
  }
})();
