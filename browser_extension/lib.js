// Shared logic of the side panel (no browser APIs here, so it can be tested with node).

export const DEFAULT_SERVER = "http://127.0.0.1:8000";

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** 'localhost:8000/' -> 'http://localhost:8000'; only local servers are allowed. */
export function normalizeServer(url) {
  let u = String(url || "").trim() || DEFAULT_SERVER;
  if (!/^https?:\/\//i.test(u)) u = "http://" + u;
  let parsed;
  try { parsed = new URL(u); } catch (e) { throw new Error("Invalid server address."); }
  if (!["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname)) {
    throw new Error("Only a server on this computer (127.0.0.1 or localhost) can be used.");
  }
  return `${parsed.protocol}//${parsed.host}`;
}

const DOC_URL = /^https:\/\/docs\.google\.com\/document\/((?:u\/\d+\/)?)d\/([A-Za-z0-9_-]{20,})/;

/** The id of a Google Doc from its URL, or null. */
export function docIdFromUrl(url) {
  const m = String(url || "").match(DOC_URL);
  return m ? m[2] : null;
}

/** Path of the Doc's simple HTML version, keeping the Google account ('/u/1/') it is open in. */
export function docMobilePathFromUrl(url) {
  const m = String(url || "").match(DOC_URL);
  return m ? `/document/${m[1]}d/${encodeURIComponent(m[2])}/mobilebasic` : null;
}

/** Call the research-assistant API; throws an Error with the server's message. */
export async function api(server, token, path, { method = "GET", body, fetchImpl = fetch, timeoutMs = 120000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetchImpl(server + path, {
      method,
      headers: { "Content-Type": "application/json", "x-auth-token": token || "" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new Error(e && e.name === "AbortError"
      ? "The server did not answer in time."
      : `Cannot reach the research-assistant server at ${server}. Is it running?`);
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (res.status === 401 || res.status === 403) throw new Error("Wrong or missing password (see Settings).");
  if (!res.ok) throw new Error((data && data.detail && String(data.detail)) || `Request failed (${res.status}).`);
  return data;
}

export const VERDICT = {
  supports: ["✓ supports", "ok"],
  partly: ["◐ partly", "warn"],
  contradicts: ["✗ contradicts", "bad"],
  unrelated: ["– unrelated", "muted"],
};

function passageHtml(paper, s, group, idx) {
  const sim = s.similarity != null ? `${Math.round(s.similarity * 100)}% similar` : "word match";
  return `<div class="passage" data-group="${group}" data-pass="${idx}">` +
    (s.before ? `<span class="ctx">${esc(s.before)} </span>` : "") +
    `<mark>${esc(s.text)}</mark>` +
    (s.after ? `<span class="ctx"> ${esc(s.after)}</span>` : "") +
    `<div class="verdict" hidden></div>` +
    `<div class="foot"><span class="badge">${sim}</span>` +
    (s.page ? `<button class="link" data-pdf="${esc(paper.hash_id)}" data-page="${esc(s.page)}">PDF p. ${esc(s.page)}</button>` : "") +
    `<button class="link" data-copy="${esc(s.text)}">Copy</button></div></div>`;
}

/** HTML of an /evidence result; ``groups`` receives the passages per claim (for the AI check). */
export function renderEvidence(data, groups) {
  const parts = data.parts && data.parts.length ? data.parts : [{ claim: data.claim, cites: "", papers: data.papers,
    unresolved: data.unresolved || [] }];
  let html = "";
  parts.forEach((part, g) => {
    groups.push({ claim: part.claim, passages: [] });
    html += `<section class="part"><h3>“${esc(part.claim)}”${part.cites ? ` <span class="cites">[${esc(part.cites)}]</span>` : ""}</h3>`;
    (part.unresolved || []).forEach((u) => {
      html += `<p class="note">Reference ${esc(u.label)} is not among the project's papers` +
        (u.reference ? `: <em>${esc(String(u.reference).slice(0, 160))}</em>` : "") + ".</p>";
    });
    const papers = (part.papers || []).filter((p) => p.passages && p.passages.length);
    if (!papers.length) html += `<p class="note">No matching sentence in the project's papers.</p>`;
    const cited = papers.filter((p) => p.cited);
    // the papers come best first: show the cited ones and the 3 best others
    const others = papers.filter((p) => !p.cited).slice(0, 3);
    const paperHtml = (p) => {
      let h = `<div class="paper"><div class="title">${p.cited ? '<span class="cited">cited</span> ' : ""}${esc(p.title || p.hash_id)}` +
        `${p.authors || p.year ? ` <span class="meta">(${esc([p.authors, p.year].filter(Boolean).join(", "))})</span>` : ""}</div>`;
      p.passages.forEach((s) => {
        groups[g].passages.push({ hash_id: p.hash_id, title: p.title || "", text: s.text, before: s.before || "", after: s.after || "" });
        h += passageHtml(p, s, g, groups[g].passages.length - 1);
      });
      return h + "</div>";
    };
    cited.forEach((p) => { html += paperHtml(p); });
    if (others.length) {
      html += cited.length
        ? `<details><summary>${others.length} best other paper(s) of the project</summary>${others.map(paperHtml).join("")}</details>`
        : others.map(paperHtml).join("");
    }
    html += "</section>";
  });
  if (data.not_indexed && data.not_indexed.length) {
    html += `<p class="note">${data.not_indexed.length} paper(s) are still being indexed (word matches for now).</p>`;
  }
  return html;
}

/** HTML summary of a citation-audit report. */
export function renderAudit(report) {
  const s = report.summary || {};
  const refs = report.references || [];
  const problems = refs.filter((r) => !r.in_project || !(r.cited_in || []).length || r.doi_differs_from_library ||
    (r.doi_check && !["ok", "no_doi"].includes(r.doi_check.status)));
  let html = `<section class="part"><h3>Audit${report.source && report.source !== "draft" ? ` of “${esc(report.source)}”` : ""}</h3>` +
    `<p class="note">${esc(s.citing_sentences)} citing sentences, ${esc(s.references)} references ` +
    `(${esc(s.references_in_project)} in the project).</p></section>`;
  const doiBad = refs.filter((r) => r.doi_check && ["not_found", "mismatch"].includes(r.doi_check.status) || r.doi_differs_from_library);
  if (doiBad.length) {
    html += `<section class="part"><h3>DOI problems</h3>` + doiBad.map((r) => {
      const c = r.doi_check || {};
      const why = c.status === "not_found" ? "Crossref does not know this DOI"
        : (c.problems || []).join("; ") || "";
      const lib = r.doi_differs_from_library ? `; your library has ${r.doi_differs_from_library}` : "";
      return `<div class="paper bad"><div class="title">Ref. ${esc(r.n)}: ${esc(r.doi)}</div>` +
        `<p class="note">${esc(why + lib)}</p>` +
        (c.crossref ? `<p class="note">Crossref: <em>${esc(c.crossref.title)}</em> (${esc(c.crossref.first_author)}, ${esc(c.crossref.year)})</p>` : "") +
        `<p class="ctx">${esc(String(r.reference).slice(0, 200))}</p></div>`;
    }).join("") + "</section>";
  }
  const notIn = problems.filter((r) => !r.in_project);
  if (notIn.length) {
    html += `<section class="part"><h3>References not in the project (not checked)</h3><p class="note">` +
      notIn.map((r) => esc(r.n)).join(", ") + `. Add them, with their PDF, to the project's Zotero collection.</p></section>`;
  }
  if ((s.uncited_references || []).length) html += `<p class="note">Never cited: ${esc(s.uncited_references.join(", "))}.</p>`;
  if ((s.citation_numbers_without_reference || []).length) {
    html += `<p class="note bad">Cited but missing from the reference list: ${esc(s.citation_numbers_without_reference.join(", "))}.</p>`;
  }
  html += `<section class="part"><h3>Citations</h3>`;
  (report.citations || []).forEach((c) => {
    html += `<div class="paper"><div class="sentence">${esc(c.sentence)}</div>`;
    (c.parts || []).forEach((p) => {
      html += `<div class="claimrow"><strong>[${esc(p.cites)}]</strong> ${esc(p.claim)}</div>`;
      (p.refs || []).forEach((r) => {
        if (r.status !== "in_project") {
          html += `<div class="ref muted">ref. ${esc(r.label)}: not in the project</div>`;
          return;
        }
        const best = (r.best_sentences || [])[0];
        html += `<div class="ref"><span class="meta">${esc([r.authors, r.year].filter(Boolean).join(", "))}</span> ` +
          (best ? `<mark>${esc(best.text)}</mark> <span class="badge">${best.similarity != null ? Math.round(best.similarity * 100) + "%" : ""}` +
            `${best.page ? " · p. " + esc(best.page) : ""}</span>` : `<span class="note">no matching sentence</span>`) + `</div>`;
      });
      if (p.better_match_elsewhere) {
        const b = p.better_match_elsewhere;
        html += `<div class="ref warn">Better match elsewhere: ${esc([b.authors, b.year].filter(Boolean).join(", "))}: ` +
          `<mark>${esc(b.text)}</mark></div>`;
      }
    });
    html += "</div>";
  });
  html += "</section>";
  if ((report.possibly_missing || []).length) {
    html += `<section class="part"><h3>Possibly missing citations</h3>` + report.possibly_missing.slice(0, 10).map((m) =>
      `<div class="paper"><div class="sentence">${esc(m.sentence)}</div><div class="ref"><span class="meta">${esc(m.paper)}</span> ` +
      `<mark>${esc(m.text)}</mark> <span class="badge">${Math.round(m.similarity * 100)}%</span></div></div>`).join("") + "</section>";
  }
  return html;
}

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", ndash: "–", mdash: "—",
  lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”", hellip: "…", deg: "°", plusmn: "±", times: "×", micro: "µ" };

function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") {
      const code = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code < 0x110000 ? String.fromCodePoint(code) : m;
    }
    return Object.prototype.hasOwnProperty.call(ENTITIES, e.toLowerCase()) ? ENTITIES[e.toLowerCase()] : m;
  });
}

/**
 * Plain text of a Google Doc's 'mobilebasic' HTML: one line per paragraph, heading, list
 * item or table row. No DOM is used (Google Docs pages forbid HTML parsing through
 * Trusted Types, and this also runs in node for the tests).
 */
export function htmlToText(html) {
  let s = String(html || "");
  const start = s.search(/<[^>]+class="[^"]*\bdoc-content\b/);
  if (start > 0) s = s.slice(start);
  s = s.replace(/<(script|style|noscript)\b[\s\S]*?<\/\1>/gi, "");
  // Auto-numbered lists (Format > Numbered list) get their numbers from CSS counters, so
  // write them out: '<ol start="12"><li>' -> '12. '. Docs splits one list into several
  // <ol start=N> elements, hence the start attribute.
  const lists = [];
  s = s.replace(/<(\/?)(ol|ul|li)\b([^>]*)>/gi, (m, close, tag, attrs) => {
    tag = tag.toLowerCase();
    if (tag === "li") {
      if (close) return "\n";
      const top = lists[lists.length - 1];
      return top && top.ordered ? `\n${top.n++}. ` : "\n";
    }
    if (close) { lists.pop(); return "\n"; }
    const start = /\bstart\s*=\s*"?(\d+)/i.exec(attrs);
    lists.push({ ordered: tag === "ol", n: start ? parseInt(start[1], 10) : 1 });
    return "\n";
  });
  s = s.replace(/<br\s*\/?>/gi, "\n");
  s = s.replace(/<\/(p|h[1-6]|li|tr|div|title)>/gi, "\n");
  s = s.replace(/<\/t[dh]>/gi, "\t");
  s = s.replace(/<[^>]*>/g, "");
  s = decodeEntities(s);
  return s.split("\n").map((l) => l.replace(/[ \t ]+/g, " ").trim()).filter(Boolean).join("\n");
}

export function docMobilePath(docId) {
  return `/document/d/${encodeURIComponent(docId)}/mobilebasic`;
}

/** True when a fetched 'mobilebasic' page is the document (not a sign-in or access page). */
export function looksLikeDocHtml(html) {
  return /class="[^"]*\bdoc-content\b/.test(String(html || ""));
}
