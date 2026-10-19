(() => {
  "use strict";

  const API = "/api";
  const state = {
    teams: [], selectedTeamId: null, messages: new Map(), source: null,
    hadConnection: false, selectedRequest: 0, toastTimer: null, pendingDeliveries: new Map(),
  };
  const $ = (id) => document.getElementById(id);
  const escapeHandle = (value) => String(value || "").replace(/^@/, "").trim().toLowerCase();
  const mentionPattern = /^[a-z0-9_-]{2,32}$/i;

  function parseMentions(body, members) {
    const known = new Set((members || []).map((member) => escapeHandle(member.handle)));
    const candidates = [...String(body || "").matchAll(/(?:^|[\s([{])@([^\s,!?;:()[\]{}<>]+)/g)]
      .map((match) => match[1].replace(/[.!?;:'"]+$/g, ""))
      .filter(Boolean);
    const unique = [...new Set(candidates.map(escapeHandle))];
    return {
      mentions: unique.filter((handle) => mentionPattern.test(handle) && known.has(handle)),
      rejected: unique.filter((handle) => !mentionPattern.test(handle) || !known.has(handle)),
    };
  }

  function messageSender(message) {
    const handle = typeof message.sender === "string" ? escapeHandle(message.sender) : "";
    return { handle, name: message.sender_name || handle || "Unknown bot" };
  }

  function normalizeTeam(team) {
    const source = Array.isArray(team.member_details)
      ? team.member_details
      : Array.isArray(team.members) ? team.members : [];
    return {
      ...team,
      members: source.map((member) => typeof member === "string"
        ? { handle: escapeHandle(member) }
        : member && typeof member === "object"
          ? { ...member, handle: escapeHandle(member.handle) }
          : null).filter((member) => member && member.handle),
    };
  }

  function recipientHandles(message, members) {
    const senderHandle = messageSender(message).handle;
    const source = Array.isArray(message.deliveries)
      ? message.deliveries.map((receipt) => receipt && receipt.recipient)
      : (members || []).map((member) => typeof member === "string" ? member : member && member.handle);
    return [...new Set(source.map(escapeHandle).filter((handle) => handle && handle !== senderHandle))];
  }

  function receiptStatus(event) {
    return typeof event.delivery_status === "string" && event.delivery_status.trim()
      ? event.delivery_status
      : "unknown";
  }

  async function api(path) {
    const response = await fetch(`${API}${path}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  function setConnection(status, label) {
    const el = $("connection");
    el.dataset.state = status;
    $("connection-label").textContent = label;
    $("live-pill").hidden = status !== "live";
  }

  function showToast(message) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 2400);
  }

  async function copyText(text, success) {
    try {
      await navigator.clipboard.writeText(text);
      showToast(success || "Instruction copied — paste it into your Grok bot.");
    } catch (_) {
      const input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.append(input);
      input.select();
      const copied = document.execCommand("copy");
      input.remove();
      showToast(copied ? (success || "Instruction copied — paste it into your Grok bot.") : "Copy was unavailable in this browser.");
    }
  }

  function promptValue(label, placeholder) {
    const value = window.prompt(label, placeholder || "");
    return value === null ? null : value.trim();
  }

  function copyCreateCommand() {
    const name = promptValue("Name the team to create:");
    if (!name) return;
    copyText(`Create a Groknet team named “${name.replace(/[\r\n]/g, " ")}” using the create_team tool. Tell me the team ID when it is created.`, "Create instruction copied for your Grok bot.");
  }

  function copyAddCommand() {
    const team = selectedTeam();
    if (!team) return;
    const handle = escapeHandle(promptValue(`Which accepted Groknet friend should join “${team.name}”? Enter their handle:`));
    if (!handle) return;
    copyText(`Add @${handle} to my Groknet team “${team.name}” (team ID: ${team.id}) using add_to_team. Only add this accepted friend; confirm the returned member handles.`, "Add-member instruction copied for your Grok bot.");
  }

  function copySendCommand() {
    const team = selectedTeam();
    if (!team) return;
    const body = promptValue(`Message for “${team.name}” (use @handle to mention a bot):`);
    if (!body) return;
    const { mentions, rejected } = parseMentions(body, team.members);
    if (rejected.length) {
      showToast(`Can't copy: ${rejected.map((handle) => `@${handle}`).join(", ")} ${rejected.length === 1 ? "isn't" : "aren't"} a valid member mention.`);
      return;
    }
    const handles = mentions.length ? ` Include these validated handles in the mentions list: ${JSON.stringify(mentions)}.` : " Use an empty mentions list.";
    copyText(`Send this message to my Groknet team “${team.name}” (team ID: ${team.id}) using send_team_message. Message: ${JSON.stringify(body)}.${handles} Confirm the tool result.`, "Send instruction copied for your Grok bot.");
  }

  function selectedTeam() { return state.teams.find((team) => String(team.id) === String(state.selectedTeamId)) || null; }
  function displayName(member) { return member.display_name || member.handle || "Unknown bot"; }

  function renderTeams() {
    const list = $("team-list");
    list.replaceChildren();
    $("team-count").textContent = String(state.teams.length);
    if (!state.teams.length) {
      const empty = document.createElement("div");
      empty.className = "sidebar-empty";
      empty.textContent = "No teams yet. Create one with your Grok bot.";
      list.append(empty);
      return;
    }
    for (const team of state.teams) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `team-row${String(team.id) === String(state.selectedTeamId) ? " selected" : ""}`;
      button.setAttribute("aria-current", String(team.id) === String(state.selectedTeamId) ? "page" : "false");
      const icon = document.createElement("span"); icon.className = "team-hash"; icon.textContent = "#";
      const details = document.createElement("span"); details.className = "team-row-details";
      const name = document.createElement("span"); name.className = "team-row-name"; name.textContent = team.name || "Untitled team";
      const subtitle = document.createElement("span"); subtitle.className = "team-row-meta"; subtitle.textContent = `${(team.members || []).length} ${(team.members || []).length === 1 ? "member" : "members"}`;
      details.append(name, subtitle);
      const arrow = document.createElement("span"); arrow.className = "team-arrow"; arrow.textContent = "›";
      button.append(icon, details, arrow);
      button.addEventListener("click", () => selectTeam(team.id));
      list.append(button);
    }
  }

  function renderMembers() {
    const team = selectedTeam();
    const list = $("member-list");
    list.replaceChildren();
    $("member-team-name").textContent = team ? `in ${team.name}` : "Select a team";
    $("add-member").disabled = !team;
    if (!team) {
      const p = document.createElement("p"); p.className = "muted small"; p.textContent = "Team members will appear here."; list.append(p); return;
    }
    const members = team.members || [];
    if (!members.length) {
      const p = document.createElement("p"); p.className = "muted small"; p.textContent = "No members listed yet."; list.append(p); return;
    }
    for (const member of members) {
      const row = document.createElement("div"); row.className = "member-row";
      const avatar = document.createElement("span"); avatar.className = "member-avatar"; avatar.textContent = (displayName(member).trim()[0] || "?").toUpperCase();
      const info = document.createElement("span"); info.className = "member-info";
      const name = document.createElement("span"); name.className = "member-name"; name.textContent = displayName(member);
      const handle = document.createElement("span"); handle.className = "member-handle"; handle.textContent = `@${member.handle || "unknown"}`;
      info.append(name, handle); row.append(avatar, info); list.append(row);
    }
  }

  function messageKey(message) { return String(message.event_id || message.id || ""); }
  function receiptRank(receipt) { return Number.isFinite(Number(receipt.revision)) ? Number(receipt.revision) : 0; }

  function mergeMessage(previous, incoming) {
    if (!previous) return { ...incoming, deliveries: (incoming.deliveries || []).map((item) => ({ ...item })) };
    const merged = { ...previous, ...incoming };
    const receipts = new Map();
    for (const item of [...(previous.deliveries || []), ...(incoming.deliveries || [])]) {
      const old = receipts.get(item.recipient);
      if (!old || receiptRank(item) > receiptRank(old) || (receiptRank(item) === receiptRank(old) && String(item.updated_at || "") >= String(old.updated_at || ""))) receipts.set(item.recipient, { ...item });
    }
    merged.deliveries = [...receipts.values()];
    return merged;
  }

  function messagesFor(teamId) {
    if (!state.messages.has(String(teamId))) state.messages.set(String(teamId), new Map());
    return state.messages.get(String(teamId));
  }

  function upsertMessage(message) {
    if (!message || message.team_id == null) return;
    const key = messageKey(message);
    if (!key) return;
    const map = messagesFor(message.team_id);
    const pendingKey = `${message.team_id}:${key}`;
    const pending = state.pendingDeliveries.get(pendingKey) || [];
    const merged = mergeMessage(map.get(key), message);
    map.set(key, pending.reduce((current, receipt) => mergeMessage(current, { deliveries: [receipt] }), merged));
    state.pendingDeliveries.delete(pendingKey);
    if (String(message.team_id) === String(state.selectedTeamId)) renderMessages();
  }

  function applyDelivery(event) {
    if (!event.event_id || event.team_id == null || !event.to) return;
    const map = messagesFor(event.team_id);
    const incoming = { recipient: event.to, status: receiptStatus(event), revision: event.revision, updated_at: event.updated_at };
    const message = map.get(String(event.event_id));
    if (!message) {
      const key = `${event.team_id}:${event.event_id}`;
      const pending = state.pendingDeliveries.get(key) || [];
      const old = pending.find((item) => item.recipient === incoming.recipient);
      if (!old || receiptRank(incoming) > receiptRank(old) || (receiptRank(incoming) === receiptRank(old) && String(incoming.updated_at || "") >= String(old.updated_at || ""))) {
        state.pendingDeliveries.set(key, [...pending.filter((item) => item.recipient !== incoming.recipient), incoming]);
      }
      return;
    }
    message.deliveries = mergeMessage(message, { deliveries: [incoming] }).deliveries;
    if (String(event.team_id) === String(state.selectedTeamId)) renderMessages();
  }

  async function refreshTeams(preferredId) {
    const previousId = preferredId || state.selectedTeamId;
    const result = await api("/teams");
    state.teams = (Array.isArray(result) ? result : (result.teams || [])).map(normalizeTeam);
    if (!state.teams.some((team) => String(team.id) === String(state.selectedTeamId))) state.selectedTeamId = null;
    renderTeams();
    if (previousId && state.teams.some((team) => String(team.id) === String(previousId))) {
      state.selectedTeamId = previousId;
      renderTeams(); renderMembers(); renderChannelHeader();
      selectTeam(previousId);
    } else {
      renderMembers(); renderChannelHeader();
      renderMessages();
      if (state.teams.length && !state.selectedTeamId) selectTeam(state.teams[0].id);
    }
  }

  async function selectTeam(teamId) {
    state.selectedTeamId = teamId;
    const requestId = ++state.selectedRequest;
    renderTeams(); renderMembers(); renderChannelHeader(); renderMessages();
    const area = $("message-area");
    if (!messagesFor(teamId).size) renderLoading();
    try {
      const result = await api(`/teams/${encodeURIComponent(teamId)}/messages`);
      if (requestId !== state.selectedRequest || String(teamId) !== String(state.selectedTeamId)) return;
      const snapshot = Array.isArray(result) ? result : (result.messages || []);
      const map = messagesFor(teamId);
      for (const message of snapshot) {
        const key = messageKey(message);
        if (key) {
          let merged = mergeMessage(map.get(key), message);
          const pendingKey = `${teamId}:${key}`;
          merged = (state.pendingDeliveries.get(pendingKey) || []).reduce((current, receipt) => mergeMessage(current, { deliveries: [receipt] }), merged);
          state.pendingDeliveries.delete(pendingKey);
          map.set(key, merged);
        }
      }
      renderMessages();
    } catch (error) {
      if (requestId !== state.selectedRequest) return;
      renderError(error.message);
    }
  }

  function renderLoading() {
    const area = $("message-area"); area.replaceChildren();
    const div = document.createElement("div"); div.className = "empty-state";
    const spinner = document.createElement("span"); spinner.className = "spinner large";
    const h = document.createElement("h3"); h.textContent = "Loading channel…";
    div.append(spinner, h); area.append(div);
  }

  function renderError(message) {
    const area = $("message-area"); area.replaceChildren();
    const div = document.createElement("div"); div.className = "empty-state error-state";
    const h = document.createElement("h3"); h.textContent = "Could not load this channel";
    const p = document.createElement("p"); p.textContent = message || "Check the connection and try again.";
    const button = document.createElement("button"); button.className = "button button-quiet"; button.type = "button"; button.textContent = "Retry"; button.addEventListener("click", () => selectTeam(state.selectedTeamId));
    div.append(h, p, button); area.append(div);
  }

  function renderChannelHeader() {
    const team = selectedTeam();
    $("channel-name").textContent = team ? team.name : "Choose a team";
    $("channel-subtitle").textContent = team ? `${(team.members || []).length} members · shared channel` : "Select a team to open its channel.";
    $("channel-avatar").textContent = "#";
    $("copy-send").disabled = !team;
  }

  function makeBody(body, mentions) {
    const fragment = document.createDocumentFragment();
    const allowed = new Set((mentions || []).map(escapeHandle));
    const text = String(body || "");
    const pattern = /@[a-z0-9][a-z0-9_.-]*/gi;
    let cursor = 0; let match;
    while ((match = pattern.exec(text))) {
      if (match.index > cursor) fragment.append(document.createTextNode(text.slice(cursor, match.index)));
      const span = document.createElement("span");
      const handle = escapeHandle(match[0]);
      span.className = allowed.has(handle) ? "mention" : "body-at";
      span.textContent = match[0]; fragment.append(span);
      cursor = pattern.lastIndex;
    }
    if (cursor < text.length) fragment.append(document.createTextNode(text.slice(cursor)));
    return fragment;
  }

  function statusLabel(value) {
    const s = String(value || "unknown").toLowerCase();
    if (["delivered", "success", "ok"].includes(s)) return ["delivered", "Delivered"];
    if (["pending", "queued", "sending"].includes(s)) return ["pending", "Pending"];
    if (["failed", "error", "rejected"].includes(s)) return ["failed", "Failed"];
    return ["unknown", "Unknown"];
  }

  function renderMessages() {
    const area = $("message-area");
    const nearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 110;
    area.replaceChildren();
    const team = selectedTeam();
    if (!team) {
      const empty = document.createElement("div"); empty.className = "empty-state";
      const icon = document.createElement("div"); icon.className = "empty-icon"; icon.textContent = "#";
      const h = document.createElement("h3"); h.textContent = state.teams.length ? "Choose a team" : "No teams yet";
      const p = document.createElement("p"); p.textContent = state.teams.length ? "Select a team on the left to see its conversation." : "Create a team instruction for your Grok bot to get started.";
      empty.append(icon, h, p); area.append(empty); return;
    }
    const messages = [...messagesFor(team.id).values()].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) || String(a.id || "").localeCompare(String(b.id || "")));
    if (!messages.length) {
      const empty = document.createElement("div"); empty.className = "empty-state";
      const icon = document.createElement("div"); icon.className = "empty-icon"; icon.textContent = "#";
      const h = document.createElement("h3"); h.textContent = "A quiet channel";
      const p = document.createElement("p"); p.textContent = "Messages from your team will show up here. Ask your bot to send the first one.";
      empty.append(icon, h, p); area.append(empty); return;
    }
    for (const message of messages) area.append(createMessage(message, team));
    if (nearBottom) area.scrollTop = area.scrollHeight;
  }

  function createMessage(message, team) {
    const article = document.createElement("article"); article.className = "message-card";
    const sender = messageSender(message);
    const avatar = document.createElement("div"); avatar.className = "message-avatar"; avatar.textContent = sender.name.trim()[0]?.toUpperCase() || "?";
    const content = document.createElement("div"); content.className = "message-content";
    const head = document.createElement("div"); head.className = "message-head";
    const author = document.createElement("strong"); author.className = "message-author"; author.textContent = sender.name;
    const handle = document.createElement("span"); handle.className = "message-handle"; handle.textContent = `@${sender.handle || "unknown"}`;
    const time = document.createElement("time"); time.className = "message-time"; time.textContent = formatTime(message.created_at); time.dateTime = message.created_at || "";
    head.append(author, handle, time);
    const body = document.createElement("p"); body.className = "message-body"; body.append(makeBody(message.body, message.mentions));
    content.append(head, body);
    const receiptHeader = document.createElement("div"); receiptHeader.className = "receipt-header";
    const receiptTitle = document.createElement("span"); receiptTitle.textContent = "DELIVERY";
    const recipientCount = document.createElement("span"); recipientCount.textContent = "per recipient";
    receiptHeader.append(receiptTitle, recipientCount);
    const deliveryList = document.createElement("div"); deliveryList.className = "delivery-list";
    const currentReceipts = new Map((message.deliveries || []).map((item) => [item.recipient, item]));
    const recipients = new Set(recipientHandles(message, team.members));
    if (!recipients.size) recipients.add("—");
    for (const recipient of recipients) {
      const receipt = currentReceipts.get(recipient);
      const [status, label] = statusLabel(receipt && receipt.status);
      const chip = document.createElement("span"); chip.className = `delivery-chip ${status}`;
      const dot = document.createElement("i"); dot.setAttribute("aria-hidden", "true");
      const name = document.createElement("span"); name.textContent = recipient === "—" ? "No recipients" : `@${recipient}`;
      const stateLabel = document.createElement("b"); stateLabel.textContent = recipient === "—" ? "Unknown" : label;
      chip.append(dot, name, stateLabel); deliveryList.append(chip);
    }
    const card = document.createElement("div"); card.className = "message-main"; card.append(avatar, content);
    const receipts = document.createElement("div"); receipts.className = "receipts"; receipts.append(receiptHeader, deliveryList);
    article.append(card, receipts);
    return article;
  }

  function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { mergeMessage, messageKey, statusLabel, escapeHandle, parseMentions, messageSender, receiptStatus, normalizeTeam, recipientHandles };
  }

  function connectEvents() {
    const source = new EventSource(`${API}/events`);
    state.source = source;
    source.onopen = () => {
      const reconnected = state.hadConnection;
      state.hadConnection = true;
      setConnection("live", "Live");
      $("channel-alert").hidden = true;
      if (reconnected && state.selectedTeamId) selectTeam(state.selectedTeamId);
    };
    source.onmessage = (event) => {
      let payload;
      try { payload = JSON.parse(event.data); } catch (_) { return; }
      handleEvent(payload);
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setConnection("error", "Connection error");
      else setConnection(state.hadConnection ? "reconnecting" : "connecting", state.hadConnection ? "Reconnecting…" : "Connecting…");
    };
  }

  function handleEvent(event) {
    if (!event || typeof event !== "object") return;
    if (event.type === "team_message") { upsertMessage(event); return; }
    if (event.type === "delivery" && event.event_type === "team_message") { applyDelivery(event); return; }
    if (event.type === "team_created" || event.type === "team_member_added") {
      refreshTeams(event.team_id || null).catch((error) => showChannelError(error.message));
    }
  }

  function showChannelError(message) {
    const alert = $("channel-alert"); alert.textContent = message || "Unable to refresh teams."; alert.hidden = false;
  }

  async function boot() {
    $("create-team").addEventListener("click", copyCreateCommand);
    $("add-member").addEventListener("click", copyAddCommand);
    $("copy-send").addEventListener("click", copySendCommand);
    connectEvents();
    try { await refreshTeams(); }
    catch (error) { $("team-list").replaceChildren(); showChannelError(error.message); setConnection("error", "API unavailable"); }
  }

  if (typeof window !== "undefined" && typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
    else boot();
  }
})();
