import os
import sys
import json
import csv
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# Set up project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from search_module.bow_searcher import BowSearcher
from citation_module.citation_manager import CitationManager

class ResearchAssistantGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("My AI Research Assistant - Quick Search")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        # Style configuration
        self.setup_styles()

        # Data states
        self.inventory = {}
        self.projects = []
        self.search_results = []
        self.selected_paper = None
        self.semantic_searcher = None
        self.semantic_loading = True
        self.semantic_error = None
        self.debounce_timer = None

        # Build UI layout
        self.create_widgets()

        # Load inventory and BOW index
        self.load_local_data()

        # Start Semantic Searcher in background thread
        threading.Thread(target=self.init_semantic_searcher, daemon=True).start()

    def setup_styles(self):
        """Configure clean, modern dark colors using ttk styles."""
        # Catppuccin Mocha inspired dark theme palette
        self.colors = {
            "bg": "#181825",          # Crust/Mantle
            "card": "#1e1e2e",        # Base
            "input": "#313244",       # Surface0
            "text": "#cdd6f4",        # Text
            "subtext": "#a6adc8",     # Subtext0
            "accent": "#89b4fa",      # Blue (primary action)
            "secondary": "#b4befe",   # Lavender
            "alert": "#f38ba8",       # Red
            "green": "#a6e3a1",       # Green
            "border": "#45475a"       # Surface1
        }

        # Apply dark theme to main root window
        self.root.configure(bg=self.colors["bg"])

        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Global configurations
        self.style.configure(".",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            fieldbackground=self.colors["input"],
            font=("Helvetica", 10)
        )

        # Custom frames
        self.style.configure("Main.TFrame", background=self.colors["bg"])
        self.style.configure("Card.TFrame", background=self.colors["card"], relief="flat")
        self.style.configure("Border.TFrame", background=self.colors["border"])

        # Label configurations
        self.style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"])
        self.style.configure("Sub.TLabel", background=self.colors["bg"], foreground=self.colors["subtext"], font=("Helvetica", 9))
        self.style.configure("Card.TLabel", background=self.colors["card"], foreground=self.colors["text"])
        self.style.configure("Title.TLabel", background=self.colors["card"], foreground=self.colors["secondary"], font=("Helvetica", 14, "bold"))
        self.style.configure("Header.TLabel", background=self.colors["bg"], foreground=self.colors["accent"], font=("Helvetica", 11, "bold"))

        # Buttons
        self.style.configure("TButton",
            background=self.colors["input"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            relief="flat",
            padding=(8, 4)
        )
        self.style.map("TButton",
            background=[("active", self.colors["accent"]), ("pressed", self.colors["border"])],
            foreground=[("active", self.colors["bg"]), ("pressed", self.colors["text"])]
        )

        self.style.configure("Accent.TButton",
            background=self.colors["accent"],
            foreground=self.colors["bg"],
            font=("Helvetica", 10, "bold"),
            relief="flat",
            padding=(10, 5)
        )
        self.style.map("Accent.TButton",
            background=[("active", self.colors["secondary"]), ("pressed", self.colors["input"])],
            foreground=[("active", self.colors["bg"]), ("pressed", self.colors["text"])]
        )

        # Entry fields
        self.style.configure("TEntry",
            fieldbackground=self.colors["input"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            insertcolor=self.colors["text"]
        )

        # Radiobuttons
        self.style.configure("TRadiobutton",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            indicatorcolor=self.colors["input"]
        )
        self.style.map("TRadiobutton",
            background=[("active", self.colors["bg"])],
            indicatorcolor=[("selected", self.colors["accent"])]
        )

        # Comboboxes
        self.style.configure("TCombobox",
            fieldbackground=self.colors["input"],
            background=self.colors["input"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            arrowcolor=self.colors["text"]
        )

        # Treeview styling (results list)
        self.style.configure("Treeview",
            background=self.colors["card"],
            foreground=self.colors["text"],
            fieldbackground=self.colors["card"],
            bordercolor=self.colors["border"],
            rowheight=35,
            font=("Helvetica", 10)
        )
        self.style.configure("Treeview.Heading",
            background=self.colors["input"],
            foreground=self.colors["text"],
            font=("Helvetica", 10, "bold")
        )
        self.style.map("Treeview",
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", self.colors["bg"])]
        )

    def create_widgets(self):
        """Build layout with panels and interactive widgets."""
        # Root layout container
        main_container = ttk.Frame(self.root, style="Main.TFrame", padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)

        # ----------------- TOP PANEL (Search Controls) -----------------
        top_frame = ttk.Frame(main_container, style="Main.TFrame")
        top_frame.pack(fill=tk.X, pady=(0, 15))

        # Search Bar
        ttk.Label(top_frame, text="Quick Search:", style="Header.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=50)
        self.search_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, 15))
        self.search_entry.focus()
        
        # Debounce real-time search binding
        self.search_entry.bind("<KeyRelease>", self.on_search_key_release)
        self.search_entry.bind("<Return>", lambda e: self.perform_search())

        # Search Mode
        self.mode_var = tk.StringVar(value="bow")
        self.radio_bow = ttk.Radiobutton(top_frame, text="Bag of Words (Fast)", variable=self.mode_var, value="bow", command=self.perform_search)
        self.radio_bow.grid(row=0, column=2, padx=(0, 15), sticky=tk.W)

        self.radio_semantic = ttk.Radiobutton(top_frame, text="Semantic (ChromaDB)", variable=self.mode_var, value="semantic", command=self.perform_search)
        self.radio_semantic.grid(row=0, column=3, padx=(0, 15), sticky=tk.W)
        self.radio_semantic.state(["disabled"])  # Wait until ChromaDB finishes loading

        # Active Project Selector
        ttk.Label(top_frame, text="Active Project:", style="TLabel").grid(row=0, column=4, padx=(15, 5), sticky=tk.E)
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(top_frame, textvariable=self.project_var, width=15, state="readonly")
        self.project_combo.grid(row=0, column=5, sticky=tk.W)

        top_frame.columnconfigure(1, weight=1)

        # ----------------- MAIN PANEL (Split View) -----------------
        split_frame = ttk.Frame(main_container, style="Main.TFrame")
        split_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column (Results List)
        left_frame = ttk.Frame(split_frame, style="Main.TFrame", width=400)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        left_frame.pack_propagate(False)

        # Treeview table list for papers
        self.tree = ttk.Treeview(left_frame, columns=("title", "year", "score"), show="headings")
        self.tree.heading("title", text="Title")
        self.tree.heading("year", text="Year")
        self.tree.heading("score", text="Match")
        
        self.tree.column("title", width=230, anchor=tk.W)
        self.tree.column("year", width=50, anchor=tk.CENTER)
        self.tree.column("score", width=60, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self.on_paper_select)
        self.tree.bind("<Double-1>", lambda e: self.open_pdf())

        # Right Column (Detailed View Card)
        self.right_frame = ttk.Frame(split_frame, style="Card.TFrame", padding=15)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Paper Metadata Labels
        self.lbl_title = ttk.Label(self.right_frame, text="Select a paper to view details", style="Title.TLabel", wraplength=450)
        self.lbl_title.pack(fill=tk.X, pady=(0, 10))

        self.lbl_authors = ttk.Label(self.right_frame, text="", style="Card.TLabel", wraplength=450)
        self.lbl_authors.pack(fill=tk.X, pady=2)

        self.lbl_journal = ttk.Label(self.right_frame, text="", style="Card.TLabel", wraplength=450)
        self.lbl_journal.pack(fill=tk.X, pady=2)

        self.lbl_doi = ttk.Label(self.right_frame, text="", style="Card.TLabel", wraplength=450)
        self.lbl_doi.pack(fill=tk.X, pady=2)

        self.lbl_keywords = ttk.Label(self.right_frame, text="", style="Card.TLabel", wraplength=450)
        self.lbl_keywords.pack(fill=tk.X, pady=(2, 10))

        # Action Buttons frame
        self.btn_frame = ttk.Frame(self.right_frame, style="Card.TFrame")
        self.btn_frame.pack(fill=tk.X, pady=(0, 15))

        self.btn_open = ttk.Button(self.btn_frame, text="📄 Open PDF", style="Accent.TButton", command=self.open_pdf)
        self.btn_open.grid(row=0, column=0, padx=(0, 8), pady=5)

        self.btn_cite = ttk.Button(self.btn_frame, text="📋 Copy BibTeX", command=self.copy_bibtex)
        self.btn_cite.grid(row=0, column=1, padx=(0, 8), pady=5)

        self.btn_key = ttk.Button(self.btn_frame, text="📋 Copy Key", command=self.copy_key)
        self.btn_key.grid(row=0, column=2, padx=(0, 8), pady=5)

        self.btn_doi = ttk.Button(self.btn_frame, text="🔗 Go to DOI", command=self.open_doi)
        self.btn_doi.grid(row=0, column=3, padx=(0, 8), pady=5)

        self.btn_add_project = ttk.Button(self.btn_frame, text="➕ Add to Bib", style="Accent.TButton", command=self.add_to_project_bib)
        self.btn_add_project.grid(row=0, column=4, padx=(0, 8), pady=5)

        # Disable detail buttons by default
        self.set_detail_buttons_state(tk.DISABLED)

        # Abstract / Summary Scrollable Text
        ttk.Label(self.right_frame, text="Summary / Abstract:", style="Card.TLabel").pack(anchor=tk.W, pady=(10, 5))
        
        text_container = ttk.Frame(self.right_frame, style="Card.TFrame")
        text_container.pack(fill=tk.BOTH, expand=True)

        self.txt_summary = tk.Text(text_container,
            wrap=tk.WORD,
            bg=self.colors["input"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            bd=0,
            padx=10,
            pady=10,
            font=("Helvetica", 10)
        )
        txt_scroll = ttk.Scrollbar(text_container, orient=tk.VERTICAL, command=self.txt_summary.yview)
        self.txt_summary.configure(yscrollcommand=txt_scroll.set)

        self.txt_summary.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Make read-only
        self.txt_summary.config(state=tk.DISABLED)

        # ----------------- BOTTOM STATUS BAR -----------------
        self.status_bar = ttk.Label(main_container, text="Loading inventory and BOW index...", style="Sub.TLabel", anchor=tk.W, padding=(5, 5))
        self.status_bar.pack(fill=tk.X, pady=(10, 0))

    def set_detail_buttons_state(self, state):
        """Enable or disable detailed paper action buttons."""
        self.btn_open.config(state=state)
        self.btn_cite.config(state=state)
        self.btn_key.config(state=state)
        self.btn_doi.config(state=state)
        self.btn_add_project.config(state=state)

    def load_local_data(self):
        """Load projects list, CSV paper inventory, and fast Bag of Words searcher."""
        # 1. Load projects
        try:
            projects_dir = PROJECT_ROOT / "projects"
            if projects_dir.exists():
                self.projects = sorted([p.name for p in projects_dir.iterdir() if p.is_dir()])
            if not self.projects:
                self.projects = ["default"]
            self.project_combo["values"] = self.projects
            self.project_combo.set(self.projects[0])
        except Exception as e:
            self.status_bar.config(text=f"Warning: Failed to load projects list ({e})")
            self.projects = ["default"]
            self.project_combo["values"] = self.projects
            self.project_combo.set("default")

        # 2. Load Papers Inventory CSV
        inventory_path = PROJECT_ROOT / "papers_inventory.csv"
        if inventory_path.exists():
            try:
                with open(inventory_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.inventory[row["hash"]] = row
                self.status_bar.config(text=f"Loaded {len(self.inventory)} papers from inventory.")
            except Exception as e:
                self.status_bar.config(text=f"Warning: Failed to load papers_inventory.csv: {e}")
        else:
            self.status_bar.config(text="Warning: papers_inventory.csv not found.")

        # 3. Load Bag of Words Index
        index_path = PROJECT_ROOT / "library" / "global_bow_index.json"
        if index_path.exists():
            self.bow_searcher = BowSearcher(index_path=str(index_path))
        else:
            self.bow_searcher = None
            self.status_bar.config(text="Warning: Bag of Words index not found. Please build it first.")

    def init_semantic_searcher(self):
        """Initializes ChromaDB in a background thread to prevent GUI freezing."""
        try:
            # We delay slightly to let the window draw
            time.sleep(0.5)
            self.update_status("⚡ Initializing ChromaDB (Semantic Search model)...")
            
            # Import modules locally to avoid load time at startup
            from search_module.searcher import SemanticSearcher
            
            db_path = PROJECT_ROOT / "chroma_db"
            library_dir = PROJECT_ROOT / "library"
            
            self.semantic_searcher = SemanticSearcher(db_path=str(db_path), library_dir=str(library_dir))
            
            # Update GUI once loaded successfully
            self.root.after(0, self.on_semantic_loaded)
        except Exception as e:
            self.semantic_error = str(e)
            self.root.after(0, self.on_semantic_failed)

    def on_semantic_loaded(self):
        """Callback run on main thread when Semantic Searcher is ready."""
        self.semantic_loading = False
        self.radio_semantic.state(["!disabled"])
        self.update_status(f"Ready. Bag of Words and Semantic search available ({len(self.inventory)} papers).")

    def on_semantic_failed(self):
        """Callback run on main thread if Semantic Searcher failed to load."""
        self.semantic_loading = False
        self.mode_var.set("bow")
        self.radio_semantic.state(["disabled"])
        self.update_status("⚠️ Semantic Search unavailable (offline fallback / missing libraries).")

    def update_status(self, text, color=None):
        """Helper to safely update the status bar text."""
        self.status_bar.config(text=text)
        if color:
            self.status_bar.config(foreground=color)
        else:
            self.status_bar.config(foreground=self.colors["subtext"])

    def on_search_key_release(self, event):
        """Debounces user keystrokes for real-time interactive search."""
        if self.debounce_timer:
            self.root.after_cancel(self.debounce_timer)
        
        self.debounce_timer = self.root.after(300, self.perform_search)

    def perform_search(self):
        """Performs search using the chosen mode."""
        query = self.search_var.get().strip()
        
        # Clear current list
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not query:
            self.search_results = []
            return

        mode = self.mode_var.get()

        if mode == "semantic" and self.semantic_searcher:
            self.update_status("🔍 Searching vector database...")
            # Query vector DB
            threading.Thread(target=self.run_semantic_query, args=(query,), daemon=True).start()
        else:
            # Bag of Words search
            if not self.bow_searcher:
                self.update_status("Error: Bag of Words index is missing.", self.colors["alert"])
                return
            
            raw_results = self.bow_searcher.search(query, top_k=20)
            self.search_results = []
            
            for res in raw_results:
                hash_id = res["hash_id"]
                score = res["score"]
                meta = self.inventory.get(hash_id, {})
                
                # Fetch local file list if directory exists
                pdf_filename = meta.get("pdf_filename")
                files = []
                hash_dir = PROJECT_ROOT / "library" / hash_id
                if hash_dir.exists():
                    files = [{"filename": f.name, "path": str(f)} for f in hash_dir.glob("*.pdf")]

                # Get summary from local metadata.json if it exists
                summary = ""
                meta_json_path = hash_dir / "metadata.json"
                if meta_json_path.exists():
                    try:
                        with open(meta_json_path, "r") as mf:
                            m_data = json.load(mf)
                            summary = m_data.get("summary", m_data.get("Summary", ""))
                    except:
                        pass

                self.search_results.append({
                    "hash_id": hash_id,
                    "score": score,
                    "metadata": meta,
                    "summary": summary,
                    "files": files,
                    "method": "bow"
                })

            self.populate_tree()
            self.update_status(f"Found {len(self.search_results)} matches using Bag of Words.")

    def run_semantic_query(self, query):
        """Worker thread logic to run the semantic vector search."""
        try:
            results = self.semantic_searcher.search(query, n_results=15)
            # Reformat to match GUI search_results schema
            formatted = []
            for res in results:
                hash_id = res["hash_id"]
                # In ChromaDB results, score is similarity (1 - distance)
                # Map to percentage
                score_pct = round(res["score"] * 100, 2)
                
                # Merge with inventory row metadata to ensure we have all fields
                meta = self.inventory.get(hash_id, {})
                for k, v in res["metadata"].items():
                    meta[k] = v

                formatted.append({
                    "hash_id": hash_id,
                    "score": score_pct,
                    "metadata": meta,
                    "summary": res["summary"],
                    "files": res["files"],
                    "method": "semantic"
                })

            self.search_results = formatted
            # Update tree on main thread
            self.root.after(0, self.populate_tree_semantic, len(formatted))
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"Semantic search failed: {e}", self.colors["alert"]))

    def populate_tree_semantic(self, count):
        self.populate_tree()
        self.update_status(f"Found {count} matches using ChromaDB Semantic Search.")

    def populate_tree(self):
        """Fills the results tree with the current search results."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, res in enumerate(self.search_results):
            meta = res["metadata"]
            title = meta.get("title") or meta.get("pdf_filename") or "Unknown Title"
            year = meta.get("year") or "N/A"
            score = f"{res['score']:.2f}%" if res["method"] == "bow" else f"{res['score']}%"
            
            self.tree.insert("", tk.END, iid=str(i), values=(title, year, score))

    def on_paper_select(self, event):
        """Displays selected paper's metadata and summary in the right pane."""
        selected_items = self.tree.selection()
        if not selected_items:
            self.selected_paper = None
            self.clear_details()
            return

        idx = int(selected_items[0])
        self.selected_paper = self.search_results[idx]
        meta = self.selected_paper["metadata"]

        # Fill metadata labels
        title = meta.get("title") or meta.get("pdf_filename") or "Unknown Title"
        self.lbl_title.config(text=title)
        
        authors = meta.get("authors") or "Unknown Authors"
        self.lbl_authors.config(text=f"Authors: {authors}")
        
        journal = meta.get("journal") or "N/A"
        self.lbl_journal.config(text=f"Journal: {journal} ({meta.get('year', 'N/A')})")
        
        doi = meta.get("doi") or meta.get("DOI") or ""
        if doi:
            self.lbl_doi.config(text=f"DOI: {doi}")
        else:
            self.lbl_doi.config(text="DOI: None")

        keywords = meta.get("keywords") or ""
        if isinstance(keywords, list):
            keywords = ", ".join(keywords)
        self.lbl_keywords.config(text=f"Keywords: {keywords}")

        # Fill Summary / Abstract Textbox
        self.txt_summary.config(state=tk.NORMAL)
        self.txt_summary.delete("1.0", tk.END)
        
        summary = self.selected_paper.get("summary") or meta.get("summary") or meta.get("Summary") or ""
        if not summary.strip():
            # Try reading abstract from full text fallback
            hash_id = self.selected_paper["hash_id"]
            text_file = PROJECT_ROOT / "library" / hash_id / "preprocessed_text.txt"
            if not text_file.exists():
                text_file = PROJECT_ROOT / "library" / hash_id / "full_text.txt"
            
            if text_file.exists():
                try:
                    text_content = text_file.read_text(encoding='utf-8', errors='ignore')
                    # Snip first 1500 chars as placeholder
                    summary = text_content[:1500] + "\n\n[... Abstract extracted from full text ...]"
                except:
                    summary = "No summary or text available for this paper."
            else:
                summary = "No summary or text available for this paper."

        self.txt_summary.insert(tk.END, summary)
        
        # Highlight search terms in summary text
        self.highlight_search_terms(summary)
        
        self.txt_summary.config(state=tk.DISABLED)

        # Enable action buttons
        self.set_detail_buttons_state(tk.NORMAL)

    def highlight_search_terms(self, text):
        """Highlights matched query terms in the summary text pane."""
        # Reset tags
        for tag in self.txt_summary.tag_names():
            self.txt_summary.tag_delete(tag)
        
        query = self.search_var.get().lower().strip()
        if not query:
            return

        terms = [t for t in query.split() if len(t) > 2]
        self.txt_summary.tag_configure("highlight", background="#414559", foreground=self.colors["secondary"])

        for term in terms:
            start_pos = "1.0"
            while True:
                start_pos = self.txt_summary.search(term, start_pos, stopindex=tk.END, nocase=True)
                if not start_pos:
                    break
                end_pos = f"{start_pos}+{len(term)}c"
                self.txt_summary.tag_add("highlight", start_pos, end_pos)
                start_pos = end_pos

    def clear_details(self):
        """Clears details panel when no paper is selected."""
        self.lbl_title.config(text="Select a paper to view details")
        self.lbl_authors.config(text="")
        self.lbl_journal.config(text="")
        self.lbl_doi.config(text="")
        self.lbl_keywords.config(text="")
        
        self.txt_summary.config(state=tk.NORMAL)
        self.txt_summary.delete("1.0", tk.END)
        self.txt_summary.config(state=tk.DISABLED)
        
        self.set_detail_buttons_state(tk.DISABLED)

    def open_pdf(self):
        """Locates associated PDF files and opens the selected one."""
        if not self.selected_paper:
            return

        files = self.selected_paper.get("files") or []
        hash_id = self.selected_paper["hash_id"]

        # If files list empty, double check directory
        if not files:
            hash_dir = PROJECT_ROOT / "library" / hash_id
            if hash_dir.exists():
                files = [{"filename": f.name, "path": str(f)} for f in hash_dir.glob("*.pdf")]

        if not files:
            # Check external library path
            external_path = os.getenv("EXTERNAL_LIBRARY_PATH")
            if external_path:
                ext_dir = Path(external_path)
                pdf_filename = self.selected_paper["metadata"].get("pdf_filename")
                if pdf_filename:
                    matches = list(ext_dir.rglob(pdf_filename))
                    if matches:
                        files = [{"filename": matches[0].name, "path": str(matches[0])}]

        if not files:
            messagebox.showerror("Error", "No PDF files found for this paper locally.")
            return

        if len(files) == 1:
            self.launch_file(files[0]["path"])
        else:
            # Let user choose which file to open
            self.show_file_selection_dialog(files)

    def launch_file(self, filepath):
        """Safely launches a file path in the OS default application."""
        try:
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", filepath])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", filepath])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open PDF file: {e}")

    def show_file_selection_dialog(self, files):
        """Displays a dialog box allowing selection from multiple PDFs."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Select PDF File")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.colors["bg"])

        ttk.Label(dialog, text="Multiple PDFs found. Select one to open:", style="Header.TLabel", padding=10).pack(fill=tk.X)

        listbox_frame = ttk.Frame(dialog, style="Main.TFrame", padding=10)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(listbox_frame,
            bg=self.colors["input"],
            fg=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground=self.colors["bg"],
            bd=0,
            highlightthickness=0
        )
        sb = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for f in files:
            listbox.insert(tk.END, f["filename"])

        listbox.select_set(0)

        def on_confirm():
            selection = listbox.curselection()
            if selection:
                idx = selection[0]
                self.launch_file(files[idx]["path"])
                dialog.destroy()

        btn = ttk.Button(dialog, text="Open Selected", style="Accent.TButton", command=on_confirm)
        btn.pack(pady=10)

    def get_citation_manager(self) -> CitationManager:
        """Returns CitationManager instance for the selected project."""
        project = self.project_var.get()
        bib_path = PROJECT_ROOT / "projects" / project / "references.bib"
        return CitationManager(bib_path=str(bib_path))

    def copy_bibtex(self):
        """Generates a BibTeX entry and copies it to the clipboard."""
        if not self.selected_paper:
            return

        meta = self.selected_paper["metadata"]
        cm = self.get_citation_manager()
        
        # Build temp database to get written text
        from bibtexparser.bibdatabase import BibDatabase
        from bibtexparser.bwriter import BibTexWriter
        
        bib_key = cm._generate_bib_key(meta)
        db = BibDatabase()
        
        new_entry = {
            'object_type': 'book',
            'ENTRYTYPE': 'article',
            'ID': bib_key,
            'title': meta.get("title", "Unknown Title"),
            'author': meta.get("authors", "Unknown"),
            'abstract': self.selected_paper.get("summary", ""),
            'keywords': meta.get("keywords", ""),
            'note': f"Source: {self.selected_paper['hash_id']}"
        }
        db.entries.append(new_entry)
        
        writer = BibTexWriter()
        bib_text = writer.write(db)
        
        self.root.clipboard_clear()
        self.root.clipboard_append(bib_text)
        self.update_status(f"Copied BibTeX citation for {bib_key} to clipboard.", self.colors["green"])

    def copy_key(self):
        """Generates and copies the citation key to the clipboard."""
        if not self.selected_paper:
            return

        meta = self.selected_paper["metadata"]
        cm = self.get_citation_manager()
        bib_key = cm._generate_bib_key(meta)

        self.root.clipboard_clear()
        self.root.clipboard_append(bib_key)
        self.update_status(f"Copied citation key '{bib_key}' to clipboard.", self.colors["green"])

    def open_doi(self):
        """Opens DOI URL in browser."""
        if not self.selected_paper:
            return

        meta = self.selected_paper["metadata"]
        doi = meta.get("doi") or meta.get("DOI") or ""
        if not doi:
            messagebox.showinfo("DOI Info", "No DOI available for this paper.")
            return

        url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        webbrowser.open(url)
        self.update_status(f"Opening DOI link: {url}")

    def add_to_project_bib(self):
        """Appends citation entry directly to active project's references.bib."""
        if not self.selected_paper:
            return

        project = self.project_var.get()
        meta = self.selected_paper["metadata"]
        meta["hash"] = self.selected_paper["hash_id"]
        meta["summary"] = self.selected_paper.get("summary", "")

        try:
            cm = self.get_citation_manager()
            bib_key = cm.add_entry(meta)
            messagebox.showinfo("Citation Added", f"Successfully added paper to project '{project}' bibliography!\nCitation Key: {bib_key}")
            self.update_status(f"Added entry {bib_key} to {project}/references.bib", self.colors["green"])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add citation to project references.bib: {e}")


def main():
    root = tk.Tk()
    
    # Enable anti-aliased font rendering on macOS if possible
    try:
        root.tk.call('tk', 'windowingsystem')
    except:
        pass

    app = ResearchAssistantGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
