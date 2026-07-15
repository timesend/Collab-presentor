# pdf_import.py
#
# The PDF-reading half of the live presenter system, hostable remotely
# alongside live_deck.py. In your notebook, wherever you want the PDF
# upload prompt to appear:
#
#   import urllib.request
#   exec(urllib.request.urlopen(
#       "https://raw.githubusercontent.com/<you>/<repo>/<commit-sha>/pdf_import.py"
#   ).read().decode())
#
# As with live_deck.py: point at a specific commit SHA, not a branch, so
# behavior stays pinned and reproducible. This runs via plain exec() (no
# separate globals dict), so it executes in the calling notebook's own
# namespace and leaves PDF_PAGES defined there for later cells — including
# a remotely-fetched live_deck.py — to use, exactly as if pasted inline.
#
# Uses subprocess for the pip install rather than the "!pip install" shell
# shorthand — that shorthand only works when Python literally sits in a
# real notebook cell; once it's inside a string passed to exec(), it's
# parsed by Python's own compiler, which doesn't understand "!" at all.
#
# --- Original cell content below, unchanged apart from that fix ---

# --- PDF import cell (auto-detected and skipped by the final cell — don't mark this one) ---
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "pymupdf", "-q"], check=True)

from google.colab import files
import fitz, base64

print("Upload your PDF (exported from PowerPoint):")
uploaded_pdf = files.upload()
pdf_path = list(uploaded_pdf.keys())[0]

doc = fitz.open(pdf_path)
PDF_PAGES = []
for page in doc:
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    PDF_PAGES.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
doc.close()
print(f"Loaded {len(PDF_PAGES)} slide(s) from {pdf_path}")