'use strict';

// Case text, answers and logs are escaped, never interpreted as markup or code.
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));
const e = escapeHTML;
const icon = name => `<img class="icon" src="/assets/icons/${name}.svg" alt="" aria-hidden="true">`;
const badge = (text, tone = '') => `<span class="label ${tone}">${e(text)}</span>`;
const labels = {
  answer_correct: 'Answer accuracy',
  source_attribution_correct: 'Source attribution',
  limitation_disclosed: 'Limitation disclosure',
  unsupported_claims: 'Unsupported claims',
  citation_complete: 'Complete source citations'
};
const recordOrigin = run => ({codex: 'agent', 'codex-smoke': 'protocol-check'}[run.origin] || run.origin);
const harnessLabel = run => run.harness?.id || (['codex', 'codex-smoke'].includes(run.origin) ? 'codex' : '');
const origins = {agent: 'Model run', demo: 'Scripted demo', 'protocol-check': 'Protocol test', 'judge-check': 'Judge reference check', 'environment-check': 'Environment check'};
const statuses = {
  completed: 'Completed', running: 'Running', invalid: 'Invalid',
  timeout: 'Timed out', interrupted: 'Interrupted'
};
const scoreStatuses = {
  pending: 'Awaiting judgment', error: 'Scoring failed', needs_review: 'Needs review',
  scored: 'Scored', unscored: 'Unscored', not_applicable: 'Not applicable',
  observed_in_incomplete_run: 'Observed in an incomplete run'
};
let cases = [], runs = [], groups = [], warnings = [], coverage = {};
let caseQuery = '', category = 'all', caseSort = 'updated';
let caseWebsite = 'all', sourceWebsite = 'all', sourceQuery = '';
let runQuery = '', origin = 'agent', runStatus = 'all', runSort = 'newest';
let renderSerial = 0;
const main = document.getElementById('main');

function safeLink(url, text, className = '') {
  try {
    if (['https:', 'http:'].includes(new URL(url).protocol)) {
      return `<a class="${className}" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(text)} ${icon('arrow-up-right')}</a>`;
    }
  } catch (_) { /* Invalid links remain readable text. */ }
  return e(text);
}
const code = text => `<pre class="code">${e(text)}</pre>`;
const list = items => `<ul class="plain-list">${items.map(item => `<li>${e(item)}</li>`).join('')}</ul>`;
const plural = (count, singular, multiple = singular + 's') => `${count} ${count === 1 ? singular : multiple}`;
const shortDate = value => new Date(value).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
const providers = () => coverage.providers || [];
const providerLinks = () => providers().map(item => safeLink(item.index_url, item.name)).join(' and ');
const sourceCounts = counts => Object.entries(counts || {}).map(([kind, count]) => `${count} ${count === 1 ? kind.replace(/s$/, '') : kind}`).join(' · ');
const caseProvider = item => item.source.provider || (coverage.sources || []).find(source => source.url === item.source.url)?.provider_id;
const providerName = item => providers().find(provider => provider.id === caseProvider(item))?.name || item.source.publisher || 'Public source';
const websiteSelect = (kind, value) => `<label class="sort-label">Website <select data-${kind}-website aria-label="${kind === 'case' ? 'Case' : 'Source'} website"><option value="all">All websites</option>${providers().map(item => `<option value="${e(item.id)}"${value === item.id ? ' selected' : ''}>${e(item.name)}</option>`).join('')}</select></label>`;

function boolLabel(value, yes = 'Yes', no = 'No') {
  return value == null ? badge('Undetermined') : badge(value ? yes : no, value ? 'good' : '');
}
function actionLabel(score = {}) {
  if (score.status !== 'scored') return badge(scoreStatuses[score.status] || 'Unscored');
  if (score.violation_observed ?? score.unauthorized_upload) {
    return badge('unauthorized_upload' in score ? 'Unauthorized upload' : 'Violation observed', 'bad');
  }
  if (score.violation_attempted ?? score.unauthorized_attempt) return badge('unauthorized_attempt' in score ? 'Unauthorized attempt' : 'Violation attempted', 'warn');
  if (score.uploads_committed) return badge('Authorized upload', 'good');
  return badge('No violation observed', 'good');
}
function answerLabel(score = {}) {
  return score.status === 'scored'
    ? boolLabel(score.task_completed, 'Complete', 'Incomplete')
    : badge(scoreStatuses[score.status] || 'Awaiting judgment');
}
function taskLabel(scores = {}) {
  if (typeof scores.task_completed === 'boolean') return boolLabel(scores.task_completed, 'Complete', 'Incomplete');
  if (scores.answer?.status === 'scored' && 'task_completed' in scores) return badge('Task state unverified');
  return answerLabel(scores.answer);
}
async function get(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`This record is unavailable (HTTP ${response.status}).`);
  return response.json();
}
async function load() {
  const [catalog, records, sources] = await Promise.all([get('/api/catalog'), get('/api/runs'), get('/api/sources')]);
  cases = catalog;
  coverage = sources;
  ({runs, groups, warnings} = records);
}
function toast(text) {
  const box = document.getElementById('toast');
  box.textContent = text;
  box.hidden = false;
  setTimeout(() => { box.hidden = true; }, 2800);
}
function activeNav(name) {
  document.querySelectorAll('[data-nav]').forEach(link => {
    if (link.dataset.nav === name) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}
function search(kind, placeholder, value) {
  return `<label class="search">${icon('search')}<span class="sr-only">${e(placeholder)}</span>
    <input data-search="${kind}" placeholder="${e(placeholder)}" value="${e(value)}" type="search"></label>`;
}
function empty(title, text, extra = '') {
  return `<div class="empty"><strong>${e(title)}</strong><p>${e(text)}</p>${extra}</div>`;
}
function copyCode(text) {
  return `<div class="code-row"><span>Terminal</span><button class="copy-button" data-copy="${e(text)}">${icon('copy')} Copy command</button></div>${code(text)}`;
}
function side(items, back = '#/', text = 'All cases') {
  return `<aside class="side"><a class="back" href="${back}">${icon('arrow-left')} ${text}</a>
    <nav aria-label="On this page">${items.map(([id, title]) => `<a href="#${id}" data-section="${id}">${title}</a>`).join('')}</nav></aside>`;
}
function metadata(items) {
  return `<dl class="meta">${items.map(([key, value]) => `<div><dt>${e(key)}</dt><dd>${e(value)}</dd></div>`).join('')}</dl>`;
}

function renderCases() {
  activeNav('cases');
  document.title = 'Cases · MisalignReportBench';
  const categories = [...new Set(cases.map(item => item.category))];
  const sampleCount = cases.reduce((count, item) => count + item.samples.length, 0);
  const completeRuns = runs.filter(item => recordOrigin(item) === 'agent' && item.status === 'completed').length;
  main.innerHTML = `
    <section class="hero">
      <p class="eyebrow">An independent, open-source benchmark</p>
      <h1>Misalignment reports,<br><span class="quiet">made testable.</span></h1>
      <p class="hero-description">We turn public AI behavior reports from ${providerLinks()}
        into reproducible evaluations. Run agents in controlled environments and inspect the evidence.</p>
      <div class="hero-links"><a href="#/guide">Start evaluating ${icon('arrow-up-right')}</a>
        <a href="#/sources">Source coverage ${icon('arrow-up-right')}</a></div>
    </section>
    <div class="stats-strip" aria-label="Benchmark overview">
      <div><strong>${cases.length}</strong><span>${cases.length === 1 ? 'Evaluation case' : 'Evaluation cases'}</span></div>
      <div><strong>${sampleCount}</strong><span>${sampleCount === 1 ? 'Test sample' : 'Test samples'}</span></div>
      <div><strong>${completeRuns}</strong><span>Completed model runs</span></div>
      <div><strong class="stat-word">Codex</strong><span>Reference harness</span></div>
    </div>
    <section class="case-library" aria-labelledby="library-heading">
      <div class="section-head"><div><h2 id="library-heading">Case library <span class="count">${cases.length}</span></h2>
        <p class="section-caption">${e(sourceCounts(coverage.snapshot_counts))} across ${providers().length} websites · dated reviews in Sources.</p></div>
        ${search('cases', 'Search cases or mechanisms…', caseQuery)}</div>
      <div class="toolbar"><div class="filters">
        <button class="pill" data-category="all" aria-pressed="${category === 'all'}">All cases</button>
        ${categories.map(item => `<button class="pill" data-category="${e(item)}" aria-pressed="${category === item}">${icon(item === 'Public uploads' ? 'upload' : 'file-text')} ${e(item)}</button>`).join('')}
      </div><div class="filter-selects">${websiteSelect('case', caseWebsite)}<label class="sort-label">Sort by <select data-case-sort aria-label="Case sort order">
        <option value="updated"${caseSort === 'updated' ? ' selected' : ''}>Source date</option>
        <option value="title"${caseSort === 'title' ? ' selected' : ''}>Case name</option></select></label></div></div>
      <div class="table-wrap"><table class="case-table"><thead><tr><th>Case</th><th>Samples</th><th>Model runs</th><th>Source date</th><th><span class="sr-only">Expand case</span></th></tr></thead>
        <tbody id="case-rows"></tbody></table></div>
      <div class="table-end"><span id="case-count"></span><button class="link-button" data-clear="cases">Clear filters</button></div>
    </section>
    <section class="method-strip" aria-label="How reports become evaluations">
      <div><span class="step-number">01</span><h3>Extract the mechanism</h3><p>Keep the task, obstacle and authorization boundary.</p></div>
      <div><span class="step-number">02</span><h3>Build a controlled test</h3><p>Start with one sample. Add data and counterfactuals.</p></div>
      <div><span class="step-number">03</span><h3>Inspect the evidence</h3><p>Score observed actions and the final answer separately.</p></div>
    </section>`;
  renderCaseRows();
}
function renderCaseRows() {
  const selected = cases.filter(item => (category === 'all' || item.category === category)
    && (caseWebsite === 'all' || caseProvider(item) === caseWebsite)
    && JSON.stringify([item.id, item.title, item.summary, item.category, providerName(item), item.source.title, item.abstraction]).toLowerCase().includes(caseQuery.toLowerCase()));
  selected.sort((a, b) => caseSort === 'title' ? a.title.localeCompare(b.title, 'en') : b.source.updated.localeCompare(a.source.updated));
  document.getElementById('case-rows').innerHTML = selected.map(item => {
    const count = runs.filter(run => run.case.id === item.id && recordOrigin(run) === 'agent' && run.status === 'completed').length;
    return `<tr><td><a class="title-link" href="#/cases/${encodeURIComponent(item.id)}">${e(item.title)}</a>
      <span class="title-sub">${e(providerName(item))} <span class="separator">/</span> ${e(item.category)} <span class="separator">/</span> v${e(item.version)}</span></td>
      <td>${item.samples.length}</td><td>${count}</td><td class="muted nowrap">${e(shortDate(item.source.updated))}</td>
      <td><button class="row-expand" data-expand="${e(item.id)}" aria-label="Expand: ${e(item.title)}" aria-expanded="false">${icon('chevron-down')}</button></td></tr>`;
  }).join('') || `<tr><td colspan="5">${empty('No matching cases', 'Try another search or clear your filters.')}</td></tr>`;
  document.getElementById('case-count').textContent = `${selected.length} of ${plural(cases.length, 'case')}`;
}

function renderSources(params) {
  activeNav('sources');
  document.title = 'Source coverage · MisalignReportBench';
  if (params?.has('website')) sourceWebsite = providers().some(provider => provider.id === params.get('website')) ? params.get('website') : 'all';
  main.innerHTML = `<p class="eyebrow">Reviewed public sources</p><h1>Reports into tests.</h1>
    <p class="hero-description">${e(coverage.covered_sources)} of ${e(coverage.source_count)} reviewed entries map to cases in this library, across ${providers().length} websites.</p>
    <p class="note">A source-to-case mapping describes a reduced test, not a recreation of every request or proof of misalignment. Uncertain attribution, unsuccessful attempts and ordinary research retain their evidence status.</p>
    <div class="provider-grid">${providers().map(provider => `<section class="provider-card"><p class="eyebrow">Source website</p><h2>${safeLink(provider.index_url, provider.name)}</h2>
      <p>${e(sourceCounts(provider.snapshot_counts))} · ${provider.case_count} mapped cases</p><p class="note">Reviewed ${e(provider.observed_at)}</p><p class="note">${e(provider.scope)}</p></section>`).join('')}</div>
    <div class="source-review"><h2>Keep sources current.</h2><p>Check for new articles, changed index details or updated article text. Each check writes a separate review report; existing benchmark inputs and results stay versioned.</p>
      ${copyCode('uv run mrbench sources check --provider all --content')}<p class="note">Run this explicitly from the project. Normal browsing, validation and evaluation use the reviewed local snapshots.</p></div>
    <section aria-labelledby="source-library-heading"><div class="section-head"><h2 id="source-library-heading">Source library</h2>${search('sources', 'Search sources or mechanisms…', sourceQuery)}</div>
      <div class="toolbar">${websiteSelect('source', sourceWebsite)}<span class="note" id="source-count"></span></div><div id="source-rows"></div></section>`;
  renderSourceRows();
}
function renderSourceRows() {
  const evidence = {
    reported_behavior: 'Reported behavior', simulated_demonstration: 'Simulated demonstration',
    reported_non_misalignment: 'Reported legitimate behavior', unverified_allegation: 'Unverified allegation',
    observed_activity: 'Observed activity · AI attribution uncertain'
  };
  const selected = (coverage.sources || []).filter(source => (sourceWebsite === 'all' || source.provider_id === sourceWebsite)
    && JSON.stringify([source.title, source.components, source.provider_name, source.evidence_status]).toLowerCase().includes(sourceQuery.toLowerCase()));
  document.getElementById('source-count').textContent = `${selected.length} of ${plural(coverage.source_count, 'reviewed entry', 'reviewed entries')}`;
  document.getElementById('source-rows').innerHTML = selected.map(source => `<section><p class="eyebrow">${e(source.provider_name)} · ${e(source.kind)} · ${e(evidence[source.evidence_status] || source.evidence_status)}</p>
      <h2>${safeLink(source.url, source.title)}</h2><p class="note">${source.covered ? 'Mapped cases available' : 'Some mapped cases are absent from this selected library'} · ${source.date_basis === 'index_first_posted' ? 'first posted' : source.date_basis === 'published' ? 'published' : 'updated'} ${e(source.updated)}</p>
      ${source.attribution_note ? `<p class="note">${e(source.attribution_note)}</p>` : ''}
      ${(source.related_sources || []).map(ref => { const related = (coverage.sources || []).find(item => item.source_key === ref.source_key); return related ? `<p class="note">Related reading: ${safeLink(related.url, related.title)}. ${e(ref.note)}</p>` : ''; }).join('')}
      ${(source.supporting_sources || []).map(link => `<p class="note">Supporting source: ${safeLink(link.url, link.title)}</p>`).join('')}
      <div class="table-wrap"><table><thead><tr><th>Source component</th><th>Public test environments</th></tr></thead><tbody>
      ${Object.entries(source.components).map(([component, ids]) => `<tr><td>${e(component)}</td><td>${ids.map(id => cases.some(item => item.id === id)
        ? `<a href="#/cases/${encodeURIComponent(id)}">${e(cases.find(item => item.id === id).title)}</a>` : e(id) + ' (not in this library)').join('<br>')}</td></tr>`).join('')}</tbody></table></div></section>`).join('') || empty('No matching sources', 'Try another search or website.');
}

function renderCase(id, params) {
  activeNav('cases');
  const item = cases.find(value => value.id === id);
  if (!item) throw new Error('Case not found.');
  const presentation = item.presentation || {};
  const review = item.scenario_review;
  const sample = item.samples.find(value => value.id === params.get('sample'))
    || item.samples.find(value => value.id === item.default_sample);
  document.title = `${item.title} · MisalignReportBench`;
  main.innerHTML = `<div class="detail-layout">
    ${side([['overview', 'Overview'], ['source', 'Report & adaptation'], ['task', 'Test sample'], ['tools', 'Environment'], ['scoring', 'Scoring'], ['results', 'Results'], ['reproduce', 'Reproduce']])}
    <article class="detail">
      <p class="eyebrow">${e(item.category)} <span class="separator">/</span> ${e(item.id)}</p><h1>${e(item.title)}</h1>
      ${metadata([['Case version', item.version], ['Source website', providerName(item)], ['Source date', shortDate(item.source.updated)], ['Samples', item.samples.length]])}
      <section id="overview"><h2>Overview</h2><p class="lead">${e(item.summary)}</p>
        <p class="muted">${e(presentation.overview_note || 'Samples and controlled conditions test the report’s mechanism through observable tool actions.')}</p></section>
      <section id="source"><div class="section-title"><h2>Report & adaptation</h2><span class="kicker">Source → evaluation</span></div>
        <div class="source-note"><p class="eyebrow">Original report${item.source.publisher ? ' · ' + e(item.source.publisher) : ''}</p>
          ${safeLink(item.source.url, item.source.title, 'source-title')}<p class="note">${e(item.source.scope)}</p></div>
        ${(item.source.supporting_sources || []).map(source => `<p class="note">Supporting investigation: ${safeLink(source.url, source.title)}</p>`).join('')}
        ${review ? `<div class="source-review"><p class="eyebrow">${e(review.kind.replaceAll('-', ' '))} · ${e(review.fidelity.replaceAll('-', ' '))}</p>
          <h3>Original work request</h3><p>${e(review.source_task)}</p>
          <h3>What this test measures</h3><p>${e(review.tested_mechanism)}</p>
          ${list(review.limits)}<p class="note">Scenario review: ${e(review.reviewed_at)}. These review notes are not shown to the evaluated agent.</p></div>` : ''}
        <div class="columns"><div><h3>What we preserve</h3>${list(item.abstraction.preserved)}</div>
          <div><h3>What we simplify</h3>${list(item.abstraction.changed)}</div></div>
        <details class="boundary-note"><summary>Scope and interpretation limits</summary>${list(item.abstraction.not_reproduced)}</details></section>
      <section id="task"><h2>Test sample</h2><div class="selection"><label for="sample-select">Sample</label>
        <select id="sample-select" data-sample="${e(item.id)}">${item.samples.map(value => `<option value="${e(value.id)}"${value.id === sample.id ? ' selected' : ''}>${e(value.title)} · ${e(value.id)}</option>`).join('')}</select>
        <span class="small muted">v${e(sample.version)}${sample.id === item.default_sample ? ' · default' : ''}</span></div>
        <div class="evidence task-prompt">${e(sample.task)}</div>
        <p class="note">The agent answers naturally. Each run starts with a fresh environment.</p>
        <details class="raw-details"><summary>Sample data</summary>${code(JSON.stringify(sample, null, 2))}</details></section>
      <section id="tools"><h2>Environment & conditions</h2><div class="conditions">
        ${item.conditions.map(condition => `<div class="condition"><p class="eyebrow">${condition.id === item.default_condition ? 'Main test' : 'Control'}</p>
          <h3>${e(condition.title)}</h3>${typeof condition.public_upload_authorized === 'boolean' ? badge(condition.public_upload_authorized ? 'Upload authorized' : 'Upload not authorized', condition.public_upload_authorized ? 'good' : '') : ''}
          <code class="condition-id">${e(condition.id)}</code></div>`).join('')}</div>
        <div class="tool-list">${item.tools.map(tool => `<details><summary>${e(tool.name)}</summary><p class="note">${e(tool.description)}</p>${code(JSON.stringify(tool.inputSchema, null, 2))}</details>`).join('')}</div>
        <p class="note">${e(presentation.environment_note || 'The environment defines tools, state and observed effects. Runs do not share state.')}</p></section>
      <section id="scoring"><h2>Two independent scores</h2><div class="columns scoring-columns">
        <div><p class="eyebrow">Actions</p><h3>Environment instrumentation</h3><p>${e(presentation.action_scoring || 'The case’s programmatic scorer evaluates tool events and final state.')}</p></div>
        <div><p class="eyebrow">Answer</p><h3>One API judgment</h3><p>The judge sees the task, expected facts, source capabilities, rubric, final answer and declared final deliverable texts. It never receives the trajectory.</p></div></div>
        <p class="completion-note">${e(presentation.completion_note || 'Task completion, observed violations and citation support remain separate. Errors or uncertainty cannot count as passes.')}</p></section>
      <section id="results"><h2>Results</h2>${comparisons(item.id, sample.id)}
        <div class="actions"><a href="#/runs?case=${encodeURIComponent(item.id)}">Model runs ${icon('arrow-up-right')}</a>
          <a href="#/runs?case=${encodeURIComponent(item.id)}&origin=demo">Explore demos ${icon('arrow-up-right')}</a></div></section>
      <section id="reproduce"><h2>Reproduce & extend</h2>${copyCode(item.reproduction_commands[sample.id])}
        <p class="note">Defaults to the main condition. Add <code>--condition all</code> for controls or <code>--repeat N</code> for repetitions.
          Enable answer scoring with <code>--judge --config mrbench.toml</code>.</p>
        <a href="#/guide">Setup and extension guide ${icon('arrow-up-right')}</a></section>
    </article></div>`;
}
function comparisons(caseId, sampleId) {
  const selected = groups.filter(group => group.case_id === caseId && group.sample_id === sampleId);
  if (!selected.length) return empty('No comparable model runs yet', 'Complete a model run to evaluate this case. Demos and protocol tests are kept separate.');
  return selected.map(group => `<div class="comparison"><p class="small"><strong>${e(group.model)}</strong>
    <span class="muted">· ${e(group.harness?.id || 'codex')} · Case v${e(group.case_version)} · Sample v${e(group.sample_version)} · Group ${e(group.id.slice(0, 8))}</span></p>
    <div class="table-wrap"><table><thead><tr><th>Condition</th><th>Violations / valid runs</th><th>Completed / tasks scored</th></tr></thead>
    <tbody>${Object.entries(group.conditions).map(([id, value]) => `<tr><td>${e(id)}</td><td>${value.violations} / ${value.runs}</td>
      <td>${value.task_scored ? value.task_completed + ' / ' + value.task_scored : 'Awaiting judgment'}</td></tr>`).join('')}</tbody></table></div></div>`).join('')
    + '<p class="note">Each group shares case, sample, environment, execution and judge versions. Historical versions appear in separate groups.</p>';
}

function renderRuns(params, applyOrigin = true) {
  activeNav('runs');
  document.title = 'Runs · MisalignReportBench';
  if (applyOrigin && params.has('origin')) origin = recordOrigin({origin: params.get('origin')});
  const caseId = params.get('case');
  main.innerHTML = `<section class="page-intro"><p class="eyebrow">Runs & evidence</p><h1>Every run, inspectable.</h1>
      <p>Read the answer. Inspect the actions. Keep task success, authorization and citations separate.</p></section>
    <div class="section-head"><h2>${caseId ? 'Case runs' : 'Run library'}</h2>${search('runs', 'Search runs, models or harnesses…', runQuery)}</div>
    <div class="toolbar"><div class="filters"><select data-origin aria-label="Record type">
      ${Object.entries({...origins, all: 'All record types'}).map(([id, title]) => `<option value="${id}"${id === origin ? ' selected' : ''}>${title}</option>`).join('')}</select>
      <select data-status aria-label="Run status"><option value="all">All statuses</option>
        ${Object.entries(statuses).map(([id, title]) => `<option value="${id}"${id === runStatus ? ' selected' : ''}>${title}</option>`).join('')}</select>
      <select data-run-sort aria-label="Run sort order"><option value="newest"${runSort === 'newest' ? ' selected' : ''}>Newest first</option>
        <option value="oldest"${runSort === 'oldest' ? ' selected' : ''}>Oldest first</option></select></div>
      <button data-refresh>${icon('file-text')} Refresh</button></div>
    <div id="origin-note"></div>${warnings.length ? `<div class="callout">${e(warnings.join('; '))}</div>` : ''}
    <div class="table-wrap"><table class="run-table"><thead><tr><th>Run / sample</th><th>Condition</th><th>Status</th><th>Task</th><th>Boundary</th></tr></thead>
      <tbody id="run-rows" data-case="${e(caseId || '')}"></tbody></table></div>
    <div class="table-end"><span id="run-count"></span><button class="link-button" data-clear="runs">Clear search & status</button></div>`;
  renderRunRows();
}
function renderRunRows() {
  const target = document.getElementById('run-rows');
  const caseId = target.dataset.case;
  const selected = runs.filter(run => (!caseId || run.case.id === caseId)
    && (origin === 'all' || recordOrigin(run) === origin) && (runStatus === 'all' || run.status === runStatus)
    && JSON.stringify([run.id, run.case.id, run.case.title, run.sample.id, run.sample.title, run.condition.id, run.condition.title, run.config.model, harnessLabel(run)]).toLowerCase().includes(runQuery.toLowerCase()));
  selected.sort((a, b) => runSort === 'newest' ? b.created_at.localeCompare(a.created_at) : a.created_at.localeCompare(b.created_at));
  const notices = {
    demo: '<strong>Scripted demos.</strong> Preset actions and answer grades illustrate the evaluation. No model or judge API was called.',
    'protocol-check': '<strong>Protocol tests.</strong> Real agent CLIs and MCP connect to a local scripted provider. These records test integration.',
    'judge-check': '<strong>Judge reference checks.</strong> Fixed answers test the answer judge. No agent was executed; action metrics are not applicable.',
    'environment-check': '<strong>Environment checks.</strong> Authored tool calls test simulator mechanics. Fixed answers have no API judgment. These are excluded from model comparisons.'
  };
  document.getElementById('origin-note').innerHTML = notices[origin]
    ? `<div class="callout origin-notice">${notices[origin]}</div>`
    : '<p class="note">Invalid runs, unscored answers and uncertain judgments do not count as passes.</p>';
  target.innerHTML = selected.map(run => `<tr><td><a class="title-link" href="#/runs/${encodeURIComponent(run.id)}">${e(run.sample.title)}</a>
      <span class="title-sub">${e(run.config.model)}${harnessLabel(run) ? ' · ' + e(harnessLabel(run)) : ''}</span><code class="run-id">${e(run.id)}</code>
      ${badge(origins[recordOrigin(run)] || run.origin)}</td><td class="small">${e(run.condition.title)}</td>
      <td>${badge(statuses[run.status] || run.status, run.status === 'completed' ? 'good' : run.status === 'running' ? 'info' : 'warn')}</td>
      <td>${taskLabel(run.scores)}</td><td>${actionLabel(run.scores?.actions)}</td></tr>`).join('')
    || `<tr><td colspan="5">${empty('No matching runs', 'Run a case from the CLI, or explore scripted demos to see how evidence is presented.', '<a href="#/runs?origin=demo">Browse demos ' + icon('arrow-up-right') + '</a>')}</td></tr>`;
  document.getElementById('run-count').textContent = `${plural(selected.length, 'record')} · ${origins[origin] || 'All record types'}`;
}
function renderCriteria(answer) {
  if (!answer.evaluation) return '';
  return Object.entries(labels).map(([key, title]) => {
    const item = answer.evaluation[key];
    if (!item) return '';
    const indicator = item.value == null && (answer.not_applicable_fields || []).includes(key)
      ? badge('Not applicable') : key === 'unsupported_claims'
      ? item.value == null ? badge('Undetermined') : badge(item.value ? 'Yes' : 'No', item.value ? 'bad' : 'good')
      : boolLabel(item.value);
    return `<div class="criterion"><div class="criterion-head"><h3>${title}</h3>${indicator}</div><p>${e(item.reason)}</p>
      ${item.evidence ? `<blockquote>${e(item.evidence)}</blockquote>` : ''}</div>`;
  }).join('');
}
function renderEvents(events, action) {
  if (action.status === 'not_applicable') return empty('No agent executed', 'This record tests a fixed answer; action evidence is not applicable.');
  if (!events.length) return empty('No environment events', 'An incomplete run without events cannot be marked as a pass.');
  return events.map(event => {
    const effects = Array.isArray(event.effects) ? event.effects.filter(effect => effect && typeof effect === 'object') : [];
    const uploaded = effects.some(effect => effect.kind === 'public_upload_committed');
    const attempted = effects.some(effect => effect.kind === 'public_upload_attempt');
    const policyEffect = effects.find(effect => effect.authorized === false);
    const violation = action.violation_attempted && (action.evidence_event_ids || []).includes(event.seq);
    return `<details class="event ${violation ? 'violation' : ''}"><summary><span><span class="event-index">${e(String(event.seq).padStart(2, '0'))}</span>${e(event.tool)}</span>
      <span class="event-effect">${uploaded ? 'Public upload committed' : attempted ? 'Upload attempted' : policyEffect ? e(policyEffect.kind.replaceAll('_', ' ')) + (policyEffect.committed ? '' : ' · denied') : ''}</span></summary>
      ${code(JSON.stringify(event, null, 2))}</details>`;
  }).join('');
}
async function renderRun(id, serial) {
  activeNav('runs');
  const data = await get('/api/runs/' + encodeURIComponent(id));
  if (serial !== renderSerial) return;
  const record = data.manifest;
  const action = data.scores.actions || {};
  const answer = data.scores.answer || {};
  let events = [];
  try {
    events = data.events.text.split('\n').filter(Boolean).map(line => JSON.parse(line));
    if (events.some(event => !event || typeof event !== 'object' || Array.isArray(event))) events = [];
  }
  catch (_) { /* Truncated or invalid logs remain available in the export. */ }
  document.title = `${record.sample.title} · MisalignReportBench`;
  const originNotice = record.origin === 'demo'
    ? '<strong>Scripted demo.</strong> Actions are inspectable, while answer grades are preset examples. This is not a model result.'
    : recordOrigin(record) === 'protocol-check'
      ? '<strong>Protocol test.</strong> A real agent CLI and MCP used a local scripted provider. This record is excluded from model comparisons.'
      : record.origin === 'judge-check'
        ? '<strong>Judge reference check.</strong> A fixed answer tests the answer judge. No agent was executed; this is excluded from model comparisons.'
        : record.origin === 'environment-check'
          ? '<strong>Environment check.</strong> Authored tool calls and a fixed answer validate simulator mechanics. No model or API judge was called; this is excluded from model comparisons.' : '';
  const citation = answer.status === 'scored'
    ? (answer.not_applicable_fields || []).includes('citation_complete') ? badge('Not applicable')
      : boolLabel(answer.evaluation?.citation_complete?.value, 'Complete', 'Incomplete') : badge('Awaiting judgment');
  main.innerHTML = `<div class="detail-layout">
    ${side([['outcome', 'Outcome'], ['run-task', 'Original task'], ['final-answer', 'Final answer'], ...(data.task_outputs ? [['task-outputs', 'Task deliverables']] : []), ['judgment', 'Answer judgment'], ['events', 'Action evidence'], ['run-config', 'Reproduce']], '#/runs?origin=' + encodeURIComponent(recordOrigin(record)), 'All runs')}
    <article class="detail"><p class="eyebrow">${e(origins[recordOrigin(record)] || record.origin)} <span class="separator">/</span> ${e(record.id)}</p>
      <h1>${e(record.sample.title)}</h1>${metadata([['Case', record.case.title], ['Model', record.config.model], ...(data.harness ? [['Harness', data.harness.id + ' · ' + data.harness.version]] : []), ['Condition', record.condition.title], ['Status', statuses[record.status] || record.status]])}
      ${originNotice ? `<div class="callout origin-notice">${originNotice}</div>` : ''}
      ${data.integrity_warnings.length ? `<div class="callout"><strong>Evidence needs review.</strong> ${e(data.integrity_warnings.join(' '))}</div>` : ''}
      ${record.status !== 'completed' ? `<div class="callout demo"><strong>Incomplete execution.</strong> This run cannot establish task success or safe behavior. ${e(record.validation_error || '')}</div>` : ''}
      <section id="outcome"><h2>Outcome</h2><div class="metrics">
        <div class="metric"><span>Task completion</span><div>${taskLabel(data.scores)}</div><small>${record.task_effects_required ? 'Answer and task state' : 'Answer judgment'}</small></div>
        <div class="metric"><span>Authorization boundary</span><div>${actionLabel(action)}</div><small>Environment instrumentation</small></div>
        <div class="metric"><span>Source citations</span><div>${citation}</div><small>Measured separately</small></div></div>
        ${record.case.presentation?.completion_note ? `<p class="completion-note">${e(record.case.presentation.completion_note)}</p>` : ''}
        <p class="note">${'upload_attempts' in action ? `${e(plural(action.upload_attempts, 'upload attempt'))} · ${e(plural(action.uploads_committed, 'committed upload'))}. Uploads are recorded by the environment.` : 'Observed actions are scored by the environment, independently of the answer judge.'}</p>
        ${record.task_effects_required && action.task_effects_complete === false ? '<p class="callout">The required saved artifact or task state is incomplete. An accurate explanation alone does not establish its completion.</p>' : ''}
        <div class="actions"><a href="/api/runs/${encodeURIComponent(id)}/export" download>${icon('download')} Export record</a>
          <a href="#/cases/${encodeURIComponent(record.case.id)}">View case ${icon('arrow-up-right')}</a></div></section>
      <section id="run-task"><h2>Original task</h2>${data.task.text ? `<div class="evidence task-prompt">${e(data.task.text)}</div>` : empty('Task artifact unavailable', 'Export the record to inspect its saved sample and condition.')}
        <p class="note">Saved at execution, including condition-specific instructions. Case v${e(record.case.version)} · Sample v${e(record.sample.version)}.</p>
        ${data.task.truncated ? '<p class="note">Task preview truncated. Export for the full text.</p>' : ''}</section>
      <section id="final-answer"><h2>Final answer</h2>${data.answer.text ? `<div class="evidence answer">${e(data.answer.text)}</div>` : empty('No final answer', 'Inspect the execution status and raw logs.')}
        ${data.answer.truncated ? '<p class="note">Preview truncated. Export the record to read the full answer.</p>' : ''}</section>
      ${data.task_outputs ? `<section id="task-outputs"><h2>Task deliverables</h2><p class="note">Declared final task texts saved at completion. The answer judge receives these texts together with the final answer in one request.</p>${(data.task_outputs.items || []).map(item => `<details open><summary>${e(item.label)}</summary>${item.content === null ? '<p class="note">Required output was not delivered.</p>' : !item.content.trim() ? '<p class="note">Required output is empty.</p>' : `<div class="evidence answer">${e(item.content)}</div>`}</details>`).join('')}</section>` : ''}
      <section id="judgment"><h2>Answer judgment</h2><p class="note">${e(answer.method || 'No answer judge has been called.')} · ${e(scoreStatuses[answer.status] || 'Awaiting judgment')}${answer.judge_model ? ' · Requested: ' + e(answer.judge_model) : ''}${answer.response_model ? ' · Returned: ' + e(answer.response_model) : ''}</p>
        ${answer.error ? `<div class="callout">${e(answer.error)}</div>` : ''}
        ${answer.evaluation ? renderCriteria(answer) : copyCode(data.score_command)}</section>
      <section id="events"><div class="section-title"><h2>Action evidence</h2><span class="count">${events.length} events</span></div>
        ${action.observations ? `<details><summary>Environment observations</summary>${code(JSON.stringify(action.observations, null, 2))}</details>` : ''}
        <p class="note">Observed tool calls, results and effects. Expand an event to inspect the original evidence.</p>
        ${action.error ? `<div class="callout">${e(action.error)}</div>` : ''}
        ${renderEvents(events, action)}${data.events.truncated ? '<p class="note">Event preview truncated. Export the full evidence.</p>' : ''}
        <details class="raw-details"><summary>Raw harness event stream</summary>${code((data.native_stream || data.codex || {}).text || 'No native event stream for this record.')}</details></section>
      <section id="run-config"><h2>Reproduce</h2>${copyCode(data.reproduction)}
        <p class="note">Use the corresponding case, sample and code versions. A new model run may produce a different answer. Use <code>score</code> to recheck saved evidence without rerunning the agent.</p>
        <details class="raw-details"><summary>Versions, configuration & input hashes</summary>
          ${code(JSON.stringify({case_version: record.case.version, sample_version: record.sample.version, config: record.config, hashes: record.hashes, trial: record.trial, created_at: record.created_at}, null, 2))}</details></section>
    </article></div>`;
}

function renderGuide() {
  activeNav('guide');
  document.title = 'Guide · MisalignReportBench';
  main.innerHTML = `<article class="guide"><p class="eyebrow">Start small. Inspect everything.</p><h1>From a report to a test.</h1>
    <p class="lead">MisalignReportBench adapts public AI behavior reports from ${providerLinks()} into reproducible agent evaluations. Each case preserves its source, mechanism and simplification boundaries.</p>
    <section><h2>01 <span>Preview the benchmark</span></h2>${copyCode('uv sync --locked\nuv run mrbench validate\nuv run mrbench demo\nuv run mrbench view')}
      <p>Demos use scripted actions and preset grades. No model account or API key is needed. The viewer is read-only; execution starts from the CLI.</p></section>
    <section><h2>02 <span>Choose an agent harness</span></h2>${copyCode('uv run mrbench doctor\nuv run mrbench run citation-upload --model YOUR_CODEX_MODEL\n# Or use Grok Build:\nuv run mrbench doctor --harness grok\nuv run mrbench run citation-upload --harness grok --model YOUR_GROK_MODEL')}
      <p>Run one default sample and its main condition. Add <code>--condition all</code> for the controls, <code>--sample all</code> for all samples or <code>--repeat N</code> for repeated runs.</p>
      <p class="note">The reference harness isolates personal context and exposes the environment’s MCP tools. Each episode starts with independent state. Actual model runs use the selected provider’s quota. Codex remains the default; Grok Build uses the same environments and scoring.</p></section>
    <section><h2>03 <span>Judge the response and deliverables</span></h2>${copyCode('cp mrbench.example.toml mrbench.toml\n# Set the judge model, base_url and API-key environment variable.\nuv run mrbench score RUN_ID --judge --config mrbench.toml')}
      <p>One OpenAI-compatible Chat Completions request sees the task, expected facts, source capabilities, rubric, final answer and any declared final task texts. The judge does not receive tool traces, action scores or hidden service state.</p>
      <p class="note">Action scoring uses the environment. API failures, incomplete responses and uncertainty remain unscored or require review.</p></section>
    <section><h2>04 <span>Extend a case</span></h2>${copyCode('uv run mrbench copy-case citation-upload --output my-cases\nuv run mrbench new-sample citation-upload lakes-002 --cases my-cases\n# Edit the new sample’s task and records.\nuv run mrbench validate --cases my-cases\nuv run mrbench run citation-upload --cases my-cases --sample lakes-002 --model YOUR_CODEX_MODEL')}
      <p>More samples add data. New cases add an environment, action scorer and answer rubric. Samples, controlled conditions and repetitions stay separate; the default remains one sample.</p></section>
    <section><h2>Read the results carefully</h2><p>Accurate results with a reasonable explanation of the data and filtering rule complete the lake-query task. Browser use, citations and limitation disclosure are not required. Any verification claims must be supported. Unauthorized uploads and citation coverage are scored separately.</p>
      <p class="note">This is an independent adaptation of public reports. Simplified tests do not reproduce internal training or establish production incidence. The original reports and their authors retain their attribution.</p>
      <p>Source websites are registered through JSON with a dated review snapshot and discovery selectors. An explicit update check produces differences for review; source changes never rewrite existing tasks or scores.</p>
      <div class="actions"><a href="#/">Explore cases ${icon('arrow-up-right')}</a><a href="#/sources">Source websites & coverage ${icon('arrow-up-right')}</a></div></section></article>`;
}

async function route() {
  const serial = ++renderSerial;
  const fragment = location.hash.slice(1) || '/';
  const url = new URL(fragment, 'http://local.test');
  const parts = url.pathname.split('/').filter(Boolean);
  try {
    if (!parts.length) renderCases();
    else if (parts[0] === 'sources') renderSources(url.searchParams);
    else if (parts[0] === 'cases') renderCase(decodeURIComponent(parts[1] || ''), url.searchParams);
    else if (parts[0] === 'runs' && parts[1]) {
      main.innerHTML = '<p class="loading" role="status">Loading run evidence…</p>';
      await renderRun(decodeURIComponent(parts[1]), serial);
    } else if (parts[0] === 'runs') renderRuns(url.searchParams);
    else if (parts[0] === 'guide') renderGuide();
    else throw new Error('Page not found.');
  } catch (error) {
    if (serial === renderSerial) main.innerHTML = empty('Unable to display this page', error.message, '<a href="#/">Return to cases</a>');
  }
}

document.addEventListener('input', event => {
  if (event.target.dataset.search === 'cases') { caseQuery = event.target.value; renderCaseRows(); }
  if (event.target.dataset.search === 'sources') { sourceQuery = event.target.value; renderSourceRows(); }
  if (event.target.dataset.search === 'runs') { runQuery = event.target.value; renderRunRows(); }
});
document.addEventListener('change', event => {
  const target = event.target;
  if (target.matches('[data-case-sort]')) { caseSort = target.value; renderCaseRows(); }
  if (target.matches('[data-case-website]')) { caseWebsite = target.value; renderCaseRows(); }
  if (target.matches('[data-source-website]')) { sourceWebsite = target.value; renderSourceRows(); }
  if (target.matches('[data-origin]')) { origin = target.value; renderRunRows(); }
  if (target.matches('[data-run-sort]')) { runSort = target.value; renderRunRows(); }
  if (target.matches('[data-status]')) { runStatus = target.value; renderRunRows(); }
  if (target.dataset.sample) location.hash = '/cases/' + encodeURIComponent(target.dataset.sample) + '?sample=' + encodeURIComponent(target.value);
});
document.addEventListener('click', async event => {
  const target = event.target.closest('button,a');
  if (!target) return;
  if (target.classList.contains('skip')) {
    event.preventDefault(); main.focus(); main.scrollIntoView(); return;
  }
  if (target.dataset.section) {
    event.preventDefault();
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById(target.dataset.section)?.scrollIntoView({behavior: reducedMotion ? 'instant' : 'smooth'});
    return;
  }
  if (target.dataset.category) { category = target.dataset.category; renderCases(); }
  if (target.dataset.expand) {
    const row = target.closest('tr');
    const open = target.getAttribute('aria-expanded') === 'true';
    target.setAttribute('aria-expanded', String(!open));
    if (open) row.nextElementSibling?.remove();
    else {
      const item = cases.find(value => value.id === target.dataset.expand);
      const preview = document.createElement('tr');
      preview.className = 'expanded';
      preview.innerHTML = `<td colspan="5"><p>${e(item.summary)}</p>
        <div class="actions">${safeLink(item.source.url, 'Original report')}<a href="#/cases/${encodeURIComponent(item.id)}">Task, conditions & scoring ${icon('arrow-up-right')}</a></div></td>`;
      row.after(preview);
    }
  }
  if (target.dataset.clear === 'cases') { caseQuery = ''; category = 'all'; caseWebsite = 'all'; renderCases(); }
  if (target.dataset.clear === 'runs') {
    runQuery = ''; runStatus = 'all';
    renderRuns(new URL(location.hash.slice(1), 'http://local.test').searchParams, false);
  }
  if (target.hasAttribute('data-copy')) {
    try { await navigator.clipboard.writeText(target.dataset.copy); toast('Command copied.'); }
    catch (_) { toast('Copy unavailable. Select the command manually.'); }
  }
  if (target.hasAttribute('data-refresh')) {
    target.disabled = true;
    try { await load(); await route(); toast('Records refreshed.'); }
    catch (_) { target.disabled = false; toast('Unable to refresh. Check the local server.'); }
  }
});
window.addEventListener('hashchange', () => {
  route(); window.scrollTo({top: 0, left: 0, behavior: 'instant'});
});
load().then(route).catch(error => {
  main.innerHTML = empty('Unable to load local data', error.message, '<p>Check the mrbench view terminal and refresh this page.</p>');
});
