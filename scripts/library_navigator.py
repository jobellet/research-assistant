import os
import json
import webbrowser
import base64
from pathlib import Path

# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = PROJECT_ROOT / "library"
OUTPUT_FILE = PROJECT_ROOT / "library_portal.html"

def get_library_data():
    """Scans the library and collects all metadata."""
    papers = []
    if not LIBRARY_DIR.exists():
        print(f"Error: Library directory not found at {LIBRARY_DIR}")
        return papers

    print(f"Scanning {LIBRARY_DIR} for papers...")
    
    # Get all hash directories
    try:
        dirs = [d for d in LIBRARY_DIR.iterdir() if d.is_dir() and len(d.name) == 64]
    except Exception as e:
        print(f"Error accessing library: {e}")
        return []

    for hash_dir in dirs:
        metadata_path = hash_dir / "metadata.json"
        text_path = hash_dir / "full_text.txt"
        
        paper = {
            "hash": hash_dir.name,
            "title": "Unknown Title",
            "authors": [],
            "year": "N/A",
            "summary": "No summary available.",
            "full_text": "",
            "doi": ""
        }
        
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    paper.update(meta)
            except Exception as e:
                print(f"Warning: Could not parse metadata for {hash_dir.name}: {e}")
        
        if text_path.exists():
            try:
                with open(text_path, 'r', encoding='utf-8') as f:
                    # Read the ENTIRE text now
                    paper["full_text"] = f.read() 
            except:
                pass
                
        papers.append(paper)
    
    # Sort by year descending
    return sorted(papers, key=lambda x: str(x.get("year", "0")), reverse=True)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Research Portal | Local Navigator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0a0a0c;
            --card-bg: rgba(255, 255, 255, 0.03);
            --accent-primary: #6366f1;
            --accent-secondary: #a855f7;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --glass-border: rgba(255, 255, 255, 0.08);
            --glow: 0 0 20px rgba(99, 102, 241, 0.15);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            line-height: 1.6;
            overflow-x: hidden;
            background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0a0a0c 100%);
            min-height: 100vh;
        }

        h1, h2, h3, .brand {
            font-family: 'Outfit', sans-serif;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--glass-border);
        }

        .brand {
            font-size: 1.8rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }

        .stats {
            font-size: 0.9rem;
            color: var(--text-dim);
            background: var(--card-bg);
            padding: 0.5rem 1rem;
            border-radius: 99px;
            border: 1px solid var(--glass-border);
        }

        .search-container {
            position: sticky;
            top: 2rem;
            z-index: 100;
            margin-bottom: 3rem;
        }

        #searchBar {
            width: 100%;
            padding: 1.2rem 2rem;
            background: rgba(15, 15, 20, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            color: white;
            font-size: 1.1rem;
            box-shadow: var(--glow);
            transition: all 0.3s ease;
            outline: none;
        }

        #searchBar:focus {
            border-color: var(--accent-primary);
            box-shadow: 0 0 30px rgba(99, 102, 241, 0.3);
        }

        .paper-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 2rem;
        }

        .paper-card {
            background: var(--card-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 2rem;
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            cursor: pointer;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
        }

        .paper-card:hover {
            transform: translateY(-10px);
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(99, 102, 241, 0.4);
        }

        .paper-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(to bottom, var(--accent-primary), var(--accent-secondary));
            opacity: 0.6;
        }

        .paper-year {
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--accent-primary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.5rem;
        }

        .paper-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1rem;
            line-height: 1.3;
            color: white;
        }

        .paper-authors {
            font-size: 0.9rem;
            color: var(--text-dim);
            margin-bottom: 1.5rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .paper-footer {
            margin-top: auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .btn-view {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--glass-border);
            color: white;
            padding: 0.5rem 1.2rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 500;
            transition: all 0.2s;
        }

        .paper-card:hover .btn-view {
            background: var(--accent-primary);
            border-color: var(--accent-primary);
        }

        /* Modal Styles */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(10px);
            z-index: 1000;
            display: none;
            justify-content: center;
            align-items: center;
            padding: 2rem;
        }

        .modal-content {
            background: #0f172a;
            width: 100%;
            max-width: 900px;
            max-height: 90vh;
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            padding: 3rem;
            position: relative;
            overflow-y: auto;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }

        .close-modal {
            position: absolute;
            top: 1.5rem;
            right: 1.5rem;
            font-size: 2rem;
            color: var(--text-dim);
            cursor: pointer;
            transition: color 0.2s;
        }

        .close-modal:hover {
            color: white;
        }

        .modal-header h2 {
            font-size: 2rem;
            margin-bottom: 1rem;
            background: linear-gradient(135deg, #fff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .modal-meta {
            margin-bottom: 2rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--glass-border);
            color: var(--text-dim);
        }

        .modal-section {
            margin-bottom: 2rem;
            position: relative;
        }

        .modal-section h3 {
            color: var(--accent-primary);
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .summary-text {
            font-size: 1.1rem;
            line-height: 1.7;
            color: #cbd5e1;
        }

        .full-text-container {
            position: relative;
        }

        .full-text-preview {
            background: rgba(0,0,0,0.3);
            padding: 1.5rem;
            border-radius: 12px;
            font-family: 'Inter', monospace;
            font-size: 0.9rem;
            white-space: pre-wrap;
            color: #94a3b8;
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid rgba(255,255,255,0.05);
        }

        .btn-copy {
            background: var(--accent-primary);
            color: white;
            border: none;
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .btn-copy:hover {
            transform: scale(1.05);
            background: var(--accent-secondary);
        }

        .btn-copy.copied {
            background: #10b981;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }

        .no-results {
            text-align: center;
            padding: 4rem;
            color: var(--text-dim);
            grid-column: 1 / -1;
        }

        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: var(--bg-color);
        }
        ::-webkit-scrollbar-thumb {
            background: #27272a;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #3f3f46;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">Research Portal</div>
            <div class="stats" id="paperCount">Loading library...</div>
        </header>

        <div class="search-container">
            <input type="text" id="searchBar" placeholder="Search by title, author, DOI or keywords..." autofocus>
        </div>

        <div class="paper-grid" id="paperGrid">
            <!-- Papers injected here -->
        </div>
    </div>

    <div class="modal-overlay" id="modalOverlay">
        <div class="modal-content">
            <span class="close-modal" id="closeModal">&times;</span>
            <div id="modalBody">
                <!-- Modal content injected here -->
            </div>
        </div>
    </div>

    <script>
        const papers = {{PAPERS_JSON}};

        const paperGrid = document.getElementById('paperGrid');
        const searchBar = document.getElementById('searchBar');
        const paperCount = document.getElementById('paperCount');
        const modalOverlay = document.getElementById('modalOverlay');
        const modalBody = document.getElementById('modalBody');
        const closeModal = document.getElementById('closeModal');

        function renderPapers(filteredPapers) {
            paperGrid.innerHTML = '';
            paperCount.textContent = `${filteredPapers.length} Papers Found`;

            if (filteredPapers.length === 0) {
                paperGrid.innerHTML = '<div class="no-results"><h3>No papers match your search.</h3><p>Try searching for a different term or check your library folders.</p></div>';
                return;
            }

            filteredPapers.forEach(paper => {
                const card = document.createElement('div');
                card.className = 'paper-card';
                card.onclick = () => showPaperDetails(paper);

                const authors = Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors;

                card.innerHTML = `
                    <div class="paper-year">${paper.year}</div>
                    <div class="paper-title">${paper.title}</div>
                    <div class="paper-authors">${authors}</div>
                    <div class="paper-footer">
                        <span style="font-size: 0.7rem; color: var(--text-dim); opacity: 0.5;">${paper.hash.substring(0,8)}...</span>
                        <button class="btn-view">Open Paper</button>
                    </div>
                `;
                paperGrid.appendChild(card);
            });
        }

        function showPaperDetails(paper) {
            const authors = Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors;
            
            modalBody.innerHTML = `
                <div class="modal-header">
                    <h2>${paper.title}</h2>
                </div>
                <div class="modal-meta">
                    <p><strong>Authors:</strong> ${authors}</p>
                    <p><strong>Year:</strong> ${paper.year} | <strong>DOI:</strong> ${paper.doi || 'N/A'}</p>
                    <p><strong>Hash:</strong> ${paper.hash}</p>
                </div>
                <div class="modal-section">
                    <h3>Summary</h3>
                    <div class="summary-text">${paper.summary.replace(/\\\\n/g, '<br>')}</div>
                </div>
                <div class="modal-section">
                    <h3>
                        Extracted Manuscript
                        <button class="btn-copy" id="copyBtn" onclick="copyManuscript()">Copy Content</button>
                    </h3>
                    <div class="full-text-container">
                        <div class="full-text-preview" id="manuscriptText">${escapeHtml(paper.full_text)}</div>
                    </div>
                </div>
            `;
            modalOverlay.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        async function copyManuscript() {
            const text = document.getElementById('manuscriptText').innerText;
            const btn = document.getElementById('copyBtn');
            
            try {
                await navigator.clipboard.writeText(text);
                btn.innerText = 'Copied!';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.innerText = 'Copy Content';
                    btn.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy: ', err);
                alert('Could not copy text. Please select manually.');
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        searchBar.addEventListener('input', (e) => {
            const term = e.target.value.toLowerCase();
            const filtered = papers.filter(p => 
                p.title.toLowerCase().includes(term) || 
                (Array.isArray(p.authors) ? p.authors.join(' ').toLowerCase() : p.authors.toLowerCase()).includes(term) ||
                p.summary.toLowerCase().includes(term) ||
                (p.doi && p.doi.toLowerCase().includes(term))
            );
            renderPapers(filtered);
        });

        closeModal.onclick = () => {
            modalOverlay.style.display = 'none';
            document.body.style.overflow = 'auto';
        };

        window.onclick = (event) => {
            if (event.target == modalOverlay) {
                closeModal.onclick();
            }
        };

        // Initial render
        renderPapers(papers);
    </script>
</body>
</html>
"""

def generate_portal():
    papers = get_library_data()
    
    # Inject papers JSON into template
    html_content = HTML_TEMPLATE.replace("{{PAPERS_JSON}}", json.dumps(papers, indent=2))
    
    # Write to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Successfully generated {OUTPUT_FILE}")
    print(f"Found {len(papers)} papers.")
    
    # Open in browser
    webbrowser.open(f"file://{OUTPUT_FILE}")

if __name__ == "__main__":
    generate_portal()
