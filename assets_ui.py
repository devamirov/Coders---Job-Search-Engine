"""Shared UI assets: theme CSS, footer, logo path."""

FOOTER = '''
<div class="infinet-footer">
  <p>OSINT Tool • Modified by InfiNet</p>
  <p style="margin-top: 0.5rem;">🌐 <a href="https://infinet.services" target="_blank" rel="noopener" style="color: var(--infinet-purple-light);">infinet.services</a></p>
</div>
'''

# Purple/dark theme matching robin branded image
THEME_CSS = '''
<style>
  /* Base */
  .stApp { background: linear-gradient(180deg, #0a0a0f 0%, #12121a 50%, #0d0d12 100%); }
  [data-testid="stHeader"] { background: rgba(0,0,0,0.4); }
  .stSidebar { background: linear-gradient(180deg, #1a1225 0%, #0f0a14 100%); }
  [data-testid="stSidebar"] .stMarkdown { color: #b8a9c9; }
  
  /* Accents: deep purple, light blue */
  :root {
    --infinet-purple: #6b4b8a;
    --infinet-purple-light: #8b6bab;
    --infinet-blue: #5b9bd5;
    --infinet-bg: #0a0a0f;
    --infinet-card: #16161e;
    --infinet-border: #2a2340;
  }
  
  .infinet-card {
    background: var(--infinet-card);
    border: 1px solid var(--infinet-border);
    border-radius: 12px;
    padding: 1.25rem;
    margin: 0.75rem 0;
  }
  
  .infinet-title { font-weight: 700; color: var(--infinet-purple-light); font-size: 1.4rem; margin-bottom: 0.5rem; }
  .infinet-muted { color: #888; font-size: 0.9rem; }
  
  .infinet-footer {
    text-align: center;
    padding: 1.5rem;
    margin-top: 2rem;
    color: #6b6b80;
    font-size: 0.85rem;
    border-top: 1px solid var(--infinet-border);
  }
  
  .infinet-footer p { margin: 0; }
  
  /* Buttons */
  .stButton > button {
    background: linear-gradient(135deg, var(--infinet-purple) 0%, #4a3560 100%) !important;
    color: #fff !important;
    border: 1px solid var(--infinet-purple-light) !important;
    border-radius: 8px !important;
  }
  .stButton > button:hover {
    background: linear-gradient(135deg, var(--infinet-purple-light) 0%, var(--infinet-purple) 100%) !important;
    border-color: var(--infinet-blue) !important;
  }
  
  /* Inputs */
  .stTextInput > div > div > input, .stNumberInput > div > div > input {
    background: #12121a !important;
    border: 1px solid var(--infinet-border) !important;
    color: #e0e0e0 !important;
    border-radius: 8px !important;
  }
  
  /* Forms */
  [data-testid="stForm"] { border: 1px solid var(--infinet-border); border-radius: 12px; padding: 1rem; }
  
  .colHeight { max-height: 40vh; overflow-y: auto; text-align: center; }
  .pTitle { font-weight: bold; color: var(--infinet-blue); margin-bottom: 0.5em; }
  .aStyle { font-size: 18px; font-weight: bold; padding: 5px; text-align: center; }
  
  /* Centered logo wrapper (Search + Profile) – works on desktop and mobile */
  .spectre-logo-center { text-align: center; width: 100%; margin: 1rem 0; }
  .spectre-logo-center img { display: inline-block; max-width: 100%; height: auto; }
</style>
'''

LOGO_PATH = "spectre.PNG"
# Profile and search screens both use spectre.PNG (app root)
LOGO_INFINET_PATH = "spectre.PNG"
