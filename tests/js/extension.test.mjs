// Tests of the Chrome extension's shared logic (browser_extension/lib.js).
import test from "node:test";
import assert from "node:assert/strict";
import { api, docIdFromUrl, esc, htmlToText, normalizeServer, renderAudit, renderEvidence }
  from "../../browser_extension/lib.js";

test("only local servers are accepted", () => {
  assert.equal(normalizeServer(""), "http://127.0.0.1:8000");
  assert.equal(normalizeServer("localhost:8001/"), "http://localhost:8001");
  assert.equal(normalizeServer("http://127.0.0.1:8000/ui"), "http://127.0.0.1:8000");
  assert.throws(() => normalizeServer("https://example.com"), /this computer/);
  assert.throws(() => normalizeServer("http://127.0.0.1.evil.com"), /this computer/);
});

test("Google Doc ids", () => {
  assert.equal(docIdFromUrl("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit?tab=t.0"),
    "1AbCdEfGhIjKlMnOpQrStUvWxYz012345");
  assert.equal(docIdFromUrl("https://docs.google.com/document/u/1/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit"),
    "1AbCdEfGhIjKlMnOpQrStUvWxYz012345");
  assert.equal(docIdFromUrl("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit"), null);
  assert.equal(docIdFromUrl("https://evil.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345"), null);
});

test("Docs mobilebasic HTML to text keeps glued citation numbers and paragraphs", () => {
  const html = '<html><head><style>.c1{vertical-align:super}</style><script>var x="<p>no</p>"</script></head>' +
    '<body><div class="doc-content"><p class="c2"><span>Wetlands store carbon in peat,</span><span class="c1">12</span>' +
    '<span> and silt&nbsp;&amp; sand.</span></p><h2>References</h2><p>12. Smith, A. (2001). Peat &#8211; carbon. ' +
    'https://doi.org/10.5555/x.12</p><table><tr><td>a</td><td>b</td></tr></table></div></body></html>';
  assert.equal(htmlToText(html),
    "Wetlands store carbon in peat,12 and silt & sand.\nReferences\n12. Smith, A. (2001). Peat – carbon. https://doi.org/10.5555/x.12\na b");
});

test("api reports server errors, wrong passwords and unreachable servers", async () => {
  const ok = async () => ({ ok: true, status: 200, json: async () => ({ projects: ["p"] }) });
  assert.deepEqual(await api("http://127.0.0.1:8000", "t", "/api/projects", { fetchImpl: ok }), { projects: ["p"] });
  const denied = async () => ({ ok: false, status: 403, json: async () => ({ detail: "Invalid" }) });
  await assert.rejects(api("http://x", "t", "/a", { fetchImpl: denied }), /password/);
  const err = async () => ({ ok: false, status: 422, json: async () => ({ detail: "Select at least a few words" }) });
  await assert.rejects(api("http://x", "t", "/a", { fetchImpl: err }), /few words/);
  const down = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(api("http://x", "t", "/a", { fetchImpl: down }), /Is it running/);
  let sent;
  const spy = async (url, opts) => { sent = { url, opts }; return { ok: true, status: 200, json: async () => ({}) }; };
  await api("http://x", "secret", "/b", { method: "POST", body: { a: 1 }, fetchImpl: spy });
  assert.equal(sent.url, "http://x/b");
  assert.equal(sent.opts.headers["x-auth-token"], "secret");
  assert.equal(sent.opts.body, '{"a":1}');
});

const passage = (text, sim) => ({ text, page: 3, similarity: sim, before: "<b>ctx</b>", after: "" });

test("evidence rendering: escaped, cited first, at most 3 other papers, groups for the AI check", () => {
  const papers = [
    { hash_id: "a", title: "<img src=x onerror=alert(1)>", authors: "Smith", year: "2001", cited: false, passages: [passage("one", 0.7)] },
    { hash_id: "b", title: "Cited paper", authors: "Jones", year: "1999", cited: true, passages: [passage("two", 0.5)] },
    ...["c", "d", "e", "f"].map((h) => ({ hash_id: h, title: h, cited: false, passages: [passage(h, 0.4)] })),
  ];
  const data = { claim: "x", parts: [{ claim: "feature alpha", cites: "12", papers,
    unresolved: [{ label: "13", reference: "Okafor (1992) <script>" }] }], not_indexed: ["z"] };
  const groups = [];
  const html = renderEvidence(data, groups);
  assert.ok(!html.includes("<img") && html.includes("&lt;img") && !html.includes("<script>") && !html.includes("<b>ctx"));
  assert.ok(html.indexOf("Cited paper") < html.indexOf("&lt;img"));
  assert.equal(groups.length, 1);
  assert.equal(groups[0].passages.length, 4);                   // 1 cited + 3 others
  assert.equal(groups[0].passages[0].hash_id, "b");
  assert.match(html, /Reference 13 is not among/);
  assert.match(html, /still being indexed/);
  assert.match(html, /data-pdf="b" data-page="3"/);
});

test("audit rendering lists DOI problems and missing references", () => {
  const report = {
    source: "My <doc>", summary: { citing_sentences: 2, references: 3, references_in_project: 1,
      uncited_references: ["3"], citation_numbers_without_reference: ["9"] },
    references: [
      { n: "1", doi: "10.5555/a", in_project: "h", cited_in: [0], doi_check: { status: "ok" }, reference: "" },
      { n: "2", doi: "10.5555/b", in_project: null, cited_in: [1], reference: "Jones",
        doi_check: { status: "mismatch", problems: ["title differs"], crossref: { title: "Other", first_author: "Kim", year: 2003 } } },
      { n: "3", doi: "", in_project: null, cited_in: [], doi_check: { status: "no_doi" }, reference: "" },
    ],
    citations: [{ sentence: "S <i>", parts: [{ cites: "1", claim: "c", refs: [
      { status: "in_project", authors: "Smith", year: "2001", best_sentences: [{ text: "match", similarity: 0.61, page: 2 }] },
      { status: "not_in_project", label: "2" }],
      better_match_elsewhere: { authors: "Lee", year: "2010", text: "better" } }] }],
    possibly_missing: [{ sentence: "uncited", paper: "P", text: "t", similarity: 0.7 }],
  };
  const html = renderAudit(report);
  assert.match(html, /DOI problems/);
  assert.match(html, /Ref\. 2: 10\.5555\/b/);
  assert.match(html, /title differs/);
  assert.match(html, /References not in the project[\s\S]*2, 3/);
  assert.match(html, /Never cited: 3/);
  assert.match(html, /missing from the reference list: 9/);
  assert.match(html, /Better match elsewhere/);
  assert.match(html, /Possibly missing citations/);
  assert.ok(!html.includes("<doc>") && !html.includes("S <i>"));
  assert.equal(esc(`<"'&>`), "&lt;&quot;&#39;&amp;&gt;");
});

test("account-specific Doc paths and access pages", async () => {
  const { docMobilePathFromUrl, looksLikeDocHtml } = await import("../../browser_extension/lib.js");
  const id = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345";
  assert.equal(docMobilePathFromUrl(`https://docs.google.com/document/d/${id}/edit?tab=t.0`), `/document/d/${id}/mobilebasic`);
  assert.equal(docMobilePathFromUrl(`https://docs.google.com/document/u/1/d/${id}/edit`), `/document/u/1/d/${id}/mobilebasic`);
  assert.equal(docMobilePathFromUrl("https://example.com/"), null);
  assert.ok(looksLikeDocHtml('<div class="x doc-content">'));
  assert.ok(!looksLikeDocHtml("<html><body>You need access</body></html>"));
});

test("auto-numbered lists keep their numbers, including continued lists", () => {
  const html = '<div class="doc-content"><h2>References</h2>' +
    '<ol class="lst-kix_a start" start="1"><li class="c1"><span>Smith A. Peat. https://doi.org/10.5555/x.1</span></li>' +
    '<li><span>Jones B. Silt.</span></li></ol><p>Note between</p>' +
    '<ol class="lst-kix_a" start="3"><li><span>Lopez C. Reeds.</span></li></ol>' +
    '<ul><li>bullet</li></ul></div>';
  assert.equal(htmlToText(html),
    "References\n1. Smith A. Peat. https://doi.org/10.5555/x.1\n2. Jones B. Silt.\nNote between\n3. Lopez C. Reeds.\nbullet");
});
