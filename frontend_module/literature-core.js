// literature-core.js — JavaScript ports of the Python helpers the phone needs without a
// server (no DOM; also loaded by Node tests):
//  - citation_module/citation_manager.py  → bibKey / bibEntry / addToBib
//  - discovery_module/discover.py         → normalizeArxivId, mergeRanked, extractQueryTerms,
//                                            parseOpenAlex, parseCrossref, matchLibrary
//  - search_module (word frequency)       → wordSearch over titles, abstracts and keywords
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LiteratureCore = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------------ text helpers
  const STOPWORDS = new Set(("the and for with from this that which was were been have has are not but also their they our " +
    "your will can should would could about than then them these those such into only other some more most very both each " +
    "any all another while where when who how why what after before during between under over through above below once " +
    "here there using used use study research results analysis data methods method paper article system based approach " +
    "model provide shown figure table however therefore thus may might one two three first second new work well many much " +
    "different example show shows given within without whether like even way make made take number case cases section " +
    "being had does did because since still just rather often less among models systems large learning recent recently " +
    "suggest suggests maintain behave small sets find found propose present argue important several various allow remain " +
    "current currently known need including include possible able high higher low lower level kind like makes seem evidence " +
    "question role").split(/\s+/));
  const WORD_RE = /[a-zà-öø-ÿ]{3,}/g;

  function asciiFold(s) {
    return String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "");
  }
  function normTitle(t) {
    return asciiFold(t).toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean).join(" ");
  }
  function normDoi(d) {
    return String(d || "").toLowerCase().replace("https://doi.org/", "").trim();
  }
  function normalizeArxivId(v) {
    if (!v) return "";
    const s = String(v);
    let m = s.match(/10\.48550\/arxiv\.(\S+)/i);
    const target = m ? m[1] : s;
    m = target.match(/(?<![\d.])(\d{4}\.\d{4,5})(v\d+)?(?!\d)/);
    return m ? m[1] : "";
  }

  // ------------------------------------------------------------------ BibTeX
  const TITLE_STOP = new Set(["a", "an", "the", "on", "of", "in", "for", "and", "to", "towards", "toward", "from",
    "with", "is", "are", "can", "do", "does", "how", "what", "why"]);
  const LATEX_ESC = { "&": "\\&", "%": "\\%", $: "\\$", "#": "\\#", _: "\\_" };
  const escTex = (t) => String(t || "").split(/\s+/).filter(Boolean).join(" ").replace(/[&%$#_]/g, (c) => LATEX_ESC[c]);

  function authorList(a) {
    if (Array.isArray(a)) return a.map((x) => String(x).trim()).filter(Boolean);
    const s = String(a || "");
    return s.split(s.includes(";") ? ";" : ",").map((x) => x.trim()).filter(Boolean);
  }
  function lastName(author) {
    if (author.includes(",")) return author.split(",")[0].trim();
    const parts = author.split(/\s+/);
    return parts[parts.length - 1] || "";
  }

  /** Same scheme as the Python CitationManager: butlin2023consciousness (+a, b…). */
  function bibKey(meta, existing = new Set()) {
    const authors = authorList(meta.authors);
    const last = authors.length ? asciiFold(lastName(authors[0])).toLowerCase().replace(/[^a-z]/g, "") : "";
    const year = /^\d{4}$/.test(String(meta.year || "")) ? String(meta.year) : "";
    const words = (asciiFold(meta.title || "").toLowerCase().match(/[a-z]+/g) || [])
      .filter((w) => !TITLE_STOP.has(w) && w.length > 2);
    const base = `${last || "anon"}${year}${words[0] || "ref"}`;
    let key = base;
    let i = 0;
    const letters = "abcdefghijklmnopqrstuvwxyz";
    while (existing.has(key)) {
      key = base + letters[i % 26].repeat(1 + Math.floor(i / 26));
      i++;
    }
    return key;
  }

  function bibEntry(meta, key) {
    const authors = authorList(meta.authors);
    const arxiv = meta.arxiv_id || normalizeArxivId(meta.doi || "");
    const journal = meta.journal || "";
    const f = { title: `{${escTex(meta.title || "Unknown Title")}}` };
    if (authors.length) f.author = authors.map(escTex).join(" and ");
    if (/^\d{4}$/.test(String(meta.year || ""))) f.year = String(meta.year);
    if (meta.doi) f.doi = meta.doi;
    let type = "article";
    if (arxiv && (!journal || journal.toLowerCase() === "arxiv")) {
      type = "misc";
      f.eprint = arxiv;
      f.archiveprefix = "arXiv";
      f.howpublished = `arXiv preprint arXiv:${arxiv}`;
    } else if (journal) {
      f.journal = escTex(journal);
    }
    const kws = Array.isArray(meta.keywords) ? meta.keywords.join(", ") : meta.keywords;
    if (kws) f.keywords = kws;
    if (meta.hash_id) f.library_hash = meta.hash_id;
    const body = Object.keys(f).sort().map((k) => `  ${k} = {${f[k]}}`).join(",\n");
    return `@${type}{${key},\n${body}\n}\n`;
  }

  /** Add a paper to BibTeX text. Returns {content, key, added}. Never duplicates a paper. */
  function addToBib(bibText, meta) {
    const text = bibText || "";
    const entries = text.split(/(?=^@)/m);
    const doi = normDoi(meta.doi);
    const arxiv = meta.arxiv_id || normalizeArxivId(meta.doi || "");
    for (const e of entries) {
      const key = (e.match(/^@\w+\{([^,\s]+),/) || [])[1];
      if (!key) continue;
      const field = (name) => ((e.match(new RegExp(`\\b${name}\\s*=\\s*\\{([^}]*)\\}`, "i")) || [])[1] || "").trim();
      if ((meta.hash_id && field("library_hash") === meta.hash_id) || (doi && normDoi(field("doi")) === doi) ||
          (arxiv && field("eprint") === arxiv)) {
        return { content: text, key, added: false };
      }
    }
    const keys = new Set((text.match(/^@\w+\{([^,\s]+),/gm) || []).map((m) => m.replace(/^@\w+\{/, "").replace(/,$/, "")));
    const key = bibKey(meta, keys);
    const sep = text && !text.endsWith("\n\n") ? (text.endsWith("\n") ? "\n" : "\n\n") : "";
    return { content: text + sep + bibEntry(meta, key), key, added: true };
  }

  // ------------------------------------------------------------------ search helpers
  function extractQueryTerms(text, n = 6) {
    const counts = new Map();
    for (const w of (asciiFold(text).toLowerCase().match(WORD_RE) || [])) {
      if (w.length > 3 && !STOPWORDS.has(w)) counts.set(w, (counts.get(w) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length).slice(0, n).map((e) => e[0]);
  }

  /** Word search over the library index (title ×3, keywords ×2, abstract ×1). */
  function wordSearch(papers, query, limit = 50) {
    const terms = (asciiFold(query).toLowerCase().match(WORD_RE) || []).filter((t) => !STOPWORDS.has(t));
    if (!terms.length) return [];
    const scored = [];
    for (const p of papers) {
      const title = asciiFold(p.title).toLowerCase();
      const kw = asciiFold([].concat(p.keywords || []).join(" ")).toLowerCase();
      const abs = asciiFold(p.summary).toLowerCase();
      let score = 0;
      let matched = 0;
      for (const t of terms) {
        const count = (s) => (s.match(new RegExp(`\\b${t}`, "g")) || []).length;
        const s = 3 * count(title) + 2 * count(kw) + count(abs);
        if (s) matched++;
        score += s;
      }
      if (score) scored.push({ paper: p, score: score * (matched / terms.length) });
    }
    return scored.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  // ------------------------------------------------------------------ external results
  function emptyCandidate(source) {
    return { title: "", authors: [], year: "", abstract: "", doi: "", arxiv_id: "", venue: "", url: "",
      pdf_url: "", citation_count: null, source };
  }

  function abstractFromIndex(inv) {
    if (!inv) return "";
    const words = [];
    for (const [w, pos] of Object.entries(inv)) for (const p of pos) words.push([p, w]);
    return words.sort((a, b) => a[0] - b[0]).map((x) => x[1]).join(" ");
  }

  function parseOpenAlex(w, source = "openalex") {
    const c = emptyCandidate(source);
    c.title = w.display_name || w.title || "";
    c.authors = (w.authorships || []).map((a) => (a.author || {}).display_name || "").filter(Boolean);
    c.year = String(w.publication_year || "");
    c.abstract = abstractFromIndex(w.abstract_inverted_index);
    const doi = (w.doi || "").replace("https://doi.org/", "");
    c.doi = doi;
    c.arxiv_id = /arxiv/i.test(doi) ? normalizeArxivId(doi) : "";
    for (const loc of w.locations || []) {
      if (!c.arxiv_id && /arxiv\.org/.test(loc.landing_page_url || "")) c.arxiv_id = normalizeArxivId(loc.landing_page_url);
    }
    c.venue = ((w.primary_location || {}).source || {}).display_name || "";
    c.url = c.doi ? `https://doi.org/${c.doi}` : (w.id || "");
    c.pdf_url = (w.best_oa_location || {}).pdf_url || (c.arxiv_id ? `https://arxiv.org/pdf/${c.arxiv_id}` : "");
    c.citation_count = w.cited_by_count ?? null;
    c.related_works = (w.related_works || []).map((r) => r.split("/").pop());
    return c;
  }

  function parseCrossref(item) {
    const c = emptyCandidate("crossref");
    c.title = (item.title || [""])[0] || "";
    c.authors = (item.author || []).map((a) => `${a.given || ""} ${a.family || ""}`.trim()).filter(Boolean);
    const parts = ((item.issued || {})["date-parts"] || [[null]])[0];
    c.year = parts && parts[0] ? String(parts[0]) : "";
    c.abstract = String(item.abstract || "").replace(/<[^>]+>/g, "").trim();
    c.doi = item.DOI || "";
    c.venue = (item["container-title"] || [""])[0] || "";
    c.url = c.doi ? `https://doi.org/${c.doi}` : "";
    c.citation_count = item["is-referenced-by-count"] ?? null;
    return c;
  }

  function resultKey(c) {
    const ax = normalizeArxivId(c.arxiv_id) || (/arxiv/i.test(c.doi || "") ? normalizeArxivId(c.doi) : "");
    if (ax) return `arxiv:${ax}`;
    if (c.doi) return `doi:${normDoi(c.doi)}`;
    return `title:${normTitle(c.title).slice(0, 120)}`;
  }

  /** Deduplicate across sources and rank by reciprocal-rank fusion (as in discover.py). */
  function mergeRanked(lists, k = 60) {
    const merged = new Map();
    const alias = new Map();
    for (const list of lists) {
      (list || []).forEach((c, rank) => {
        if (!c.title) return;
        const t = normTitle(c.title).slice(0, 120);
        const key = alias.get(t) || resultKey(c);
        if (!alias.has(t)) alias.set(t, key);
        if (!merged.has(key)) merged.set(key, { ...c, sources: [c.source], score: 0 });
        else {
          const m = merged.get(key);
          for (const [f, v] of Object.entries(c)) {
            if (!["source", "score", "sources"].includes(f) && v && !(m[f] && (!Array.isArray(m[f]) || m[f].length))) m[f] = v;
          }
          if (!m.sources.includes(c.source)) m.sources.push(c.source);
        }
        merged.get(key).score += 1 / (k + rank + 1);
      });
    }
    const out = [...merged.values()];
    for (const m of out) {
      m.score = Math.round((m.score * 100 + 0.05 * Math.log1p(m.citation_count || 0)) * 1e4) / 1e4;
      delete m.related_works;
    }
    return out.sort((a, b) => b.score - a.score);
  }

  function matchLibrary(c, papers) {
    const doi = normDoi(c.doi);
    const ax = normalizeArxivId(c.arxiv_id) || (/arxiv/i.test(doi) ? normalizeArxivId(doi) : "");
    const t = normTitle(c.title);
    for (const p of papers || []) {
      if ((doi && normDoi(p.doi) === doi) || (ax && (p.arxiv_id === ax || normalizeArxivId(p.doi) === ax)) ||
          (t && normTitle(p.title) === t)) return p.hash_id;
    }
    return "";
  }

  return {
    normalizeArxivId, normTitle, bibKey, bibEntry, addToBib, extractQueryTerms, wordSearch,
    parseOpenAlex, parseCrossref, mergeRanked, matchLibrary, emptyCandidate,
  };
});
