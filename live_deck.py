# live_deck.py
#
# The "infrastructure" half of the live presenter notebook, pulled out so it
# can be hosted remotely instead of pasted inline. To use it that way, host
# this file in a GitHub repo, then in your notebook's final cell:
#
#   import urllib.request
#   exec(urllib.request.urlopen(
#       "https://raw.githubusercontent.com/<you>/<repo>/<commit-sha>/live_deck.py"
#   ).read().decode())
#
# Use a specific commit SHA in the URL, not a branch name like "main" — that
# keeps behavior pinned and reproducible; you upgrade explicitly by changing
# the URL when you're ready, rather than picking up silent changes on every run.
#
# This relies on running via plain exec() (no separate globals dict passed),
# so it executes in the calling notebook's own namespace and can see PDF_PAGES,
# NOTEBOOK_URL, In, and get_ipython() exactly as if it were pasted inline.
#
# --- Original cell content below, unchanged ---

# --- Final cell: builds slides from every cell above (excluding this one and the PDF-import cell), then presents ---


import io, base64, contextlib, json
from PIL import Image, ImageDraw, ImageFont
from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import Token
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FONT_PATH = matplotlib.font_manager.findfont("DejaVu Sans Mono")

TOKEN_COLORS = {
    Token.Keyword: "#c678dd", Token.Keyword.Namespace: "#c678dd",
    Token.Name.Builtin: "#61afef", Token.Name.Function: "#61afef",
    Token.Name.Class: "#e5c07b", Token.String: "#98c379",
    Token.Number: "#d19a66", Token.Comment: "#5c6370",
    Token.Operator: "#56b6c2", Token.Punctuation: "#abb2bf",
}

def _token_color(ttype):
    while ttype not in TOKEN_COLORS and ttype.parent:
        ttype = ttype.parent
    return TOKEN_COLORS.get(ttype, "#abb2bf")

def _render_code_image(code_str, font_size=20, padding=28, line_height=1.5, min_width=700):
    font = ImageFont.truetype(FONT_PATH, font_size)
    lh = int(font_size * line_height)
    lines = code_str.rstrip("\n").split("\n")
    n_lines = len(lines)
    char_w = font.getlength("m")
    max_line_len = max((len(l) for l in lines), default=1)
    width = max(min_width, int(char_w * max_line_len) + padding * 2 + 60)
    height = n_lines * lh + padding * 2
    img = Image.new("RGB", (width, height), "#282c34")
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        x = padding + 50
        for ttype, value in lex(line, PythonLexer()):
            if value == "\n":
                continue
            draw.text((x, y), value, font=font, fill=_token_color(ttype))
            x += draw.textlength(value, font=font)
        y += lh
    y = padding
    for i in range(1, n_lines + 1):
        draw.text((padding, y), str(i), font=font, fill="#4b5263")
        y += lh
    return img

def _render_text_output_image(text, width, font_size=18, padding=24):
    font = ImageFont.truetype(FONT_PATH, font_size)
    lh = int(font_size * 1.4)
    lines = text.rstrip("\n").split("\n") or [""]
    height = len(lines) * lh + padding * 2
    img = Image.new("RGB", (width, height), "#1a1d21")
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill="#d4d4d4")
        y += lh
    return img

def _looks_like_pdf_import_cell(src):
    return "PDF_PAGES" in src and "fitz.open" in src

def _build_code_pages_from_history(history_entries):
    """history_entries: list of {"code": src, "cell_id": id_or_None}."""
    shared_ns = {}
    code_pages = []
    skip_notes = []
    for i, entry in enumerate(history_entries):
        src = entry["code"] or ""
        cell_id = entry.get("cell_id")
        stripped = src.strip()
        if not stripped:
            continue
        if stripped.startswith("# NOSLIDE"):
            skip_notes.append((i, "marked # NOSLIDE"))
            continue
        if _looks_like_pdf_import_cell(src):
            skip_notes.append((i, "detected as PDF-import cell"))
            continue

        clean_lines = [l for l in src.split("\n")
                        if not l.strip().startswith("!") and "files.upload(" not in l]
        clean_src = "\n".join(clean_lines)
        if not clean_src.strip():
            continue

        buf_out = io.StringIO()
        plt.close("all")
        try:
            with contextlib.redirect_stdout(buf_out):
                exec(clean_src, shared_ns)
        except Exception as e:
            skip_notes.append((i, f"raised {type(e).__name__}: {e}"))
            print(f"Skipped a cell that raised {type(e).__name__}: {e}")
            continue
        stdout_text = buf_out.getvalue()

        code_img = _render_code_image(src)
        output_img = None
        if plt.get_fignums():
            fig = plt.gcf()
            fig_buf = io.BytesIO()
            fig.savefig(fig_buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
            fig_buf.seek(0)
            output_img = Image.open(fig_buf).convert("RGB")
            plt.close("all")
        elif stdout_text.strip():
            output_img = _render_text_output_image(stdout_text, width=code_img.width)

        if output_img is not None:
            gap = 16
            combined_width = max(code_img.width, output_img.width)
            combined_height = code_img.height + gap + output_img.height
            combined = Image.new("RGB", (combined_width, combined_height), "#1a1d21")
            combined.paste(code_img, (0, 0))
            out_x = (combined_width - output_img.width) // 2
            combined.paste(output_img, (out_x, code_img.height + gap))
        else:
            combined = code_img

        buf = io.BytesIO()
        combined.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        code_pages.append({"src": b64, "cellId": cell_id})

    return code_pages, skip_notes

# Colab's kernel tracks which cell ID produced each execution (its own
# ColabHistoryManager, separate from stock IPython's `In`), which is what
# lets each code slide link back to the exact cell that made it. Fall back
# to plain `In` (no cell IDs, so no "go to cell" links) if that's not
# available — e.g. outside Colab.
try:
    _raw_history = list(get_ipython().history_manager._input_hist_cells)
    _entries = [{"code": h.get("code") or "", "cell_id": h.get("cell_id") or None}
                for h in _raw_history[1:-1]]
except AttributeError:
    _entries = [{"code": src, "cell_id": None} for src in list(In)[1:-1]]

# If a cell was re-run (edited or not), collapse it to just its most recent
# execution. Dedupe by cell_id when we have one (correctly handles edits —
# same cell, different code); fall back to exact-text matching otherwise.
_last_index_of = {}
for _i, _entry in enumerate(_entries):
    _key = _entry["cell_id"] or _entry["code"]
    _last_index_of[_key] = _i
_kept_indices = sorted(_last_index_of.values())
_entries = [_entries[_i] for _i in _kept_indices]

CODE_PAGES, _skip_notes = _build_code_pages_from_history(_entries)
print(f"Built {len(CODE_PAGES)} code slide(s) from {len(_entries)} prior cell(s) "
      f"({len(_skip_notes)} skipped).")

_PDF_PAGES = [{"src": p, "cellId": None} for p in (PDF_PAGES if "PDF_PAGES" in dir() else [])]
ALL_SLIDES = _PDF_PAGES + CODE_PAGES
print(f"Combined deck: {len(ALL_SLIDES)} slide(s) total "
      f"({len(_PDF_PAGES)} from PDF, {len(CODE_PAGES)} from replayed code).")

from IPython.display import HTML, display

slides_json = json.dumps(ALL_SLIDES)
notebook_url_json = json.dumps(NOTEBOOK_URL if "NOTEBOOK_URL" in dir() else "")

deck_html = f"""
<style>
  #deck-wrap {{ font-family: sans-serif; }}
  #toolbar {{ display:flex; gap:8px; margin-bottom:12px; align-items:center; }}
  #toolbar button {{ padding:8px 16px; border-radius:6px; border:1px solid #444; background:#20232a; color:#eee; cursor:pointer; font-size:0.9em; }}
  #toolbar button.active {{ background:#2f5d50; border-color:#2f5d50; }}
  #mode-note {{ color:#888; font-size:0.85em; margin-left:8px; }}

  #edit-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap:20px; }}
  .thumb {{ position:relative; background:#111; border-radius:8px; overflow:hidden; border:1px solid #333; cursor:grab; transition: transform 0.12s, box-shadow 0.12s; }}
  .thumb:active {{ cursor:grabbing; }}
  .thumb.dragging {{ opacity:0.35; }}
  .thumb.drag-over {{ transform: scale(1.03); box-shadow: 0 0 0 3px #2f5d50; }}
  .thumb img {{ width:100%; display:block; aspect-ratio: 16/9; object-fit:cover; pointer-events:none; }}
  .thumb-controls {{ display:flex; justify-content:space-between; align-items:center; padding:8px; background:#1a1a1a; gap:6px; }}
  .thumb-controls button {{ background:#2a2a2a; color:#eee; border:none; border-radius:4px; width:34px; height:32px; cursor:pointer; font-size:1em; flex-shrink:0; }}
  .thumb-controls button:disabled {{ opacity:0.25; cursor:not-allowed; }}
  .thumb-controls button.del {{ background:#5a2323; }}
  .thumb-controls a.goto {{ background:#1f3a5f; color:#9cc4ff; border-radius:4px; height:32px; padding:0 10px; display:flex; align-items:center; justify-content:center; font-size:0.8em; text-decoration:none; white-space:nowrap; flex-shrink:0; cursor:pointer; border:none; }}
  .thumb-controls a.goto:hover {{ background:#2a4d7a; }}
  .thumb-num {{ position:absolute; top:8px; left:8px; background:rgba(0,0,0,0.7); color:#fff; font-size:0.8em; padding:3px 9px; border-radius:10px; }}

  .goto-toast {{ display:none; align-items:center; gap:8px; flex-wrap:wrap; background:#1a2e42; border:1px solid #2a4d7a; border-radius:6px; padding:10px 14px; margin-bottom:14px; font-size:0.85em; color:#cfe3ff; }}
  .goto-toast.visible {{ display:flex; }}
  .goto-toast input {{ flex:1; min-width:160px; background:#0d1620; border:1px solid #2a4d7a; border-radius:4px; color:#eee; padding:6px 10px; font-family:ui-monospace,monospace; font-size:0.95em; }}
  .goto-toast button {{ background:#2a4d7a; color:#fff; border:none; border-radius:4px; padding:6px 12px; cursor:pointer; font-size:0.85em; }}
  .goto-toast button.close {{ background:transparent; color:#9cc4ff; font-size:1.1em; padding:2px 8px; }}

  #present-panel {{ display:none; width: 96%; margin: 0 auto; position: relative; }}
  #present-panel.visible {{ display:block; }}
  #edit-grid.hidden {{ display:none; }}
  .present-box {{ width: 100%; padding-bottom: 56.25%; position: relative; background: #0d0d0f; border-radius: 8px; }}
  .present-inner {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 2%; box-sizing: border-box; overflow: hidden; }}
  .present-inner.scrollable {{ align-items: flex-start; overflow-y: auto; overflow-x: hidden; }}
  .present-inner img {{ border-radius:6px; box-shadow:0 6px 24px rgba(0,0,0,0.5); }}
  .present-inner:not(.scrollable) img {{ width:100%; height:100%; object-fit:contain; }}
  .present-inner.scrollable img {{ width:100%; height:auto; display:block; }}
  .scroll-hint {{ position:absolute; bottom:8px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,0.6); color:#9cc4ff; font-size:0.75em; padding:3px 10px; border-radius:10px; pointer-events:none; opacity:0; transition:opacity 0.2s; }}
  .scroll-hint.visible {{ opacity:1; }}
  .present-counter {{ position: absolute; bottom: 10px; right: 16px; color: #aaa; font-size: 0.85em; }}
  .present-goto-btn {{ position:absolute; bottom:10px; left:16px; background:#1f3a5f; color:#9cc4ff; border:none; border-radius:6px; padding:6px 14px; font-size:0.85em; cursor:pointer; display:none; }}
  .present-goto-btn.visible {{ display:inline-block; }}
  .present-goto-btn:hover {{ background:#2a4d7a; }}
  .present-goto-panel {{ position:absolute; bottom:56px; left:16px; background:#1a2e42; border:1px solid #2a4d7a; border-radius:6px; padding:10px 14px; display:none; align-items:center; gap:8px; font-size:0.85em; color:#cfe3ff; z-index:10; }}
  .present-goto-panel.visible {{ display:flex; }}
  .present-goto-panel input {{ width:180px; background:#0d1620; border:1px solid #2a4d7a; border-radius:4px; color:#eee; padding:6px 10px; font-family:ui-monospace,monospace; font-size:0.9em; }}
  .present-goto-panel button {{ background:#2a4d7a; color:#fff; border:none; border-radius:4px; padding:6px 10px; cursor:pointer; font-size:0.85em; }}
  .present-goto-panel button.close {{ background:transparent; color:#9cc4ff; font-size:1.1em; padding:2px 6px; }}
  .present-arrow {{ position:absolute; top:50%; transform:translateY(-50%); background:rgba(255,255,255,0.12); color:#fff; border:none; border-radius:50%; width:44px; height:44px; font-size:1.3em; cursor:pointer; }}
  .present-arrow.left {{ left:10px; }}
  .present-arrow.right {{ right:10px; }}
  #empty-note {{ color:#888; padding: 40px; text-align:center; }}

  #export-panel {{ display:none; }}
  #export-panel.visible {{ display:block; }}
  .export-box {{ background:#1a1a1a; border:1px solid #333; border-radius:8px; padding:26px; max-width:560px; }}
  .export-box h3 {{ margin-top:0; color:#eee; font-size:1.1em; }}
  .export-box p {{ color:#aaa; font-size:0.9em; line-height:1.55; }}
  .export-box button {{ background:#2f5d50; color:#fff; border:none; border-radius:6px; padding:12px 24px; font-size:0.95em; cursor:pointer; }}
  .export-box button:disabled {{ opacity:0.5; cursor:not-allowed; }}
  #export-status {{ margin-top:14px; color:#9cc4ff; font-size:0.85em; min-height:1.2em; }}
</style>

<div id="deck-wrap">
  <div id="toolbar">
    <button id="btn-edit" class="active">Edit</button>
    <button id="btn-present">Present</button>
    <button id="btn-export">Export</button>
    <span id="mode-note">Edit mode: reorder or delete slides below.</span>
  </div>

  <div id="goto-toast" class="goto-toast">
    <span>Paste after # in your browser's address bar, then press Enter:</span>
    <input id="goto-toast-input" readonly onclick="this.select()">
    <button id="goto-toast-copy">Copy</button>
    <button id="goto-toast-close" class="close">&times;</button>
  </div>

  <div id="edit-grid"></div>

  <div id="present-panel">
    <div class="present-box">
      <div class="present-inner" id="present-inner"><img id="present-img"></div>
      <div class="scroll-hint" id="scroll-hint">&#8595; scroll for more</div>
      <div class="present-counter" id="present-counter"></div>
      <a class="present-goto-btn" id="present-goto-link" target="_blank" style="display:none;">&#8599; Code cell</a>
      <button class="present-goto-btn" id="present-goto-btn">&#8599; Code cell link</button>
      <div class="present-goto-panel" id="present-goto-panel">
        <span>Paste after #:</span>
        <input id="present-goto-input" readonly onclick="this.select()">
        <button id="present-goto-copy">Copy</button>
        <button id="present-goto-close" class="close">&times;</button>
      </div>
      <button class="present-arrow left" id="btn-prev">&#8592;</button>
      <button class="present-arrow right" id="btn-next">&#8594;</button>
    </div>
  </div>

  <div id="export-panel">
    <div class="export-box">
      <h3>Export to PowerPoint</h3>
      <p>Saves the deck exactly as it's currently ordered above (including any
      reordering or deletions you've made) as a <code>.pptx</code> file, one
      slide per image, downloaded to your browser's downloads folder.</p>
      <button id="btn-do-export">Export to PowerPoint (.pptx)</button>
      <div id="export-status"></div>
    </div>
  </div>
</div>

<script>
(function() {{
    // Each slide is {{ src: base64Png, cellId: string|null }}. cellId is only
    // set for code slides whose originating cell we could identify; PDF
    // slides (and any code slide where identification wasn't possible) have
    // cellId: null, and simply don't show a "go to code cell" control.
    let SLIDES = {slides_json};
    let mode = 'edit';
    let presentIdx = 0;

    // If you've set NOTEBOOK_URL (your own notebook's Colab URL, pasted in
    // because the sandboxed output can't read it itself), "go to code cell"
    // becomes a real link that opens a new tab there directly. Without it,
    // it falls back to the copy-paste toast.
    const NOTEBOOK_URL = {notebook_url_json};
    const HAS_NOTEBOOK_URL = !!NOTEBOOK_URL;

    const editGrid = document.getElementById('edit-grid');
    const presentPanel = document.getElementById('present-panel');
    const presentInner = document.getElementById('present-inner');
    const presentImg = document.getElementById('present-img');
    const scrollHint = document.getElementById('scroll-hint');
    const presentCounter = document.getElementById('present-counter');
    const presentGotoBtn = document.getElementById('present-goto-btn');
    const presentGotoLink = document.getElementById('present-goto-link');
    const presentGotoPanel = document.getElementById('present-goto-panel');
    const presentGotoInput = document.getElementById('present-goto-input');
    const gotoToast = document.getElementById('goto-toast');
    const gotoToastInput = document.getElementById('goto-toast-input');
    const btnEdit = document.getElementById('btn-edit');
    const btnPresent = document.getElementById('btn-present');
    const btnExport = document.getElementById('btn-export');
    const exportPanel = document.getElementById('export-panel');
    const btnDoExport = document.getElementById('btn-do-export');
    const exportStatus = document.getElementById('export-status');
    const modeNote = document.getElementById('mode-note');

    function showGotoToast(cellId) {{
        gotoToastInput.value = '#scrollTo=' + cellId;
        gotoToast.classList.add('visible');
        gotoToastInput.focus();
        gotoToastInput.select();
    }}
    document.getElementById('goto-toast-close').addEventListener('click', function() {{
        gotoToast.classList.remove('visible');
    }});
    document.getElementById('goto-toast-copy').addEventListener('click', function(e) {{
        const btn = e.currentTarget;
        gotoToastInput.select();
        try {{
            navigator.clipboard.writeText(gotoToastInput.value).then(function() {{
                btn.textContent = 'Copied!';
                setTimeout(function() {{ btn.textContent = 'Copy'; }}, 1500);
            }}).catch(function() {{ /* clipboard blocked — text is still selected for manual copy */ }});
        }} catch (err) {{ /* clipboard API unavailable — text is still selected for manual copy */ }}
    }});

    function renderEditGrid() {{
        if (SLIDES.length === 0) {{
            editGrid.innerHTML = '<div id="empty-note">No slides. Re-run the setup cells to load some.</div>';
            return;
        }}
        editGrid.innerHTML = SLIDES.map((s, i) => `
            <div class="thumb" draggable="true" data-idx="${{i}}">
                <img src="data:image/png;base64,${{s.src}}">
                <div class="thumb-controls">
                    <button class="up" ${{i === 0 ? 'disabled' : ''}}>&#8593;</button>
                    <button class="down" ${{i === SLIDES.length - 1 ? 'disabled' : ''}}>&#8595;</button>
                    ${{s.cellId ? (HAS_NOTEBOOK_URL
                        ? `<a class="goto" href="${{NOTEBOOK_URL}}#scrollTo=${{s.cellId}}" target="_blank" title="Open this cell in a new tab">&#8599; Code</a>`
                        : `<a class="goto" data-cellid="${{s.cellId}}" title="Show link to this cell">&#8599; Code</a>`
                    ) : ''}}
                    <button class="del">&times;</button>
                </div>
                <div class="thumb-num">${{i + 1}}</div>
            </div>`).join('');
    }}

    function updateScrollHint() {{
        if (!presentInner.classList.contains('scrollable')) {{
            scrollHint.classList.remove('visible');
            return;
        }}
        const atBottom = presentInner.scrollTop + presentInner.clientHeight >= presentInner.scrollHeight - 4;
        scrollHint.classList.toggle('visible', !atBottom);
    }}
    presentInner.addEventListener('scroll', updateScrollHint);

    function renderPresent() {{
        if (SLIDES.length === 0) {{
            presentCounter.textContent = '0 / 0';
            presentImg.src = '';
            presentGotoBtn.classList.remove('visible');
            presentGotoLink.style.display = 'none';
            presentGotoPanel.classList.remove('visible');
            return;
        }}
        const s = SLIDES[presentIdx];
        presentInner.classList.remove('scrollable');
        scrollHint.classList.remove('visible');
        presentImg.onload = function() {{
            const boxW = presentInner.clientWidth;
            const boxH = presentInner.clientHeight;
            const scaleToFit = Math.min(boxW / presentImg.naturalWidth, boxH / presentImg.naturalHeight);
            // If fitting the whole image would shrink it below ~65% of native
            // size, text becomes hard to read — fill the width at full scale
            // instead and let it scroll vertically. A modest shrink (above the
            // threshold) still reads fine, so those keep the normal letterboxed
            // fit with no extra scrolling required.
            const SCALE_THRESHOLD = 0.65;
            if (scaleToFit < SCALE_THRESHOLD) {{
                presentInner.classList.add('scrollable');
                presentInner.scrollTop = 0;
                updateScrollHint();
            }}
        }};
        presentImg.src = 'data:image/png;base64,' + s.src;
        presentCounter.textContent = (presentIdx + 1) + ' / ' + SLIDES.length;
        presentGotoPanel.classList.remove('visible'); // close any open panel when the slide changes

        if (s.cellId && HAS_NOTEBOOK_URL) {{
            presentGotoLink.href = NOTEBOOK_URL + '#scrollTo=' + s.cellId;
            presentGotoLink.style.display = 'inline-block';
            presentGotoBtn.classList.remove('visible');
        }} else if (s.cellId) {{
            presentGotoBtn.classList.add('visible');
            presentGotoBtn.dataset.cellid = s.cellId;
            presentGotoLink.style.display = 'none';
        }} else {{
            presentGotoBtn.classList.remove('visible');
            presentGotoLink.style.display = 'none';
        }}
    }}

    editGrid.addEventListener('click', function(e) {{
        const thumb = e.target.closest('.thumb');
        if (!thumb) return;
        const i = parseInt(thumb.dataset.idx, 10);
        if (e.target.classList.contains('up') && i > 0) {{
            [SLIDES[i - 1], SLIDES[i]] = [SLIDES[i], SLIDES[i - 1]];
            renderEditGrid();
        }} else if (e.target.classList.contains('down') && i < SLIDES.length - 1) {{
            [SLIDES[i + 1], SLIDES[i]] = [SLIDES[i], SLIDES[i + 1]];
            renderEditGrid();
        }} else if (e.target.classList.contains('del')) {{
            SLIDES.splice(i, 1);
            if (presentIdx >= SLIDES.length) presentIdx = Math.max(0, SLIDES.length - 1);
            renderEditGrid();
        }} else if (e.target.classList.contains('goto') && e.target.dataset.cellid) {{
            showGotoToast(e.target.dataset.cellid);
        }}
        // if it's the real-link variant (has href, no data-cellid), the browser
        // handles the click itself — nothing for us to do here
    }});

    let dragSrcIdx = null;

    editGrid.addEventListener('dragstart', function(e) {{
        const thumb = e.target.closest('.thumb');
        if (!thumb) return;
        dragSrcIdx = parseInt(thumb.dataset.idx, 10);
        thumb.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
    }});

    editGrid.addEventListener('dragend', function(e) {{
        const thumb = e.target.closest('.thumb');
        if (thumb) thumb.classList.remove('dragging');
        editGrid.querySelectorAll('.thumb.drag-over').forEach(el => el.classList.remove('drag-over'));
        dragSrcIdx = null;
    }});

    editGrid.addEventListener('dragover', function(e) {{
        e.preventDefault();
        const thumb = e.target.closest('.thumb');
        if (!thumb || dragSrcIdx === null) return;
        editGrid.querySelectorAll('.thumb.drag-over').forEach(el => el.classList.remove('drag-over'));
        const targetIdx = parseInt(thumb.dataset.idx, 10);
        if (targetIdx !== dragSrcIdx) thumb.classList.add('drag-over');
    }});

    editGrid.addEventListener('drop', function(e) {{
        e.preventDefault();
        const thumb = e.target.closest('.thumb');
        if (!thumb || dragSrcIdx === null) return;
        const targetIdx = parseInt(thumb.dataset.idx, 10);
        if (targetIdx !== dragSrcIdx) {{
            const [moved] = SLIDES.splice(dragSrcIdx, 1);
            SLIDES.splice(targetIdx, 0, moved);
            if (presentIdx === dragSrcIdx) presentIdx = targetIdx;
            renderEditGrid();
        }}
        dragSrcIdx = null;
    }});

    function setMode(newMode) {{
        mode = newMode;
        editGrid.classList.add('hidden');
        presentPanel.classList.remove('visible');
        exportPanel.classList.remove('visible');
        btnEdit.classList.remove('active');
        btnPresent.classList.remove('active');
        btnExport.classList.remove('active');

        if (mode === 'present') {{
            presentPanel.classList.add('visible');
            btnPresent.classList.add('active');
            modeNote.textContent = 'Present mode: \u2190 / \u2192 to move between slides.';
            renderPresent();
        }} else if (mode === 'export') {{
            exportPanel.classList.add('visible');
            btnExport.classList.add('active');
            modeNote.textContent = 'Export mode: saves the deck in its current order.';
        }} else {{
            editGrid.classList.remove('hidden');
            btnEdit.classList.add('active');
            modeNote.textContent = 'Edit mode: reorder or delete slides below.';
            renderEditGrid();
        }}
    }}

    btnEdit.addEventListener('click', () => setMode('edit'));
    btnPresent.addEventListener('click', () => setMode('present'));
    btnExport.addEventListener('click', () => setMode('export'));

    function computeLetterbox(imgW, imgH, boxW, boxH) {{
        const imgRatio = imgW / imgH;
        const boxRatio = boxW / boxH;
        let w, h;
        if (imgRatio > boxRatio) {{
            w = boxW;
            h = boxW / imgRatio;
        }} else {{
            h = boxH;
            w = boxH * imgRatio;
        }}
        return {{ x: (boxW - w) / 2, y: (boxH - h) / 2, w, h }};
    }}

    function getImageNaturalSize(b64) {{
        return new Promise(function(resolve, reject) {{
            const img = new Image();
            img.onload = function() {{ resolve({{ w: img.naturalWidth, h: img.naturalHeight }}); }};
            img.onerror = function() {{ reject(new Error('Could not read image dimensions')); }};
            img.src = 'data:image/png;base64,' + b64;
        }});
    }}

    function ensurePptxGenLoaded() {{
        return new Promise(function(resolve, reject) {{
            if (window.PptxGenJS) {{ resolve(); return; }}
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/gh/gitbrent/pptxgenjs@3.12.0/dist/pptxgen.bundle.js';
            script.onload = function() {{ resolve(); }};
            script.onerror = function() {{ reject(new Error('Could not load the PowerPoint library from the CDN — check your internet connection.')); }};
            document.head.appendChild(script);
        }});
    }}

    async function exportToPptx() {{
        if (SLIDES.length === 0) {{
            exportStatus.textContent = 'No slides to export.';
            return;
        }}
        btnDoExport.disabled = true;
        try {{
            exportStatus.textContent = 'Loading PowerPoint library...';
            await ensurePptxGenLoaded();

            const pres = new window.PptxGenJS();
            pres.layout = 'LAYOUT_16x9';
            const SLIDE_W = 10, SLIDE_H = 5.625;

            for (let i = 0; i < SLIDES.length; i++) {{
                exportStatus.textContent = `Building slide ${{i + 1}} / ${{SLIDES.length}}...`;
                const s = SLIDES[i];
                const dims = await getImageNaturalSize(s.src);
                const box = computeLetterbox(dims.w, dims.h, SLIDE_W, SLIDE_H);
                const slide = pres.addSlide();
                slide.background = {{ color: '0D0D0F' }};
                slide.addImage({{ data: 'data:image/png;base64,' + s.src, x: box.x, y: box.y, w: box.w, h: box.h }});
            }}

            exportStatus.textContent = 'Saving file...';
            await pres.writeFile({{ fileName: 'presentation.pptx' }});
            exportStatus.textContent = `Done — ${{SLIDES.length}} slide(s) saved as presentation.pptx. Check your downloads.`;
        }} catch (err) {{
            exportStatus.textContent = 'Export failed: ' + err.message;
        }} finally {{
            btnDoExport.disabled = false;
        }}
    }}

    btnDoExport.addEventListener('click', exportToPptx);

    document.getElementById('btn-next').addEventListener('click', function() {{
        if (presentIdx < SLIDES.length - 1) {{ presentIdx++; renderPresent(); }}
    }});
    document.getElementById('btn-prev').addEventListener('click', function() {{
        if (presentIdx > 0) {{ presentIdx--; renderPresent(); }}
    }});
    document.addEventListener('keydown', function(e) {{
        if (mode !== 'present') return;
        if (e.key === 'ArrowRight') document.getElementById('btn-next').click();
        if (e.key === 'ArrowLeft') document.getElementById('btn-prev').click();
    }});

    presentGotoBtn.addEventListener('click', function(e) {{
        e.stopPropagation();
        presentGotoInput.value = '#scrollTo=' + presentGotoBtn.dataset.cellid;
        presentGotoPanel.classList.add('visible');
        presentGotoInput.focus();
        presentGotoInput.select();
    }});
    document.getElementById('present-goto-close').addEventListener('click', function(e) {{
        e.stopPropagation();
        presentGotoPanel.classList.remove('visible');
    }});
    document.getElementById('present-goto-copy').addEventListener('click', function(e) {{
        e.stopPropagation();
        const btn = e.currentTarget;
        presentGotoInput.select();
        try {{
            navigator.clipboard.writeText(presentGotoInput.value).then(function() {{
                btn.textContent = 'Copied!';
                setTimeout(function() {{ btn.textContent = 'Copy'; }}, 1500);
            }}).catch(function() {{ /* clipboard blocked — text is still selected for manual copy */ }});
        }} catch (err) {{ /* clipboard API unavailable — text is still selected for manual copy */ }}
    }});

    document.getElementById('deck-wrap').addEventListener('click', function(e) {{
        if (e.target.closest('.present-goto-panel') || e.target.closest('#present-goto-btn') || e.target.closest('#present-goto-link')) return;
        if (mode === 'present' && e.target.tagName !== 'BUTTON') {{
            presentPanel.requestFullscreen && presentPanel.requestFullscreen().catch(function(){{}});
        }}
    }});

    renderEditGrid();
}})();
</script>
"""

display(HTML(deck_html))