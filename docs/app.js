// Admin page for the GitHub Actions bot. Static: it reads and writes bot-data/*.json and starts
// workflow runs through the GitHub API, using a fine-grained token kept in this browser's localStorage.

const REPO = (() => {
  // On https://<owner>.github.io/<repo>/ use that repo; elsewhere (local testing) fall back to the default.
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  return m && repo ? `${m[1]}/${repo}` : "VolodymyrVolynets/daft-bot";
})();
const BRANCH = "main";
const WORKFLOW = "bot.yml";
const SETTINGS_PATH = "bot-data/settings.json";
const STATE_PATH = "bot-data/state.json";
const TOKEN_KEY = "daftbot.token";

const $ = (id) => document.getElementById(id);
let token = readToken();
let settings = null, settingsSha = null, state = null, options = null;

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
function writeToken(value) {
  try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
  token = value;
}

// ---- GitHub API -------------------------------------------------------------------------

async function gh(path, { method = "GET", body } = {}) {
  const res = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    method,
    cache: "no-store",
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new Error("GitHub rejected the token (expired or wrong). Sign out and sign in again.");
  if (res.status === 403 || res.status === 404) {
    const detail = (await res.json().catch(() => ({}))).message || res.statusText;
    throw new Error(`GitHub said "${detail}". Check the token has Actions and Contents read/write for ${REPO}.`);
  }
  if (!res.ok) throw new Error(`GitHub error ${res.status}: ${(await res.json().catch(() => ({}))).message || res.statusText}`);
  return res.status === 204 ? null : res.json();
}

const fromBase64 = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\n/g, "")), (c) => c.charCodeAt(0)));
function toBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function readJson(path) {
  const file = await gh(`/contents/${path}?ref=${BRANCH}`);
  return { data: JSON.parse(fromBase64(file.content)), sha: file.sha };
}

async function writeSettings(next, message) {
  const res = await gh(`/contents/${SETTINGS_PATH}`, {
    method: "PUT",
    body: { message, branch: BRANCH, sha: settingsSha, content: toBase64(JSON.stringify(next, null, 2) + "\n") },
  });
  settings = next;
  settingsSha = res.content.sha;
}

const dispatch = (command) =>
  gh(`/actions/workflows/${WORKFLOW}/dispatches`, { method: "POST", body: { ref: BRANCH, inputs: { command } } });

// ---- UI helpers -------------------------------------------------------------------------

function flash(message, kind = "ok") {
  const el = $("flash");
  el.textContent = message;
  el.className = `flash ${kind}`;
  el.hidden = !message;
  if (message) el.scrollIntoView({ block: "nearest" });
}

async function busy(button, fn) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Working…";
  try { await fn(); } catch (e) { flash(e.message, "error"); } finally { button.disabled = false; button.textContent = label; }
}

const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—");
const lines = (text) => text.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
const toInt = (text) => (/^\d+$/.test(text.trim()) ? parseInt(text, 10) : null);

function cell(row, content, href) {
  const td = row.insertCell();
  if (href) {
    const a = document.createElement("a");
    a.href = href; a.target = "_blank"; a.rel = "noopener"; a.textContent = content;
    td.append(a);
  } else td.textContent = content ?? "";
  return td;
}

// ---- Views ------------------------------------------------------------------------------

function showTab() {
  const signedIn = Boolean(token);
  const tab = location.hash === "#settings" ? "settings" : "dashboard";
  $("signin").hidden = signedIn;
  $("dashboard").hidden = !signedIn || tab !== "dashboard";
  $("settings").hidden = !signedIn || tab !== "settings";
  document.querySelectorAll("nav a").forEach((a) =>
    a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  $("signout").hidden = !signedIn;
  $("who-text").textContent = signedIn ? REPO : "";
}

function renderDashboard() {
  const running = settings.running;
  $("status-pill").textContent = running ? "Running" : "Stopped";
  $("status-pill").className = `pill ${running ? "on" : "off"}`;
  $("btn-stop").hidden = !running;
  $("start-box").hidden = running;
  $("start-remember").checked = !Object.keys(state.seen || {}).length;
  $("btn-scan").textContent = running ? "Scan now" : "Scan once";
  $("last-summary").textContent = state.last_run_summary
    ? `${state.last_run_summary} (${fmtTime(state.last_run_at)})` : "—";
  $("seen-count").textContent = `${Object.keys(state.seen || {}).length}` +
    (state.remembered_at ? ` (last remembered ${fmtTime(state.remembered_at)})` : "");
  $("last-error").hidden = !state.last_error;
  $("last-error").textContent = state.last_error ? `Last error: ${state.last_error}` : "";

  const body = $("matches");
  body.replaceChildren();
  for (const m of (state.matches || []).slice(0, 50)) {
    const row = body.insertRow();
    cell(row, m.title, m.url); cell(row, m.price); cell(row, m.beds ?? ""); cell(row, fmtTime(m.notified_at));
  }
  if (!body.rows.length) cell(body.insertRow(), "No matches yet.").colSpan = 4;
}

async function loadRuns() {
  const data = await gh(`/actions/workflows/${WORKFLOW}/runs?per_page=15`);
  const body = $("runs");
  body.replaceChildren();
  for (const r of data.workflow_runs) {
    const row = body.insertRow();
    cell(row, fmtTime(r.run_started_at || r.created_at), r.html_url);
    cell(row, r.event === "schedule" ? "Scheduled" : "Manual");
    const result = r.status !== "completed" ? r.status.replace("_", " ") : r.conclusion;
    const td = cell(row, result);
    td.className = r.status !== "completed" ? "status-wait" : r.conclusion === "success" ? "status-ok" : "status-bad";
  }
  if (!body.rows.length) cell(body.insertRow(), "No runs yet.").colSpan = 3;
}

function renderSettings() {
  const s = settings;
  $("locations").value = (s.locations || []).join("\n");
  for (const k of ["min_price", "max_price", "min_beds", "max_beds", "max_age_hours", "max_notifications_per_run", "max_pages"])
    $(k).value = s[k] ?? "";
  for (const k of ["include_keywords", "exclude_keywords", "exclude_agents"]) $(k).value = (s[k] || []).join("\n");
  $("message_template").value = s.message_template || "";
  $("remember_after").checked = false;

  const box = $("property-types");
  box.replaceChildren();
  for (const p of options.propertyTypes) {
    const label = document.createElement("label");
    const input = Object.assign(document.createElement("input"), { type: "checkbox", value: p, checked: (s.property_types || []).includes(p) });
    label.append(input, " " + p.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()));
    box.append(label);
  }
}

async function loadAll() {
  if (!token) return showTab();
  try {
    const [s, st] = await Promise.all([readJson(SETTINGS_PATH), readJson(STATE_PATH)]);
    settings = s.data; settingsSha = s.sha; state = st.data;
    showTab();
    renderDashboard();
    renderSettings();
    await loadRuns();
  } catch (e) {
    showTab();
    flash(e.message, "error");
  }
}

// ---- Actions ----------------------------------------------------------------------------

$("signin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  writeToken($("token").value.trim());
  $("token").value = "";
  flash("");
  await loadAll();
});

$("signout").addEventListener("click", () => { writeToken(""); flash("Signed out."); showTab(); });

$("btn-start").addEventListener("click", (e) => busy(e.target, async () => {
  if ($("start-remember").checked) await dispatch("remember");
  await writeSettings({ ...settings, running: true }, "Start bot from admin page");
  renderDashboard();
  flash($("start-remember").checked
    ? "Bot started. Remembering current listings first (takes about a minute), then it checks every 5 minutes."
    : "Bot started. It checks every 5 minutes.");
}));

$("btn-stop").addEventListener("click", (e) => busy(e.target, async () => {
  await writeSettings({ ...settings, running: false }, "Stop bot from admin page");
  renderDashboard();
  flash("Bot stopped. Scheduled runs will now exit straight away.");
}));

$("btn-scan").addEventListener("click", (e) => busy(e.target, async () => {
  await dispatch("scan");
  flash("Scan started on GitHub. It takes about a minute; press Refresh under Recent runs to follow it.");
  setTimeout(() => loadRuns().catch(() => {}), 4000);
}));

$("btn-remember").addEventListener("click", (e) => busy(e.target, async () => {
  await dispatch("remember");
  flash("Remembering current listings on GitHub (about a minute). They won't be notified.");
  setTimeout(() => loadRuns().catch(() => {}), 4000);
}));

$("btn-refresh").addEventListener("click", (e) => busy(e.target, loadAll));

$("loc-add").addEventListener("click", () => {
  const value = $("loc-search").value.trim().toUpperCase().replace(/ /g, "_");
  if (!value) return;
  const current = lines($("locations").value);
  if (!current.includes(value)) current.push(value);
  $("locations").value = current.join("\n");
  $("loc-search").value = "";
  $("loc-search").focus();
});

$("settings").addEventListener("submit", (e) => {
  e.preventDefault();
  busy($("btn-save"), async () => {
    const locations = lines($("locations").value).map((x) => x.toUpperCase().replace(/ /g, "_"));
    const known = new Set(options.locations);
    const unknown = locations.filter((x) => !known.has(x));
    if (!locations.length || unknown.length) {
      throw new Error(`Unknown location(s): ${unknown.join(", ") || "none given"}. Pick from the suggestions.`);
    }
    const next = {
      ...settings,
      locations,
      property_types: [...$("property-types").querySelectorAll("input:checked")].map((i) => i.value),
      min_price: toInt($("min_price").value), max_price: toInt($("max_price").value),
      min_beds: toInt($("min_beds").value), max_beds: toInt($("max_beds").value),
      max_pages: Math.min(Math.max(toInt($("max_pages").value) || 1, 1), 10),
      include_keywords: lines($("include_keywords").value),
      exclude_keywords: lines($("exclude_keywords").value),
      exclude_agents: lines($("exclude_agents").value),
      max_age_hours: toInt($("max_age_hours").value),
      max_notifications_per_run: Math.max(toInt($("max_notifications_per_run").value) || 10, 1),
      message_template: $("message_template").value.trim(),
    };
    await writeSettings(next, "Update settings from admin page");
    if ($("remember_after").checked) {
      await dispatch("remember");
      flash("Saved. Remembering listings that match the new criteria (about a minute).");
    } else flash("Saved. The next scan uses the new settings.");
    renderSettings();
  });
});

window.addEventListener("hashchange", () => { flash(""); showTab(); });

(async function init() {
  $("repo-name").textContent = REPO;
  $("secrets-link").href = `https://github.com/${REPO}/settings/secrets/actions`;
  options = await fetch("options.json").then((r) => r.json());
  $("loc-list").replaceChildren(...options.locations.map((n) => Object.assign(document.createElement("option"), { value: n })));
  await loadAll();
})();
