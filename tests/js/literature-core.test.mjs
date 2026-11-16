import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const L = require("../../frontend_module/literature-core.js");

const butlin = { hash_id: "h1", title: "Consciousness in Artificial Intelligence", authors: ["Patrick Butlin", "Robert Long"],
  year: "2023", doi: "10.48550/arXiv.2308.08708", arxiv_id: "2308.08708", journal: "arXiv" };

test("BibTeX keys and entries match the Python CitationManager", () => {
  assert.equal(L.bibKey(butlin), "butlin2023consciousness");
  const entry = L.bibEntry(butlin, "butlin2023consciousness");
  assert.match(entry, /^@misc\{butlin2023consciousness,/);
  assert.match(entry, /author = \{Patrick Butlin and Robert Long\}/);
  assert.match(entry, /eprint = \{2308\.08708\}/);
  assert.match(entry, /title = \{\{Consciousness in Artificial Intelligence\}\}/);
});

test("addToBib never duplicates a paper and makes keys unique", () => {
  let r = L.addToBib("", butlin);
  assert.ok(r.added);
  const again = L.addToBib(r.content, { ...butlin });
  assert.equal(again.added, false);
  assert.equal(again.key, "butlin2023consciousness");
  const other = L.addToBib(r.content, { title: "Consciousness and machines", authors: "Patrick Butlin", year: "2023" });
  assert.equal(other.key, "butlin2023consciousnessa");
  assert.equal((other.content.match(/^@/gm) || []).length, 2);
});

test("journal articles are @article with an escaped journal name", () => {
  const e = L.bibEntry({ title: "A construct-first approach", authors: "Peter Fazekas", year: "2024",
    journal: "Neuroscience & Biobehavioral Reviews", doi: "10.1016/x" }, "k");
  assert.match(e, /^@article\{k,/);
  assert.match(e, /journal = \{Neuroscience \\& Biobehavioral Reviews\}/);
});

test("word search ranks title matches first", () => {
  const papers = [
    { hash_id: "a", title: "Deep learning and the global workspace theory", summary: "", keywords: [] },
    { hash_id: "b", title: "Integrated information theory", summary: "mentions workspace once", keywords: [] },
  ];
  const hits = L.wordSearch(papers, "workspace");
  assert.deepEqual(hits.map((h) => h.paper.hash_id), ["a", "b"]);
});

test("results from several sources are merged and matched to the library", () => {
  const a = { ...L.emptyCandidate("openalex"), title: "Consciousness in Artificial Intelligence", doi: "10.48550/arxiv.2308.08708" };
  const b = { ...L.emptyCandidate("crossref"), title: "Consciousness in artificial intelligence", citation_count: 900 };
  const merged = L.mergeRanked([[a], [b]]);
  assert.equal(merged.length, 1);
  assert.deepEqual(merged[0].sources, ["openalex", "crossref"]);
  assert.equal(L.matchLibrary(merged[0], [butlin]), "h1");
});

test("OpenAlex records are parsed like the Python client", () => {
  const c = L.parseOpenAlex({
    display_name: "Looking Inward", publication_year: 2024, doi: "https://doi.org/10.48550/arxiv.2410.13787",
    authorships: [{ author: { display_name: "Felix Binder" } }], abstract_inverted_index: { Humans: [0], introspect: [1] },
    primary_location: { source: { display_name: "arXiv" } }, cited_by_count: 5,
  });
  assert.equal(c.arxiv_id, "2410.13787");
  assert.equal(c.abstract, "Humans introspect");
  assert.equal(c.pdf_url, "https://arxiv.org/pdf/2410.13787");
});

test("query terms skip generic words", () => {
  const t = L.extractQueryTerms("Recent interpretability work suggests that language models maintain a small set of verbalizable representations that behave like a global workspace.");
  assert.ok(t.includes("verbalizable") && t.includes("workspace"));
  assert.ok(!t.includes("maintain") && !t.includes("small"));
});
