const CONFIG = {
  API_BASE: window.location.origin,
  AUTH_TOKEN:
    new URLSearchParams(window.location.search).get("token") ||
    "vibe-coding-secret",
};

// Store token in session storage for persistence if provided in URL
if (new URLSearchParams(window.location.search).get("token")) {
  sessionStorage.setItem("auth_token", CONFIG.AUTH_TOKEN);
} else if (sessionStorage.getItem("auth_token")) {
  CONFIG.AUTH_TOKEN = sessionStorage.getItem("auth_token");
}

const state = {
  activeProject: null, // currently selected project name
  activeFile: "draft", // 'draft' | 'bib'
  currentContent: "",
  results: [],
  libraryData: [],
  debounceTimer: null,
  saveTimer: null,
  view: "editor", // 'editor' | 'graph' | 'library' | 'chat'
  searchMethod: "filter", // 'filter' | 'semantic' | 'bow'
  simulation: null,
  isMobile: window.innerWidth <= 768,
};

// --- DOM Elements ---
const editor = document.getElementById("latex-editor");
const resultsContainer = document.getElementById("results-container");
const pdfModal = document.getElementById("pdf-modal");
const pdfFrame = document.getElementById("pdf-frame");
const closePdfModal = document.getElementById("close-pdf-modal");
const textModal = document.getElementById("text-modal");
const closeTextModal = document.getElementById("close-text-modal");
const textModalTitle = document.getElementById("text-modal-title");
const textModalBody = document.getElementById("text-modal-body");
const graphModal = document.getElementById("graph-modal");
const graphFrame = document.getElementById("graph-frame");
const closeGraphModal = document.getElementById("close-graph-modal");
const saveStatus = document.getElementById("save-status");
const currentFilename = document.getElementById("current-filename");

const btnEditor = document.getElementById("btn-editor");
const btnGraph = document.getElementById("btn-graph");
const editorWorkspace = document.getElementById("editor-workspace");
const graphWorkspace = document.getElementById("graph-workspace");

const projectSelect = document.getElementById("project-select");
const btnNewProject = document.getElementById("btn-new-project");
const btnDeleteProject = document.getElementById("btn-delete-project");
const newProjectModal = document.getElementById("new-project-modal");
const newProjectName = document.getElementById("new-project-name");
const btnCreateProject = document.getElementById("btn-create-project");
const btnCancelProject = document.getElementById("btn-cancel-project");
const fileListItems = document.querySelectorAll("#file-list .nav-item");

// Chat & Library UI Elements
const tabLibrary = document.getElementById("tab-library");
const tabMatches = document.getElementById("tab-matches");
const libraryContainer = document.getElementById("library-container");
const librarySearchInput = document.getElementById("library-search-input");
const libraryFilterYear = document.getElementById("library-filter-year");
const libraryFilterAuthor = document.getElementById("library-filter-author");
const libraryFilterJournal = document.getElementById("library-filter-journal");
const libraryList = document.getElementById("library-list");
const btnSearchFilter = document.getElementById("btn-search-filter");
const btnSearchSemantic = document.getElementById("btn-search-semantic");
const btnSearchFreq = document.getElementById("btn-search-freq");

// Mobile UI Elements
const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const sidebar = document.querySelector(".sidebar");
const sidePanel = document.querySelector(".side-panel");
const mobileNavItems = document.querySelectorAll(".mobile-nav-item");

// --- Auth Helper ---
const authHeaders = () => ({
  "Content-Type": "application/json",
  "x-auth-token": CONFIG.AUTH_TOKEN,
});

// =============================================================================
// INITIALIZATION
// =============================================================================

async function init() {
  // Wire up view toggle
  btnEditor.addEventListener("click", () => switchView("editor"));
  btnGraph.addEventListener("click", () => switchView("graph"));

  // Wire up modal close
  if (closePdfModal) {
    closePdfModal.addEventListener("click", () => {
      pdfModal.style.display = "none";
      pdfFrame.src = "";
    });
  }

  if (closeTextModal) {
    closeTextModal.addEventListener("click", () => {
      textModal.style.display = "none";
      textModalBody.textContent = "";
    });
  }

  if (closeGraphModal) {
    closeGraphModal.addEventListener("click", () => {
      graphModal.style.display = "none";
      graphFrame.src = "";
    });
  }

  // Wire up global escape key for modals
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (pdfModal && pdfModal.style.display === "flex") {
        pdfModal.style.display = "none";
        pdfFrame.src = "";
      }
      if (textModal && textModal.style.display === "flex") {
        textModal.style.display = "none";
        textModalBody.textContent = "";
      }
      if (graphModal && graphModal.style.display === "flex") {
        graphModal.style.display = "none";
        graphFrame.src = "";
      }
      if (newProjectModal && !newProjectModal.classList.contains("hidden")) {
        hideNewProjectModal();
      }
    }
  });

  // Wire up editor events
  editor.addEventListener("input", handleInput);
  editor.addEventListener("mouseup", handleHighlight);
  editor.addEventListener("keyup", handleHighlight);
  document.addEventListener("selectionchange", () => {
    // Only trigger if focus is in editor or if on mobile
    if (document.activeElement === editor || state.isMobile) {
      handleHighlight();
    }
  });

  // Wire up project controls
  projectSelect.addEventListener("change", () =>
    switchProject(projectSelect.value),
  );
  btnNewProject.addEventListener("click", showNewProjectModal);
  btnCancelProject.addEventListener("click", hideNewProjectModal);
  btnCreateProject.addEventListener("click", createProject);
  newProjectName.addEventListener("keydown", (e) => {
    if (e.key === "Enter") createProject();
  });
  newProjectName.addEventListener("input", (e) => {
    const isEmpty = !e.target.value.trim();
    btnCreateProject.disabled = isEmpty;
    btnCreateProject.title = isEmpty
      ? "Type a project name to create"
      : "Create project";
  });
  btnDeleteProject.addEventListener("click", deleteProject);

  // Wire up file tab clicks
  fileListItems.forEach((item) => {
    item.addEventListener("click", () => {
      fileListItems.forEach((i) => i.classList.remove("active"));
      item.classList.add("active");
      state.activeFile = item.dataset.file;
      loadCurrentFile();
    });

    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        item.click();
      }
    });
  });

  // Load project list
  await loadProjects();

  // Wire up Side Panel Tabs
  if (tabLibrary && tabMatches) {
    tabLibrary.addEventListener("click", () => {
      switchSidePanel("library");
      librarySearchInput.focus();
    });
    tabMatches.addEventListener("click", () => switchSidePanel("matches"));

    librarySearchInput.addEventListener("input", handleLibrarySearch);
    if (libraryFilterYear)
      libraryFilterYear.addEventListener("input", handleLibrarySearch);
    if (libraryFilterAuthor)
      libraryFilterAuthor.addEventListener("input", handleLibrarySearch);
    if (libraryFilterJournal)
      libraryFilterJournal.addEventListener("input", handleLibrarySearch);

    // Zotero-like Keyboard Shortcut (Cmd+K or Ctrl+K)
    window.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        switchSidePanel("library");
        librarySearchInput.focus();
      }
    });

    if (btnSearchFilter && btnSearchSemantic && btnSearchFreq) {
      const updateMode = (method) => {
        state.searchMethod = method;
        [btnSearchFilter, btnSearchSemantic, btnSearchFreq].forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        if (method === "filter") {
          btnSearchFilter.classList.add("active");
          btnSearchFilter.setAttribute("aria-pressed", "true");
        }
        if (method === "semantic") {
          btnSearchSemantic.classList.add("active");
          btnSearchSemantic.setAttribute("aria-pressed", "true");
        }
        if (method === "bow") {
          btnSearchFreq.classList.add("active");
          btnSearchFreq.setAttribute("aria-pressed", "true");
        }

        // Trigger search with current input
        handleLibrarySearch({ target: librarySearchInput });
      };

      btnSearchFilter.addEventListener("click", () => updateMode("filter"));
      btnSearchSemantic.addEventListener("click", () => updateMode("semantic"));
      btnSearchFreq.addEventListener("click", () => updateMode("bow"));
    }
  }

  // Load Library data
  await loadLibrary();

  // Mobile specific initialization
  initMobileUI();

  window.addEventListener("resize", () => {
    state.isMobile = window.innerWidth <= 768;
    if (!state.isMobile) {
      // Reset mobile-specific styles if we resize back to desktop
      sidebar.classList.remove("show");
      sidebarOverlay.classList.remove("show");
      sidePanel.classList.remove("mobile-active");
    }
  });

  console.log("Research Assistant — Multi-Project UI initialized");
}

function initMobileUI() {
  if (btnToggleSidebar) {
    btnToggleSidebar.addEventListener("click", () => {
      sidebar.classList.toggle("show");
      sidebarOverlay.classList.toggle("show");
    });
  }

  if (sidebarOverlay) {
    sidebarOverlay.addEventListener("click", () => {
      sidebar.classList.remove("show");
      sidebarOverlay.classList.remove("show");
    });
  }

  mobileNavItems.forEach((item) => {
    item.addEventListener("click", () => {
      const view = item.dataset.view;
      switchMobileView(view);
    });
  });
}

function switchMobileView(view) {
  // Remove active class from all mobile nav items
  mobileNavItems.forEach((i) => i.classList.remove("active"));
  // Add active class to the selected one
  const targetItem = document.querySelector(
    `.mobile-nav-item[data-view="${view}"]`,
  );
  if (targetItem) targetItem.classList.add("active");

  if (view === "editor" || view === "graph") {
    sidePanel.classList.remove("mobile-active");
    switchView(view);
  } else if (view === "library") {
    sidePanel.classList.add("mobile-active");
    switchSidePanel("library");
  } else if (view === "matches") {
    sidePanel.classList.add("mobile-active");
    switchSidePanel("matches");
  }
}

function switchSidePanel(tab) {
  [tabLibrary, tabMatches].forEach((t) => {
    t.classList.remove("active");
    t.setAttribute("aria-selected", "false");
  });
  [libraryContainer, resultsContainer].forEach((c) => {
    c.classList.remove("active-content");
    c.style.display = "none";
  });

  if (tab === "library") {
    tabLibrary.classList.add("active");
    tabLibrary.setAttribute("aria-selected", "true");
    libraryContainer.classList.add("active-content");
    libraryContainer.style.display = "block";
    if (state.isMobile) {
      // Ensure mobile nav is synced
      mobileNavItems.forEach((i) => i.classList.remove("active"));
      const btnLib = document.getElementById("mobile-btn-library");
      if (btnLib) btnLib.classList.add("active");
    }
  } else if (tab === "matches") {
    tabMatches.classList.add("active");
    tabMatches.setAttribute("aria-selected", "true");
    resultsContainer.classList.add("active-content");
    resultsContainer.style.display = "block";
    if (state.isMobile) {
      mobileNavItems.forEach((i) => i.classList.remove("active"));
      const btnMatches = document.getElementById("mobile-btn-matches");
      if (btnMatches) btnMatches.classList.add("active");
    }
  }
}

// =============================================================================
// PROJECT MANAGEMENT
// =============================================================================

async function loadProjects() {
  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/projects`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to list projects");
    const data = await res.json();

    projectSelect.innerHTML = "";
    if (!data.projects || data.projects.length === 0) {
      // No projects — create default
      await createProjectByName("default");
      return loadProjects();
    }

    data.projects.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      projectSelect.appendChild(opt);
    });

    // Restore last-used project from localStorage
    const last = localStorage.getItem("activeProject") || data.projects[0];
    const toSelect = data.projects.includes(last) ? last : data.projects[0];
    projectSelect.value = toSelect;
    await switchProject(toSelect, false); // false = don't prompt unsaved
  } catch (err) {
    console.error("loadProjects error:", err);
  }
}

async function switchProject(name, guardUnsaved = true) {
  if (guardUnsaved && state.activeProject && state.activeProject !== name) {
    // Auto-save before switching
    await saveCurrentFile(true);
  }
  state.activeProject = name;
  localStorage.setItem("activeProject", name);
  await loadCurrentFile();
}

async function loadCurrentFile() {
  if (!state.activeProject) return;

  const endpoint =
    state.activeFile === "draft"
      ? `/api/projects/${state.activeProject}/draft`
      : `/api/projects/${state.activeProject}/bib`;

  const ext = state.activeFile === "draft" ? "draft.tex" : "references.bib";
  currentFilename.textContent = `${state.activeProject} / ${ext}`;

  try {
    const res = await fetch(`${CONFIG.API_BASE}${endpoint}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to load ${state.activeFile}`);
    const data = await res.json();
    editor.value = data.content;
    state.currentContent = data.content;
    setSaveStatus("Saved");
  } catch (err) {
    console.error("loadCurrentFile error:", err);
    setSaveStatus("Load error");
  }
}

async function saveCurrentFile(silent = false) {
  if (!state.activeProject || state.activeFile !== "draft") return; // only auto-save .tex
  if (!silent) setSaveStatus("Saving…");

  try {
    const res = await fetch(
      `${CONFIG.API_BASE}/api/projects/${state.activeProject}/draft`,
      {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ content: editor.value }),
      },
    );
    if (res.ok) {
      state.currentContent = editor.value;
      setSaveStatus("Saved");
    } else {
      setSaveStatus("Save failed");
    }
  } catch (err) {
    console.error("saveCurrentFile error:", err);
    setSaveStatus("Save error");
  }
}

function showNewProjectModal() {
  newProjectModal.classList.remove("hidden");
  newProjectName.value = "";
  btnCreateProject.disabled = true;
  btnCreateProject.title = "Type a project name to create";
  newProjectName.focus();
}

function hideNewProjectModal() {
  newProjectModal.classList.add("hidden");
}

async function createProject() {
  const name = newProjectName.value.trim();
  if (!name) return;

  btnCreateProject.disabled = true;
  newProjectName.disabled = true;
  btnCreateProject.setAttribute("aria-busy", "true");
  newProjectName.setAttribute("aria-busy", "true");
  const originalHTML = btnCreateProject.innerHTML;
  btnCreateProject.innerHTML = "Creating...";

  try {
    await createProjectByName(name);
    hideNewProjectModal();
    await loadProjects();
    projectSelect.value = name;
    await switchProject(name, false);
  } finally {
    const isEmpty = !newProjectName.value.trim();
    btnCreateProject.disabled = isEmpty;
    btnCreateProject.title = isEmpty
      ? "Type a project name to create"
      : "Create project";
    newProjectName.disabled = false;
    btnCreateProject.removeAttribute("aria-busy");
    newProjectName.removeAttribute("aria-busy");
    btnCreateProject.innerHTML = originalHTML;
  }
}

async function createProjectByName(name) {
  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/projects`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ name }),
    });
    if (!res.ok && res.status !== 409) throw new Error("Create project failed");
  } catch (err) {
    console.error("createProjectByName error:", err);
  }
}

async function deleteProject() {
  if (!state.activeProject) return;
  if (
    !confirm(`Delete project "${state.activeProject}"? This cannot be undone.`)
  )
    return;

  btnDeleteProject.disabled = true;
  btnDeleteProject.setAttribute("aria-busy", "true");
  const originalHTML = btnDeleteProject.innerHTML;
  btnDeleteProject.innerHTML = "🗑 Deleting...";

  try {
    const res = await fetch(
      `${CONFIG.API_BASE}/api/projects/${state.activeProject}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      },
    );
    if (!res.ok) throw new Error("Delete failed");
    state.activeProject = null;
    await loadProjects();
  } catch (err) {
    console.error("deleteProject error:", err);
  } finally {
    btnDeleteProject.disabled = false;
    btnDeleteProject.removeAttribute("aria-busy");
    btnDeleteProject.innerHTML = originalHTML;
  }
}

// =============================================================================
// EDITOR EVENTS
// =============================================================================

function handleInput(e) {
  state.currentContent = e.target.value;
  setSaveStatus("Unsaved");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveCurrentFile(), 1500);
}

function handleHighlight() {
  if (state.activeFile !== "draft") return;
  const selectedText = window.getSelection().toString().trim();
  if (selectedText.length > 10) {
    // Prevent searching for the exact same text constantly
    if (state.lastSearchedText === selectedText) return;

    clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(() => {
      state.lastSearchedText = selectedText;
      performSemanticSearch(selectedText);
    }, 500);
  }
}

function setSaveStatus(msg) {
  saveStatus.textContent = msg;
}

// =============================================================================
// VIEW TOGGLE
// =============================================================================

function switchView(view) {
  state.view = view;
  if (view === "editor") {
    editorWorkspace.style.display = "block";
    graphWorkspace.style.display = "none";
    btnEditor.classList.add("active-view");
    btnGraph.classList.remove("active-view");
    btnEditor.setAttribute("aria-selected", "true");
    btnGraph.setAttribute("aria-selected", "false");
    if (state.isMobile) {
      mobileNavItems.forEach((i) => i.classList.remove("active"));
      document.getElementById("mobile-btn-editor").classList.add("active");
    }
  } else {
    editorWorkspace.style.display = "none";
    graphWorkspace.style.display = "block";
    btnEditor.classList.remove("active-view");
    btnGraph.classList.add("active-view");
    btnEditor.setAttribute("aria-selected", "false");
    btnGraph.setAttribute("aria-selected", "true");
    if (state.isMobile) {
      mobileNavItems.forEach((i) => i.classList.remove("active"));
      document.getElementById("mobile-btn-graph").classList.add("active");
    }
    loadGraph();
  }
}

// =============================================================================
// SEMANTIC SEARCH
// =============================================================================

async function performSemanticSearch(query) {
  try {
    const response = await fetch(`${CONFIG.API_BASE}/api/search`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ query: query, n_results: 3 }),
    });
    if (!response.ok) throw new Error("Search failed");
    const results = await response.json();
    renderResults(results);

    // Show a toast if on mobile and matches exist but aren't currently visible
    if (
      state.isMobile &&
      results.length > 0 &&
      (!sidePanel.classList.contains("mobile-active") ||
        !tabMatches.classList.contains("active"))
    ) {
      showToast(
        `Found ${results.length} matches! Tap 'Matches' below to view.`,
        3000,
      );
    }
  } catch (error) {
    console.error("API Error:", error);
  }
}

async function loadLibrary() {
  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/library`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to load library");
    const data = await res.json();
    state.libraryData = data.papers || [];
    renderLibrary(state.libraryData);
  } catch (e) {
    console.error("Library Load Error:", e);
    if (libraryList) {
      libraryList.innerHTML =
        '<div class="text-secondary" style="text-align: center; margin-top: 2rem;">Error loading library.</div>';
    }
  }
}

async function handleLibrarySearch(e) {
  const q = librarySearchInput
    ? librarySearchInput.value.trim().toLowerCase()
    : "";
  const fYear = libraryFilterYear ? libraryFilterYear.value.trim() : "";
  const fAuthor = libraryFilterAuthor
    ? libraryFilterAuthor.value.trim().toLowerCase()
    : "";
  const fJournal = libraryFilterJournal
    ? libraryFilterJournal.value.trim().toLowerCase()
    : "";

  // Clear debounce timer
  if (state.debounceTimer) clearTimeout(state.debounceTimer);

  if (!q && !fYear && !fAuthor && !fJournal) {
    renderLibrary(state.libraryData);
    return;
  }

  if (state.searchMethod === "filter") {
    // Local filtering
    const filtered = state.libraryData.filter((p) => {
      const title = (p.metadata.title || "").toLowerCase();
      const authors = (p.metadata.authors || "").toLowerCase();
      const journal = (p.metadata.journal || "").toLowerCase();
      const year = p.metadata.year ? p.metadata.year.toString() : "";

      const matchQ = !q || title.includes(q) || authors.includes(q);
      const matchYear = !fYear || year === fYear;
      const matchAuthor = !fAuthor || authors.includes(fAuthor);
      const matchJournal = !fJournal || journal.includes(fJournal);

      // Implicit text field filtering logic locally
      let implicitMatch = true;
      if (q) {
        const yearMatch = q.match(/\b(19\d{2}|20\d{2})\b/);
        if (yearMatch && year !== yearMatch[1]) {
          implicitMatch = false;
        }
      }

      return (
        matchQ && matchYear && matchAuthor && matchJournal && implicitMatch
      );
    });
    renderLibrary(filtered);
  } else {
    // Server-side search (Semantic or BOW)
    state.debounceTimer = setTimeout(async () => {
      libraryList.innerHTML =
        '<div class="text-secondary" style="text-align: center; margin-top: 2rem;">Searching server...</div>';
      try {
        const payload = {
          query: q || " ",
          n_results: 50,
          method: state.searchMethod,
        };
        if (fYear) payload.year = parseInt(fYear);
        if (fAuthor) payload.author = fAuthor;
        if (fJournal) payload.journal = fJournal;

        const response = await fetch(`${CONFIG.API_BASE}/api/search`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error("Search failed");
        const results = await response.json();

        // Map results to the library format for rendering
        const papers = results.map((r) => ({
          hash_id: r.hash_id,
          metadata: r.metadata,
          score: r.score,
          method: r.method,
          files: r.files,
        }));
        renderLibrary(papers);
      } catch (error) {
        console.error("Search Error:", error);
        libraryList.innerHTML =
          '<div class="text-secondary" style="text-align: center; margin-top: 2rem;">Search failed.</div>';
      }
    }, 500);
  }
}

function renderLibrary(papers, limit = 50) {
  if (!libraryList) return;

  // Clear the list if we are starting fresh (limit is 50 means first page)
  if (limit === 50) {
    libraryList.innerHTML = "";
  } else {
    // Remove existing load more button before adding more items
    const existingBtn = document.getElementById("load-more-btn");
    if (existingBtn) existingBtn.remove();
  }

  if (papers.length === 0) {
    libraryList.innerHTML = `
      <div class="empty-state" style="text-align: center; padding: 2rem 1rem;">
        <div style="font-size: 2rem; margin-bottom: 1rem;" aria-hidden="true">📄</div>
        <div class="text-secondary" style="margin-bottom: 0.5rem; font-weight: 500;">No papers found</div>
        <div style="font-size: 0.85rem; color: var(--text-secondary); opacity: 0.8;">Adjust your search filters or add new PDFs to your library.</div>
      </div>
    `;
    return;
  }

  const currentDisplay = papers.slice(limit - 50, limit);

  currentDisplay.forEach((p) => {
    const card = document.createElement("div");
    card.className = "result-card library-card";
    card.style.padding = "1rem";
    card.style.marginBottom = "0.75rem";

    const title = p.metadata.title || "Unknown Title";
    const rawAuthors = p.metadata.authors || "";
    const authorList = Array.isArray(rawAuthors)
      ? rawAuthors
      : rawAuthors.split(",");
    const authors =
      authorList.length > 0
        ? authorList.slice(0, 2).join(", ") +
          (authorList.length > 2 ? " et al." : "")
        : "";

    const rawKeywords = p.metadata.keywords || "";
    const keywordList = Array.isArray(rawKeywords)
      ? rawKeywords
      : rawKeywords.split(",");
    const keywords =
      keywordList.length > 0 ? keywordList.slice(0, 3).join(", ") : "";

    const filename = p.metadata.pdf_filename || "";

    // Generate buttons for all available files (Main + Supplements)
    let fileButtons = "";
    if (p.files && p.files.length > 0) {
      fileButtons = p.files
        .map((f, idx) => {
          let label = idx === 0 ? "PDF" : `Supp ${idx}`;
          const lowerName = f.filename.toLowerCase();
          if (lowerName.includes("supp")) label = "Supp";
          if (lowerName.includes("fig")) label = "Figs";

          return `<button class="view-btn" onclick="openPDF('${p.hash_id}', '${f.filename}')" title="${f.filename}">${label}</button>`;
        })
        .join("");
    }

    card.innerHTML = `
            <div class="result-title" style="font-size: 0.95rem; margin-bottom: 0.25rem;">${title}</div>
            ${authors ? `<div style="font-size: 0.8rem; color: var(--accent-color); margin-bottom: 0.5rem;">${authors}</div>` : ""}
            ${keywords ? `<div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.75rem;">🏷 ${keywords}</div>` : ""}
            <div class="result-footer" style="justify-content: flex-end;">
                <div style="display: flex; gap: 0.3rem; flex-wrap: wrap; justify-content: flex-end;">
                    <button class="view-btn" style="background: var(--accent-color); color: white;" onclick="openQuickGraph('${p.hash_id}')">Quick Graph</button>
                    ${fileButtons}
                    <button class="view-btn" onclick="openRawText('${p.hash_id}', '${title.replace(/'/g, "\\'")}')">Text</button>
                    <button class="view-btn" id="bib-btn-lib-${p.hash_id}" onclick="addToBib('${p.hash_id}')" style="background: #3b82f6">Cite</button>
                </div>
            </div>
        `;
    card.addEventListener("dblclick", () => {
      openRawText(p.hash_id, title);
    });

    libraryList.appendChild(card);
  });

  // Add Load More button if there are more papers
  if (papers.length > limit) {
    const loadMoreBtn = document.createElement("button");
    loadMoreBtn.id = "load-more-btn";
    loadMoreBtn.className = "view-btn";
    loadMoreBtn.style.width = "100%";
    loadMoreBtn.style.marginTop = "1rem";
    loadMoreBtn.style.padding = "0.75rem";
    loadMoreBtn.style.background = "rgba(255,255,255,0.05)";
    loadMoreBtn.textContent = `Load More (${papers.length - limit} remaining)`;
    loadMoreBtn.onclick = () => renderLibrary(papers, limit + 50);
    libraryList.appendChild(loadMoreBtn);
  }
}

window.openRawText = async (hash_id, title) => {
  if (!textModal || !textModalBody) return;

  textModalTitle.textContent = title;
  textModalBody.textContent = "Loading raw text...";
  textModal.style.display = "flex";

  try {
    const response = await fetch(
      `${CONFIG.API_BASE}/api/library/text/${hash_id}`,
      { headers: authHeaders() },
    );
    if (!response.ok) throw new Error("Failed to load text");
    const data = await response.json();
    textModalBody.textContent = data.text;
  } catch (e) {
    console.error(e);
    textModalBody.textContent = "Error: Raw text not found or failed to load.";
  }
};

function renderResults(results) {
  resultsContainer.innerHTML = "";
  if (!results || results.length === 0) {
    resultsContainer.innerHTML = `
      <div class="empty-state" style="text-align: center; padding: 2rem 1rem;">
        <div style="font-size: 2rem; margin-bottom: 1rem;" aria-hidden="true">🔍</div>
        <div class="text-secondary" style="margin-bottom: 0.5rem; font-weight: 500;">No matches found</div>
        <div style="font-size: 0.85rem; color: var(--text-secondary); opacity: 0.8;">Try highlighting a different phrase or adding more papers to your library.</div>
      </div>
    `;
    return;
  }

  results.forEach((res) => {
    const card = document.createElement("div");
    card.className = "result-card";
    const title = res.metadata.title || "Unknown Title";
    const summary = res.summary || "";
    const score = Math.round(res.score * 100);

    // Generate buttons for all available files (Main + Supplements)
    let fileButtons = "";
    if (res.files && res.files.length > 0) {
      fileButtons = res.files
        .map((f, idx) => {
          let label = idx === 0 ? "PDF" : `Supp ${idx}`;
          const lowerName = f.filename.toLowerCase();
          if (lowerName.includes("supp")) label = "Supp";
          if (lowerName.includes("fig")) label = "Figs";

          return `<button class="view-btn" onclick="openPDF('${res.hash_id}', '${f.filename}')" title="${f.filename}">${label}</button>`;
        })
        .join("");
    }

    card.innerHTML = `
            <div class="result-title">${title}</div>
            <div class="result-summary">${summary}</div>
            <div class="result-footer">
                <span class="score-badge">${score}% Match</span>
                <div style="display: flex; gap: 0.3rem; flex-wrap: wrap; justify-content: flex-end;">
                    <button class="view-btn" style="background: var(--accent-color); color: white;" onclick="openQuickGraph('${res.hash_id}')">Quick Graph</button>
                    ${fileButtons}
                    <button class="view-btn" onclick="openRawText('${res.hash_id}', '${title.replace(/'/g, "\\'")}')">Text</button>
                    <button class="view-btn" id="bib-btn-${res.hash_id}" onclick="addToBib('${res.hash_id}')" style="background: #3b82f6">Cite</button>
                </div>
            </div>
        `;
    resultsContainer.appendChild(card);
  });
}

window.openQuickGraph = (hash_id) => {
  if (graphModal && graphFrame) {
    graphFrame.src = `/ui/graph.html?neighbor_id=${hash_id}&token=${CONFIG.AUTH_TOKEN}`;
    graphModal.style.display = "flex";
  } else {
    window.open(
      `/ui/graph.html?neighbor_id=${hash_id}&token=${CONFIG.AUTH_TOKEN}`,
      "_blank",
    );
  }
};

window.openPDF = (hash_id, filename = "") => {
  let url = `${CONFIG.API_BASE}/api/pdf/${hash_id}?token=${CONFIG.AUTH_TOKEN}`;
  if (filename) {
    url += `&filename=${encodeURIComponent(filename)}`;
  }
  pdfFrame.src = url;
  pdfModal.style.display = "flex";
};

window.addToBib = async (hash_id) => {
  // Select buttons in both Matches and Library views if they exist
  const btnMatch = document.getElementById(`bib-btn-${hash_id}`);
  const btnLib = document.getElementById(`bib-btn-lib-${hash_id}`);

  // If already cited, copy the citation key instead of triggering another API call
  const activeBtn = btnMatch || btnLib;
  if (activeBtn && activeBtn.classList.contains("citation-ready")) {
    const citationKey = activeBtn.dataset.citationKey;
    if (!citationKey) return; // Wait for it to become ready
    if (activeBtn.textContent === "Copied!") return; // Prevent double clicks

    try {
      await navigator.clipboard.writeText(`\\cite{${citationKey}}`);

      [btnMatch, btnLib].forEach((btn) => {
        if (btn) {
          btn.textContent = "Copied!";
          btn.style.background = "#10b981"; // success color
          setTimeout(() => {
            btn.textContent = `\\cite{${citationKey}}`;
            btn.style.background = ""; // restore original background
          }, 2000);
        }
      });
    } catch (e) {
      console.error("Failed to copy citation:", e);
    }
    return;
  }

  [btnMatch, btnLib].forEach((btn) => {
    if (btn) {
      btn.textContent = "Adding…";
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
    }
  });

  try {
    const response = await fetch(`${CONFIG.API_BASE}/api/citation/add`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ hash_id: hash_id, project: state.activeProject }),
    });
    if (response.ok) {
      const data = await response.json();

      [btnMatch, btnLib].forEach((btn) => {
        if (btn) {
          btn.textContent = "Added!";
          btn.classList.add("citation-ready");
          btn.dataset.citationKey = data.bib_key;
          btn.setAttribute("title", "Click to copy citation");
          setTimeout(() => {
            btn.textContent = `\\cite{${data.bib_key}}`;
          }, 1000);
        }
      });
    }
  } catch (e) {
    console.error(e);
    [btnMatch, btnLib].forEach((btn) => {
      if (btn) btn.textContent = "Error";
    });
  } finally {
    [btnMatch, btnLib].forEach((btn) => {
      if (btn) {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
      }
    });
  }
};

// =============================================================================
// D3 GRAPH
// =============================================================================

async function loadGraph() {
  try {
    const response = await fetch(`${CONFIG.API_BASE}/api/graph`, {
      headers: authHeaders(),
    });
    const data = await response.json();
    renderGraph(data);
  } catch (e) {
    console.error("Graph Load Error:", e);
  }
}

function renderGraph(data) {
  const graphWorkspace = document.getElementById("graph-workspace");
  if (!graphWorkspace) return;

  // Clear previous
  graphWorkspace.innerHTML =
    '<div id="graph-canvas-container" style="position:relative; width:100%; height:100%; overflow:hidden;">' +
    '<div id="graph-canvas" style="width:100%; height:100%;"></div>' +
    '<div class="graph-controls" style="position:absolute; top:10px; right:10px; display:flex; gap:10px;">' +
    `<button class="view-btn" style="background: var(--accent-color); color: white;" onclick="window.location.href='/ui/graph.html?token=${CONFIG.AUTH_TOKEN}'">Advanced Explorer →</button>` +
    "</div></div>";

  const canvas = document.getElementById("graph-canvas");
  const width = graphWorkspace.clientWidth || 800;
  const height = graphWorkspace.clientHeight || 600;

  const svg = d3
    .select("#graph-canvas")
    .append("svg")
    .attr("width", "100%")
    .attr("height", "100%")
    .attr("viewBox", `0 0 ${width} ${height}`);

  // Adapt formats
  const links = (data.links || data.edges || []).map((d) => ({
    source: d.source,
    target: d.target,
    value: d.value || 1,
  }));

  const nodes = data.nodes.map((d) => ({
    ...d,
    id: d.id || d.hash_id,
    label: d.title || d.label || d.name || d.id || d.hash_id,
  }));

  const simulation = d3
    .forceSimulation(nodes)
    .force(
      "link",
      d3
        .forceLink(links)
        .id((d) => d.id)
        .distance(100),
    )
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(width / 2, height / 2));

  const link = svg
    .append("g")
    .attr("stroke", "#475569")
    .attr("stroke-opacity", 0.4)
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("stroke-width", (d) => Math.sqrt(d.value));

  const node = svg
    .append("g")
    .selectAll("g")
    .data(nodes)
    .join("g")
    .call(
      d3
        .drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended),
    );

  node
    .append("circle")
    .attr("r", 8)
    .attr("fill", (d) => d.cluster_color || "var(--accent-color)")
    .attr("stroke", "#fff")
    .attr("stroke-width", 1);

  node
    .append("text")
    .text((d) =>
      d.label.length > 20 ? d.label.substring(0, 20) + "…" : d.label,
    )
    .attr("x", 12)
    .attr("y", 4)
    .attr("fill", "#94a3b8")
    .style("font-size", "10px")
    .style("pointer-events", "none");

  node.append("title").text((d) => d.label);

  node.on("click", (event, d) => {
    if (d.hash_id) {
      window.openQuickGraph(d.hash_id);
    }
  });

  simulation.on("tick", () => {
    link
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    node.attr("transform", (d) => `translate(${d.x},${d.y})`);
  });

  function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
  }

  function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
  }

  function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
  }
}

document.addEventListener("DOMContentLoaded", init);

// =============================================================================
// UTILS
// =============================================================================
function showToast(message, duration = 3000) {
  let toast = document.getElementById("toast-notification");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast-notification";
    toast.className = "toast-notification";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("show");

  setTimeout(() => {
    toast.classList.remove("show");
  }, duration);
}
