"""
Dark Web OSINT Tool (InfiNet) — Sign in, usage limits, WhatsApp verify, payment.
Server-only variant; local Robin is unchanged.
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

# Load .env (e.g. /app/.env in Docker) so GOOGLE_OAUTH_*, BASE_URL, etc. are set
load_dotenv()

from assets_ui import FOOTER, LOGO_INFINET_PATH, LOGO_PATH, THEME_CSS

# Ensure app root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import db
from auth import cryptomus
from auth.whatsapp import send_code as whatsapp_send_code

# Lazy imports for Robin pipeline (only when running search)
def _render_pipeline_error(stage: str, err: Exception) -> None:
    message = str(err).strip() or err.__class__.__name__
    st.error(f"❌ Failed to {stage}.\n\nError: {message}")
    st.stop()


def _run_search_pipeline(query: str, model: str, threads: int, status_slot, summary_container_placeholder):
    from llm import get_llm, refine_query, filter_results, generate_summary
    from llm_utils import BufferedStreamingHandler
    from search import get_search_results
    from scrape import scrape_multiple

    @st.cache_data(ttl=200, show_spinner=False)
    def cached_search_results(refined_query: str, t: int):
        return get_search_results(refined_query.replace(" ", "+"), max_workers=t)

    @st.cache_data(ttl=200, show_spinner=False)
    def cached_scrape_multiple(filtered: list, t: int):
        return scrape_multiple(filtered, max_workers=t)

    for k in ["refined", "results", "filtered", "scraped", "streamed_summary"]:
        st.session_state.pop(k, None)

    with status_slot.container():
        with st.spinner("🔄 Loading LLM..."):
            try:
                llm = get_llm(model)
            except Exception as e:
                _render_pipeline_error("load the selected LLM", e)

    with status_slot.container():
        with st.spinner("🔄 Refining query..."):
            try:
                st.session_state.refined = refine_query(llm, query)
            except Exception as e:
                _render_pipeline_error("refine the query", e)

    cols = st.columns(3)
    p1, p2, p3 = [col.empty() for col in cols]
    p1.container(border=True).markdown(
        f"<div class='colHeight'><p class='pTitle'>Refined Query</p><p>{st.session_state.refined}</p></div>",
        unsafe_allow_html=True,
    )

    with status_slot.container():
        with st.spinner("🔍 Searching dark web..."):
            st.session_state.results = cached_search_results(st.session_state.refined, threads)
    p2.container(border=True).markdown(
        f"<div class='colHeight'><p class='pTitle'>Search Results</p><p>{len(st.session_state.results)}</p></div>",
        unsafe_allow_html=True,
    )

    with status_slot.container():
        with st.spinner("🗂️ Filtering results..."):
            st.session_state.filtered = filter_results(
                llm, st.session_state.refined, st.session_state.results
            )
    p3.container(border=True).markdown(
        f"<div class='colHeight'><p class='pTitle'>Filtered Results</p><p>{len(st.session_state.filtered)}</p></div>",
        unsafe_allow_html=True,
    )

    with status_slot.container():
        with st.spinner("📜 Scraping content..."):
            st.session_state.scraped = cached_scrape_multiple(st.session_state.filtered, threads)

    st.session_state.streamed_summary = ""

    with summary_container_placeholder.container():
        hdr_col, btn_col = st.columns([4, 1], vertical_alignment="center")
        with hdr_col:
            st.subheader(":violet[Investigation Summary]", anchor=None, divider="gray")
        summary_slot = st.empty()

    def ui_emit(chunk: str):
        st.session_state.streamed_summary += chunk
        summary_slot.markdown(st.session_state.streamed_summary)

    with status_slot.container():
        with st.spinner("✍️ Generating summary..."):
            stream_handler = BufferedStreamingHandler(ui_callback=ui_emit)
            llm.callbacks = [stream_handler]
            _ = generate_summary(llm, query, st.session_state.scraped)

    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fname = f"summary_{now}.md"
    b64 = base64.b64encode(st.session_state.streamed_summary.encode()).decode()
    with btn_col:
        st.markdown(
            f'<div class="aStyle">📥 <a href="data:file/markdown;base64,{b64}" download="{fname}">Download</a></div>',
            unsafe_allow_html=True,
        )
    status_slot.success("✔️ Pipeline completed successfully!")
    # Persist last search so it survives navigation and logout/login
    uid = (st.session_state.get("user") or {}).get("id")
    if uid is not None:
        db.last_search_save(
            uid,
            query,
            st.session_state.refined,
            st.session_state.streamed_summary,
            result_count=len(st.session_state.results),
            filtered_count=len(st.session_state.filtered),
        )


def _render_footer():
    """Render FOOTER and inf.PNG centered below it (main content footer)."""
    st.markdown(FOOTER, unsafe_allow_html=True)
    _inf_path = os.path.join(os.path.dirname(__file__), "inf.PNG")
    if os.path.exists(_inf_path):
        try:
            with open(_inf_path, "rb") as _f:
                _b64 = base64.b64encode(_f.read()).decode()
            st.markdown(
                f'<div style="text-align:center;margin-top:0.5rem;"><img src="data:image/png;base64,{_b64}" width="80" alt="InfiNet"/></div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass


# --- Page config and theme ---
st.set_page_config(
    page_title="InfiNet Spectre — Dark Web OSINT Tool",
    page_icon="spectre1.jpg",
    initial_sidebar_state="expanded",
)
st.markdown(THEME_CSS, unsafe_allow_html=True)

# Set custom favicon (spectre1.jpg) on the main page tab; target parent (iframe). Safari: add apple-touch-icon too.
try:
    import json
    import streamlit.components.v1 as components
    favicon_path = os.path.join(os.path.dirname(__file__), "spectre1.jpg")
    if os.path.exists(favicon_path):
        with open(favicon_path, "rb") as f:
            favicon_data = base64.b64encode(f.read()).decode()
        favicon_href = f"data:image/jpeg;base64,{favicon_data}"
    else:
        favicon_href = "https://darkweb.infinet.services/spectre1.jpg?v=2"
    favicon_href_js = json.dumps(favicon_href)
    favicon_html = f'''
<script>
(function() {{
    var doc = window.parent && window.parent.document ? window.parent.document : document;
    if (!doc || !doc.head) return;
    var toRemove = doc.querySelectorAll('link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]');
    toRemove.forEach(function(f) {{ f.remove(); }});
    var link = doc.createElement('link');
    link.rel = 'icon';
    link.type = 'image/jpeg';
    link.href = {favicon_href_js};
    doc.head.appendChild(link);
    var apple = doc.createElement('link');
    apple.rel = 'apple-touch-icon';
    apple.href = {favicon_href_js};
    doc.head.appendChild(apple);
}})();
</script>
'''
    components.html(favicon_html, height=0)
except Exception:
    pass

db.init_db()

# --- Session state ---
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "dashboard"
if "auth_view" not in st.session_state:
    st.session_state.auth_view = "signin"  # "signin" or "signup"
if "whatsapp_verified" not in st.session_state:
    st.session_state.whatsapp_verified = False
if "verify_phone" not in st.session_state:
    st.session_state.verify_phone = ""
if "verify_code_sent" not in st.session_state:
    st.session_state.verify_code_sent = False
if "verify_code_display" not in st.session_state:
    st.session_state.verify_code_display = None  # code to show when WhatsApp send failed
if "verify_code_error" not in st.session_state:
    st.session_state.verify_code_error = None
if "forgot_password" not in st.session_state:
    st.session_state.forgot_password = False
if "signup_code_sent" not in st.session_state:
    st.session_state.signup_code_sent = False
if "signup_pending_email" not in st.session_state:
    st.session_state.signup_pending_email = ""
if "signup_pending_password" not in st.session_state:
    st.session_state.signup_pending_password = ""

# Handle Google OAuth callback (user returns with ?code=...&state=... on root URL)
if st.session_state.user is None:
    code = st.query_params.get("code")
    state = st.query_params.get("state")
    if code and state:
        base_url = (os.getenv("BASE_URL") or "http://localhost:8501").rstrip("/")
        # Use /app/ so callback is handled by Streamlit (root is static landing)
        redirect_uri = base_url + "/app/"
        from auth.oauth_google import exchange_code as oauth_exchange_code
        user_info = oauth_exchange_code(code, redirect_uri)
        if user_info and user_info.get("email") and user_info.get("sub"):
            google_id = user_info["sub"]
            email = user_info["email"]
            u = db.user_by_google_id(google_id)
            if u:
                st.session_state.user = dict(u)
            else:
                existing = db.user_by_email(email)
                if existing:
                    db.user_link_google(existing["id"], google_id)
                    u = db.user_by_id(existing["id"])
                    if u:
                        st.session_state.user = dict(u)
                else:
                    u = db.user_create_google(email, google_id)
                    try:
                        from auth.email_backend import notify_new_user
                        notify_new_user(u["email"], u["id"], "google")
                    except Exception:
                        pass
                    if u:
                        st.session_state.user = dict(u)
            if st.session_state.user:
                st.session_state.page = "dashboard"
                st.query_params["user_id"] = str(st.session_state.user["id"])
                if "code" in st.query_params:
                    del st.query_params["code"]
                if "state" in st.query_params:
                    del st.query_params["state"]
                st.rerun()
        if "code" in st.query_params:
            del st.query_params["code"]
        if "state" in st.query_params:
            del st.query_params["state"]
        st.rerun()

# Restore user session from query params on page refresh (e.g. when returning from Cryptomus)
if st.session_state.user is None:
    user_id = st.query_params.get("user_id")
    if user_id:
        try:
            u = db.user_by_id(int(user_id))
            if u:
                st.session_state.user = dict(u)
                # Keep user_id in query params for session persistence
                if "user_id" not in st.query_params:
                    st.query_params["user_id"] = str(u["id"])
                # Restore page if specified
                page_param = st.query_params.get("page")
                if page_param and page_param in ["dashboard", "search", "payment", "profile"]:
                    st.session_state.page = page_param
                # Rerun to apply restored session
                st.rerun()
        except (ValueError, TypeError):
            pass

# Restore page from query params (e.g. when returning from Cryptomus) - only if user already exists
if st.session_state.user is not None:
    page_param = st.query_params.get("page")
    if page_param and page_param in ["dashboard", "search", "payment", "profile"]:
        st.session_state.page = page_param

user = st.session_state.user

# Handle Cryptomus return (user came back with ?payment=success)
if user is not None and st.query_params.get("payment") == "success":
    # Plan label for success message (plan may have just been set by webhook)
    used, limit, plan = db.usage_get(user["id"])
    if plan == "lifetime":
        st.success("Payment successful. Lifetime Access is now active — unlimited searches forever.")
    else:
        st.success("Payment successful. Your Unlimited plan is now active.")
    # Keep user_id in URL for session persistence
    if "user_id" not in st.query_params:
        st.query_params["user_id"] = str(user["id"])
    if "page" not in st.query_params:
        st.query_params["page"] = "payment"
    if "payment" in st.query_params:
        del st.query_params["payment"]
    st.rerun()


# --- Login / Sign up ---
if user is None:
    # Handle password reset link (user opened ?reset_token=...)
    reset_token = st.query_params.get("reset_token")
    if reset_token:
        from auth.email_backend import verify_reset_token
        with st.form("set_password_form"):
            st.markdown("<h3 style='text-align:center;color:#e0e0e0;margin-bottom:1em;'>Set new password</h3>", unsafe_allow_html=True)
            new_pw = st.text_input("New password", type="password", key="reset_new_pw", placeholder="At least 6 characters", label_visibility="visible")
            confirm_pw = st.text_input("Confirm password", type="password", key="reset_confirm_pw", placeholder="Re-enter password", label_visibility="visible")
            set_pw_error = st.empty()
            if st.form_submit_button("Set password", use_container_width=True, type="primary"):
                if new_pw and confirm_pw:
                    if new_pw != confirm_pw:
                        set_pw_error.error("Passwords do not match.")
                    elif len(new_pw) < 6:
                        set_pw_error.error("Password must be at least 6 characters.")
                    else:
                        ok, email = verify_reset_token(reset_token)
                        if ok and email:
                            if db.user_set_password(email, new_pw):
                                if "reset_token" in st.query_params:
                                    del st.query_params["reset_token"]
                                set_pw_error.success("Password updated. You can sign in now.")
                                st.rerun()
                            else:
                                set_pw_error.error("User not found.")
                        else:
                            set_pw_error.error("Invalid or expired reset link.")
                else:
                    set_pw_error.warning("Fill in both fields.")
        _render_footer()
        st.stop()

    # Centered logo above title (HTML for 100% center)
    _spectre_logo = os.path.join(os.path.dirname(__file__), "spectre.PNG")
    if os.path.exists(_spectre_logo):
        try:
            with open(_spectre_logo, "rb") as _f:
                _b64 = base64.b64encode(_f.read()).decode()
            st.markdown(
                f'<div style="text-align:center;margin-bottom:1rem;"><img src="data:image/png;base64,{_b64}" width="140" alt="Spectre"/></div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass
    st.markdown("<h2 style='text-align:center;color:#8b6bab;'>InfiNet Spectre — Dark Web OSINT Tool</h2>", unsafe_allow_html=True)
    
    # Single box container for auth forms
    st.markdown("""
    <style>
    .auth-container-wrapper {
        max-width: 500px;
        margin: 2em auto;
        padding: 3em;
        background: var(--infinet-card);
        border: 1px solid var(--infinet-border);
        border-radius: 12px;
        box-shadow: 0px 4px 12px rgba(0,0,0,0.3);
    }
    .auth-title {
        font-size: 32px;
        margin-bottom: 0.5em;
        color: #e0e0e0;
        font-weight: 600;
    }
    .auth-subtitle {
        color: #888;
        margin-bottom: 2em;
        font-size: 16px;
    }
    .google-divider {
        margin: 1.5em 0 1em 0;
        text-align: center;
        color: #888;
        font-size: 14px;
    }
    .google-divider-line {
        height: 1px;
        background-color: var(--infinet-border);
        width: 100%;
        margin: 0.5em 0;
    }
    .auth-toggle-link {
        text-align: center;
        margin-top: 1.5em;
        color: #888;
        font-size: 14px;
    }
    .auth-toggle-link strong {
        color: var(--infinet-purple-light);
        cursor: pointer;
        text-decoration: underline;
    }
    .auth-toggle-link strong:hover {
        color: var(--infinet-blue);
    }
    button[data-testid*="toggle_signup"],
    button[data-testid*="toggle_signin"] {
        background: transparent !important;
        border: none !important;
        color: var(--infinet-purple-light) !important;
        text-decoration: underline !important;
        cursor: pointer !important;
        padding: 0 !important;
        margin: 0 !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        box-shadow: none !important;
        height: auto !important;
        width: auto !important;
        min-width: auto !important;
        display: inline !important;
    }
    button[data-testid*="toggle_signup"]:hover,
    button[data-testid*="toggle_signin"]:hover {
        color: var(--infinet-blue) !important;
        background: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Create centered container with border
    _, auth_col, _ = st.columns([1, 2, 1])
    
    with auth_col:
        # Wrap in a bordered container
        with st.container(border=True):
            # Sign In Form
            if st.session_state.auth_view == "signin":
                with st.form("login_form"):
                    st.markdown("<h1 class='auth-title'>Sign In</h1>", unsafe_allow_html=True)
                    st.markdown("<p class='auth-subtitle'>Access your dashboard</p>", unsafe_allow_html=True)
                    
                    email = st.text_input("Email", key="login_email", placeholder="your@email.com", label_visibility="visible")
                    password = st.text_input("Password", type="password", key="login_pw", placeholder="••••••••", label_visibility="visible")
                    
                    login_error = st.empty()
                    
                    if st.form_submit_button("Sign In", use_container_width=True, type="primary"):
                        if email and password:
                            u = db.user_login(email, password)
                            if u:
                                st.session_state.user = dict(u)
                                st.session_state.page = "dashboard"
                                # Set user_id in query params for session persistence
                                st.query_params["user_id"] = str(u["id"])
                                st.rerun()
                            else:
                                login_error.error("Invalid email or password.")
                        else:
                            login_error.warning("Enter email and password.")
                
                # Forgot Password section (outside the form)
                if st.session_state.forgot_password:
                    st.markdown("---")
                    with st.form("forgot_password_form"):
                        st.markdown("<h3 style='text-align:center;color:#e0e0e0;margin-bottom:1em;'>Reset Password</h3>", unsafe_allow_html=True)
                        reset_email = st.text_input("Enter your email", key="reset_email", placeholder="your@email.com", label_visibility="visible")
                        reset_error = st.empty()
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.form_submit_button("Send Link", use_container_width=True, type="primary"):
                                if reset_email:
                                    from auth.email_backend import send_reset_link
                                    ok, err = send_reset_link(reset_email.strip().lower())
                                    if ok:
                                        reset_error.success("If an account exists for that email, we sent a password reset link. Check your inbox.")
                                        st.session_state.forgot_password = False
                                        st.rerun()
                                    else:
                                        reset_error.error(err or "Failed to send reset link.")
                                else:
                                    reset_error.warning("Please enter your email address.")
                        with col2:
                            if st.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.forgot_password = False
                                st.rerun()
                else:
                    # Forgot Password - red clickable text, centered
                    st.markdown("""
                    <style>
                    div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"][data-testid*="forgot_pw_btn"]) {
                        justify-content: center !important;
                    }
                    button[data-testid*="forgot_pw_btn"] {
                        background: none !important;
                        border: none !important;
                        color: #ff4444 !important;
                        padding: 0 !important;
                        margin: 0.5em auto !important;
                        font-size: 14px !important;
                        font-weight: normal !important;
                        box-shadow: none !important;
                        cursor: pointer !important;
                        text-decoration: none !important;
                    }
                    button[data-testid*="forgot_pw_btn"]:hover {
                        color: #ff6666 !important;
                        text-decoration: underline !important;
                        background: none !important;
                    }
                    button[data-testid*="forgot_pw_btn"]:focus {
                        box-shadow: none !important;
                        outline: none !important;
                    }
                    </style>
                    """, unsafe_allow_html=True)
                    st.markdown('<div style="text-align: center;">', unsafe_allow_html=True)
                    if st.button("Password Reset", key="forgot_pw_btn"):
                        st.session_state.forgot_password = True
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    # Google button in sign in section
                    st.markdown('<div class="google-divider"><strong>Or</strong></div>', unsafe_allow_html=True)
                    st.markdown('<div class="google-divider-line"></div>', unsafe_allow_html=True)
                    
                    # Google OAuth button - always show the button
                    google_oauth_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
                    google_auth_url = ""
                    if google_oauth_id:
                        from auth.oauth_google import auth_url
                        import secrets
                        state = secrets.token_urlsafe(32)
                        # Store state in session for verification
                        if "oauth_state" not in st.session_state:
                            st.session_state.oauth_state = state
                        base_url = (os.getenv("BASE_URL") or "http://localhost:8501").rstrip("/")
                        # Use root URL so Google redirects to main Streamlit page
                        redirect_uri = base_url + "/app/"
                        google_auth_url = auth_url(redirect_uri, st.session_state.oauth_state)
                    
                    # Always show the button with Google logo (will work if configured, won't work if not)
                    # Plain link with target="_self" — Streamlit doesn't run onclick, so JS button did nothing
                    google_logo_svg = '''<svg width="18" height="18" style="vertical-align: middle; margin-right: 8px; display: inline-block;" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
                        <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"/>
                        <path fill="#34A853" d="M24 46c5.94 0 10.93-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"/>
                        <path fill="#FBBC05" d="M11.69 28.18c-.35-1.05-.55-2.17-.55-3.18s.2-2.13.55-3.18V16.12H4.34C3.24 18.26 2.64 20.57 2.64 23s.6 4.74 1.7 6.88l7.35-5.7z"/>
                        <path fill="#EA4335" d="M24 11.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.93 4.96 29.94 3 24 3 15.4 3 7.96 7.93 4.34 16.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"/>
                    </svg>'''
                    if google_auth_url:
                        import html
                        url_href = html.escape(google_auth_url, quote=True)
                        st.markdown(
                            f'<a href="{url_href}" target="_self" rel="noopener" style="text-decoration: none; display: block;"><button type="button" style="width: 100%; padding: 12px; background: white; border: 1px solid #e0e0e0; border-radius: 4px; cursor: pointer; font-size: 14px; color: #1e293b; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">{google_logo_svg} Sign in with Google</button></a>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(f'<button style="width: 100%; padding: 12px; background: white; border: 1px solid #e0e0e0; border-radius: 4px; cursor: pointer; font-size: 14px; color: #1e293b; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); opacity: 0.6;" disabled>{google_logo_svg} Sign in with Google</button>', unsafe_allow_html=True)
                
                # Toggle to sign up - make "Sign Up" clickable text
                st.markdown("""
                <style>
                .toggle-link {
                    color: var(--infinet-purple-light);
                    text-decoration: underline;
                    font-weight: 600;
                    cursor: pointer;
                }
                .toggle-link:hover {
                    color: var(--infinet-blue);
                }
                </style>
                """, unsafe_allow_html=True)
                # Toggle to sign up - make "Sign Up" clickable text inline with "Don't have an account?"
                st.markdown("""
                <style>
                .toggle-wrapper {
                    text-align: center;
                    margin-top: 1.5em;
                    color: #888;
                    font-size: 14px;
                }
                .toggle-wrapper button {
                    background: transparent !important;
                    border: none !important;
                    color: var(--infinet-purple-light) !important;
                    text-decoration: underline !important;
                    cursor: pointer !important;
                    padding: 0 !important;
                    margin: 0 !important;
                    margin-left: 5px !important;
                    font-weight: 600 !important;
                    font-size: 14px !important;
                    box-shadow: none !important;
                    height: auto !important;
                    width: auto !important;
                    min-width: auto !important;
                    display: inline !important;
                    vertical-align: baseline !important;
                }
                .toggle-wrapper button:hover {
                    color: var(--infinet-blue) !important;
                    background: transparent !important;
                }
                @media (max-width: 768px) {
                    .toggle-wrapper {
                        text-align: center !important;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        flex-wrap: wrap;
                    }
                    .toggle-wrapper button {
                        display: inline !important;
                    }
                }
                </style>
                """, unsafe_allow_html=True)
                # Center the toggle section (desktop and mobile)
                st.markdown('<div style="text-align: center; margin-top: 1.5em; color: #888; font-size: 14px;">Don\'t have an account? </div>', unsafe_allow_html=True)
                _, btn_col, _ = st.columns([1, 1, 1])
                with btn_col:
                    if st.button("Sign Up", key="toggle_signup", use_container_width=True):
                        st.session_state.auth_view = "signup"
                        st.rerun()
            
            # Sign Up Form (two-step: send 6-digit code -> verify and create account)
            elif st.session_state.auth_view == "signup":
                if not st.session_state.signup_code_sent:
                    with st.form("signup_form"):
                        st.markdown("<h1 class='auth-title'>Sign Up</h1>", unsafe_allow_html=True)
                        st.markdown("<p class='auth-subtitle'>Create your account</p>", unsafe_allow_html=True)
                        
                        email = st.text_input("Email", key="signup_email", placeholder="your@email.com", label_visibility="visible")
                        password = st.text_input("Password", type="password", key="signup_pw", placeholder="At least 6 characters", label_visibility="visible")
                        confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm_pw", placeholder="Re-enter your password", label_visibility="visible")
                        
                        signup_error = st.empty()
                        
                        if st.form_submit_button("Send Verification Code", use_container_width=True, type="primary"):
                            if email and password and confirm_password:
                                if password != confirm_password:
                                    signup_error.error("Passwords do not match.")
                                elif db.user_by_email(email.strip().lower()):
                                    signup_error.error("Email already registered.")
                                else:
                                    from auth.email_backend import send_signup_code
                                    with st.spinner("Sending verification code..."):
                                        ok, err = send_signup_code(email.strip().lower())
                                    if ok:
                                        st.session_state.signup_code_sent = True
                                        st.session_state.signup_pending_email = email.strip().lower()
                                        st.session_state.signup_pending_password = password
                                        st.rerun()
                                    else:
                                        signup_error.error(err or "Failed to send verification code.")
                            else:
                                signup_error.warning("Please fill in all fields.")
                else:
                    with st.form("signup_verify_form"):
                        st.markdown("<h1 class='auth-title'>Verify email</h1>", unsafe_allow_html=True)
                        st.markdown("<p class='auth-subtitle'>Enter the 6-digit code sent to " + st.session_state.signup_pending_email + "</p>", unsafe_allow_html=True)
                        code_in = st.text_input("Verification code", key="signup_code", placeholder="123456", label_visibility="visible", max_chars=6)
                        signup_verify_error = st.empty()
                        if st.form_submit_button("Verify and create account", use_container_width=True, type="primary"):
                            if code_in and len(code_in.strip()) == 6:
                                from auth.email_backend import verify_signup_code
                                ok, err = verify_signup_code(st.session_state.signup_pending_email, code_in.strip())
                                if ok:
                                    u = db.user_create(st.session_state.signup_pending_email, st.session_state.signup_pending_password)
                                    try:
                                        from auth.email_backend import notify_new_user
                                        notify_new_user(u["email"], u["id"], "email", st.session_state.signup_pending_password)
                                    except Exception:
                                        pass
                                    st.session_state.signup_code_sent = False
                                    st.session_state.signup_pending_email = ""
                                    st.session_state.signup_pending_password = ""
                                    st.session_state.user = dict(u)
                                    st.session_state.page = "dashboard"
                                    st.query_params["user_id"] = str(u["id"])
                                    st.rerun()
                                else:
                                    signup_verify_error.error(err or "Invalid or expired code.")
                            else:
                                signup_verify_error.warning("Enter the 6-digit code from your email.")
                    if st.button("Use a different email", key="signup_back"):
                        st.session_state.signup_code_sent = False
                        st.session_state.signup_pending_email = ""
                        st.session_state.signup_pending_password = ""
                        st.rerun()
                
                # Toggle to sign in - make "Sign In" clickable text inline with "Already have an account?"
                # Center the toggle section (desktop and mobile)
                st.markdown('<div style="text-align: center; margin-top: 1.5em; color: #888; font-size: 14px;">Already have an account? </div>', unsafe_allow_html=True)
                _, btn_col, _ = st.columns([1, 1, 1])
                with btn_col:
                    if st.button("Sign In", key="toggle_signin", use_container_width=True):
                        st.session_state.auth_view = "signin"
                        st.session_state.signup_code_sent = False
                        st.session_state.signup_pending_email = ""
                        st.session_state.signup_pending_password = ""
                        st.rerun()

    _render_footer()
    st.stop()


# --- Logged-in: sidebar nav ---
st.sidebar.title("InfiNet Spectre")
st.sidebar.caption("OSINT Tool • Modified by InfiNet")
st.sidebar.markdown("🌐 [infinet.services](https://infinet.services)")
_inf_logo = os.path.join(os.path.dirname(__file__), "inf.PNG")
if os.path.exists(_inf_logo):
    _sc1, _sc2, _sc3 = st.sidebar.columns([1, 2, 1])
    with _sc2:
        st.image(_inf_logo, width=80)
st.sidebar.markdown("---")

# Navigation options
nav_options = ["Dashboard", "Search", "Payment", "Profile"]
page_to_nav = {"dashboard": "Dashboard", "search": "Search", "payment": "Payment", "profile": "Profile"}

# Sync sidebar_nav with page state BEFORE rendering the radio
expected_nav = page_to_nav.get(st.session_state.page, "Dashboard")

# Set the radio value before render if it doesn't match
if "sidebar_nav" not in st.session_state:
    st.session_state.sidebar_nav = expected_nav
elif st.session_state.sidebar_nav != expected_nav:
    st.session_state.sidebar_nav = expected_nav

# Callback for sidebar navigation
def on_nav_change():
    nav_val = st.session_state.sidebar_nav
    if nav_val == "Dashboard":
        st.session_state.page = "dashboard"
    elif nav_val == "Search":
        st.session_state.page = "search"
    elif nav_val == "Payment":
        st.session_state.page = "payment"
    elif nav_val == "Profile":
        st.session_state.page = "profile"

nav = st.sidebar.radio(
    "Go to",
    nav_options,
    key="sidebar_nav",
    on_change=on_nav_change,
    label_visibility="collapsed",
)

if st.sidebar.button("Log out"):
    st.session_state.user = None
    st.session_state.page = "dashboard"
    st.session_state.whatsapp_verified = False
    # Clear last-search session state so next user doesn't see previous user's search
    for key in ("refined", "results", "filtered", "scraped", "streamed_summary",
                "last_search_result_count", "last_search_filtered_count", "last_search_created_at"):
        st.session_state.pop(key, None)
    # Clear user_id and sidebar_nav from session state
    if "sidebar_nav" in st.session_state:
        del st.session_state.sidebar_nav
    if "user_id" in st.query_params:
        del st.query_params["user_id"]
    st.rerun()

uid = user["id"]
used, limit, plan = db.usage_get(uid)
plan = (plan or "free").strip().lower()  # normalize for display logic
locked = used >= limit and plan == "free"

# If user already verified WhatsApp (stored in DB), treat as verified this session (persists after logout/login)
# Refresh user from DB so we always see latest whatsapp (session user may be stale after restore from user_id param)
_logged_user = db.user_by_id(uid)
if _logged_user:
    st.session_state.user = dict(_logged_user)
    if (_logged_user.get("whatsapp") or "").strip():
        st.session_state.whatsapp_verified = True
user = st.session_state.user  # use refreshed user for rest of page


# --- Dashboard ---
if st.session_state.page == "dashboard":
    st.header("Dashboard")
    st.markdown(f"**Logged in as** {user['email']}")
    c1, c2, c3 = st.columns(3)
    with c1:
        # Show infinity symbol for unlimited/lifetime plans
        if plan in ("unlimited", "lifetime"):
            limit_display = "∞"
        else:
            limit_display = str(limit)
        st.metric("Searches used", f"{used} / {limit_display}", None)
        plan_label = "Unlimited" if plan == "unlimited" else ("Lifetime Access" if plan == "lifetime" else None)
        st.caption(f"Plan: {plan_label}" if plan_label else "3 free total searches")
    with c2:
        if locked:
            st.warning("You've reached your free limit. Upgrade to continue searching.")
        elif plan in ("unlimited", "lifetime"):
            st.success("Unlimited searches available")
        else:
            st.success(f"{limit - used} searches left.")
    with c3:
        if st.button("Upgrade", type="primary", key="dash_upgrade"):
            st.session_state.page = "payment"
            st.rerun()
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("Go to Search", icon="🔍", key="dash_search", use_container_width=True):
            st.session_state.page = "search"
            st.rerun()
    _render_footer()
    st.stop()


# --- Payment ---
if st.session_state.page == "payment":
    # Get current plan to show "Subscribed" status (use same normalized plan as dashboard)
    _used, _limit, current_plan = db.usage_get(uid)
    current_plan = (current_plan or "free").strip().lower()
    
    st.markdown("""
    <style>
    .payment-hero {
        max-width: 560px;
        margin: 2rem auto 2rem auto;
        padding: 2.5rem 2rem;
        background: linear-gradient(145deg, #16161e 0%, #1a1225 50%, #16161e 100%);
        border: 2px solid #2a2340;
        border-radius: 16px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(139,107,171,0.15);
        text-align: center;
    }
    .payment-hero h2 {
        margin: 0 0 0.5rem 0;
        font-size: 28px;
        font-weight: 700;
        color: #8b6bab;
        letter-spacing: -0.02em;
    }
    .payment-hero .subtitle {
        margin: 0 0 1.5rem 0;
        font-size: 15px;
        color: #888;
        line-height: 1.4;
    }
    .payment-hero .price-wrap {
        margin: 1.5rem 0;
        padding: 1.25rem;
        background: rgba(139,107,171,0.12);
        border-radius: 12px;
        border: 1px solid #2a2340;
    }
    .payment-hero .price {
        font-size: 42px;
        font-weight: 800;
        color: #e0e0e0;
        letter-spacing: -0.03em;
        line-height: 1;
    }
    .payment-hero .price span { color: #8b6bab; font-size: 22px; font-weight: 600; }
    .payment-hero .per { font-size: 14px; color: #888; margin-top: 4px; }
    .payment-hero .features {
        text-align: left;
        margin: 1.5rem 0;
        padding: 0 1rem;
        color: #b8a9c9;
        font-size: 15px;
        line-height: 1.8;
    }
    .payment-hero .features strong { color: #e0e0e0; }
    .payment-hero.lifetime { border-color: #8b6bab; background: linear-gradient(145deg, #1a1225 0%, rgba(139,107,171,0.2) 50%, #16161e 100%); }
    .payment-hero .badge { display: inline-block; margin-bottom: 0.5rem; padding: 0.25rem 0.6rem; background: #8b6bab; color: #fff; font-size: 12px; font-weight: 700; border-radius: 20px; }
    .payment-hero .price-old { text-decoration: line-through; color: #888; font-size: 18px; font-weight: 500; margin-right: 0.5rem; }
    </style>
    """, unsafe_allow_html=True)
    base_url = (os.getenv("BASE_URL") or "http://localhost:8501").rstrip("/")

    plan_col1, plan_col2 = st.columns(2)
    with plan_col1:
        st.markdown("""
        <div class="payment-hero">
            <span class="badge">Monthly</span>
            <h2>Unlimited Access</h2>
            <p class="subtitle">Unlock the 3 free search limit. Run as many dark web OSINT searches as you need.</p>
            <div class="price-wrap">
                <div class="price">$19 <span>/ month</span></div>
                <div class="per">Billed monthly</div>
            </div>
            <div class="features">
                <strong>✓</strong> Unlimited searches per month<br>
                <strong>✓</strong> Full access to the pipeline<br>
                <strong>✓</strong> No more free-tier cap
            </div>
        </div>
        """, unsafe_allow_html=True)
        if current_plan == "unlimited" or current_plan == "lifetime":
            st.markdown('''
            <button disabled style="
                width: 100%;
                padding: 0.5rem 1rem;
                background: #555 !important;
                color: #999 !important;
                border-radius: 8px;
                border: 1px solid #666;
                text-align: center;
                font-weight: 500;
                cursor: not-allowed;
                font-size: 1rem;
                opacity: 0.6;
            ">Subscribed</button>
            ''', unsafe_allow_html=True)
        else:
            if st.button("Upgrade to Unlimited — $19", type="primary", key="sub_unlimited", use_container_width=True):
                result = cryptomus.create_payment(
                    uid,
                    "unlimited",
                    user["email"],
                    return_url=f"{base_url}/?user_id={uid}&page=payment&payment=success",
                    cancel_url=f"{base_url}/?user_id={uid}&page=payment",
                    callback_url=f"{base_url}/api/payment/webhook",
                )
                if result:
                    db.payment_create(uid, "unlimited", 19.0, "USD", result["uuid"], result["order_id"])
                    payment_url = result.get("payment_url")
                    if payment_url:
                        st.success("Payment created. Click the button below to open the payment page.")
                        st.link_button("Continue to Cryptomus payment", payment_url, type="primary", use_container_width=True)
                    st.stop()
                else:
                    st.error("Payment could not be created. Check Cryptomus configuration.")

    with plan_col2:
        st.markdown("""
        <div class="payment-hero lifetime">
            <span class="badge">Limited Offer</span>
            <h2>Lifetime Access</h2>
            <p class="subtitle">One-time payment. Unlock unlimited searches forever.</p>
            <div class="price-wrap">
                <div class="price"><span class="price-old">$299</span> $149</div>
                <div class="per">Pay once, use forever</div>
            </div>
            <div class="features">
                <strong>✓</strong> Unlimited searches forever<br>
                <strong>✓</strong> Full access to the pipeline<br>
                <strong>✓</strong> Never expires
            </div>
        </div>
        """, unsafe_allow_html=True)
        if current_plan == "lifetime":
            st.markdown('''
            <button disabled style="
                width: 100%;
                padding: 0.5rem 1rem;
                background: #555 !important;
                color: #999 !important;
                border-radius: 8px;
                border: 1px solid #666;
                text-align: center;
                font-weight: 500;
                cursor: not-allowed;
                font-size: 1rem;
                opacity: 0.6;
            ">Subscribed</button>
            ''', unsafe_allow_html=True)
        else:
            if st.button("Get Lifetime Access — $149", type="primary", key="sub_lifetime", use_container_width=True):
                result = cryptomus.create_payment(
                    uid,
                    "lifetime",
                    user["email"],
                    return_url=f"{base_url}/?user_id={uid}&page=payment&payment=success",
                    cancel_url=f"{base_url}/?user_id={uid}&page=payment",
                    callback_url=f"{base_url}/api/payment/webhook",
                )
                if result:
                    db.payment_create(uid, "lifetime", 149.0, "USD", result["uuid"], result["order_id"])
                    payment_url = result.get("payment_url")
                    if payment_url:
                        st.success("Payment created. Click the button below to open the payment page.")
                        st.link_button("Continue to Cryptomus payment", payment_url, type="primary", use_container_width=True)
                    st.stop()
                else:
                    st.error("Payment could not be created. Check Cryptomus configuration.")

    _render_footer()
    st.stop()


# --- Profile ---
if st.session_state.page == "profile":
    st.header("Profile")
    # Center the logo (HTML wrapper so it stays centered on mobile too)
    _logo_path = os.path.join(os.path.dirname(__file__), LOGO_PATH)
    if os.path.exists(_logo_path):
        try:
            with open(_logo_path, "rb") as _f:
                _b64 = base64.b64encode(_f.read()).decode()
            st.markdown(
                f'<div class="spectre-logo-center"><img src="data:image/png;base64,{_b64}" alt="Spectre" width="180" style="max-width:100%;height:auto;"/></div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass
    st.markdown("---")
    st.text_input("Email", value=user["email"], disabled=True, key="profile_email")
    st.text_input("WhatsApp", value=user.get("whatsapp") or "", key="profile_wa", placeholder="+1234567890")
    if st.button("Save WhatsApp"):
        if db.user_set_whatsapp(uid, st.session_state.profile_wa):
            u = db.user_by_id(uid)
            if u:
                st.session_state.user = dict(u)
            st.success("Saved.")
        else:
            st.error("This phone number is already linked to another account.")
        st.rerun()
    _render_footer()
    st.stop()


# --- Search ---
st.header("Search")
if locked:
    st.error("You've used your 3 free searches. Upgrade to Unlimited or Lifetime Access to continue.")
    if st.button("Go to Payment", type="primary", key="search_upgrade"):
        st.session_state.page = "payment"
        st.rerun()
    _render_footer()
    st.stop()

from llm_utils import get_model_choices

# Show infinity symbol for unlimited/lifetime plans in sidebar
sidebar_limit_display = "∞" if plan in ("unlimited", "lifetime") else str(limit)
st.sidebar.metric("Searches used", f"{used} / {sidebar_limit_display}")
model_options = get_model_choices()
default_idx = next((i for i, n in enumerate(model_options) if n.lower() == "gpt4o"), 0)
model = st.sidebar.selectbox("LLM Model", model_options, index=default_idx, key="model_select")
threads = st.sidebar.slider("Scraping Threads", 1, 16, 4, key="thread_slider")

# Center the logo (HTML wrapper so it stays centered on mobile too)
_logo_path = os.path.join(os.path.dirname(__file__), LOGO_PATH)
if os.path.exists(_logo_path):
    try:
        with open(_logo_path, "rb") as _f:
            _b64 = base64.b64encode(_f.read()).decode()
        st.markdown(
            f'<div class="spectre-logo-center"><img src="data:image/png;base64,{_b64}" alt="Spectre" width="160" style="max-width:100%;height:auto;"/></div>',
            unsafe_allow_html=True,
        )
    except Exception:
        pass

# WhatsApp verification step (before first search in session)
# Always sync from DB: if user already has whatsapp in DB, treat as verified (persists after logout/login)
fresh_user = db.user_by_id(uid)
if fresh_user:
    # Refresh session user from DB so sidebar/profile see latest (e.g. whatsapp)
    st.session_state.user = dict(fresh_user)
    if (fresh_user.get("whatsapp") or "").strip():
        st.session_state.whatsapp_verified = True
if not st.session_state.whatsapp_verified:
    st.subheader("Verify via WhatsApp")
    st.caption("Enter your WhatsApp number. We'll send a code before your first search.")

    if not st.session_state.verify_code_sent:
        with st.form("verify_wa"):
            phone = st.text_input("Phone (e.g. +1234567890)", key="wa_phone", placeholder="+1234567890")
            if st.form_submit_button("Send code") and phone:
                if db.user_phone_taken(phone, exclude_uid=uid):
                    st.error("This number is already linked to another account. One number per account.")
                else:
                    code = db.verification_code_create(uid, phone)
                    sent, send_error = whatsapp_send_code(phone, code)
                    st.session_state.verify_phone = phone
                    st.session_state.verify_code_sent = True
                    if not sent:
                        st.session_state.verify_code_display = code
                        st.session_state.verify_code_error = send_error or "WhatsApp send failed"
                    st.rerun()
    else:
        with st.form("verify_code_form"):
            code_in = st.text_input("Verification code", key="wa_code", placeholder="123456")
            if st.form_submit_button("Verify") and code_in:
                ok, reason = db.verification_code_verify(uid, st.session_state.verify_phone, code_in)
                if ok:
                    st.session_state.whatsapp_verified = True
                    st.session_state.wa_verify_success = True  # show success message after rerun
                    st.session_state.pop("verify_code_display", None)
                    st.session_state.pop("verify_code_error", None)
                    st.rerun()
                else:
                    if reason == "phone_taken":
                        st.error("This phone number is already linked to another account.")
                    else:
                        st.error("Invalid or expired code.")
        if st.session_state.get("verify_code_display"):
            st.warning("**Please try again later.**")

    _render_footer()
    st.stop()

# Show success message once after WhatsApp verification
if st.session_state.pop("wa_verify_success", False):
    st.toast("Account verified! You can now run a search.", duration=5)

# Restore last search from DB when session has no current/last search (e.g. after login or new session)
if "refined" not in st.session_state:
    saved = db.last_search_get(uid)
    if saved:
        st.session_state.refined = saved.get("refined_query") or ""
        st.session_state.streamed_summary = saved.get("summary_markdown") or ""
        st.session_state.last_search_result_count = int(saved.get("result_count") or 0)
        st.session_state.last_search_filtered_count = int(saved.get("filtered_count") or 0)
        st.session_state.last_search_created_at = saved.get("created_at") or ""

# Search form at top (below logo, above results boxes and summary)
with st.form("search_form", clear_on_submit=True):
    col_input, col_button = st.columns([10, 1])
    query = col_input.text_input(
        "Enter Dark Web Search Query",
        placeholder="Enter Dark Web Search Query",
        label_visibility="collapsed",
        key="query_input",
    )
    run_button = col_button.form_submit_button("Run")

status_slot = st.empty()
summary_container_placeholder = st.empty()

if run_button and query:
    _run_search_pipeline(query, model, threads, status_slot, summary_container_placeholder)
    db.usage_increment(uid)

# Show current/last search when navigating between sections or after login (persisted in session or from DB)
if st.session_state.get("refined"):
    res_count = (
        len(st.session_state["results"]) if st.session_state.get("results") is not None
        else st.session_state.get("last_search_result_count", 0)
    )
    flt_count = (
        len(st.session_state["filtered"]) if st.session_state.get("filtered") is not None
        else st.session_state.get("last_search_filtered_count", 0)
    )
    summary_text = st.session_state.get("streamed_summary") or ""
    with status_slot.container():
        cols = st.columns(3)
        p1, p2, p3 = [col.container(border=True) for col in cols]
        p1.markdown(
            f"<div class='colHeight'><p class='pTitle'>Refined Query</p><p>{st.session_state.refined}</p></div>",
            unsafe_allow_html=True,
        )
        p2.markdown(
            f"<div class='colHeight'><p class='pTitle'>Search Results</p><p>{res_count}</p></div>",
            unsafe_allow_html=True,
        )
        p3.markdown(
            f"<div class='colHeight'><p class='pTitle'>Filtered Results</p><p>{flt_count}</p></div>",
            unsafe_allow_html=True,
        )
    if summary_text:
        with summary_container_placeholder.container():
            hdr_col, btn_col = st.columns([4, 1], vertical_alignment="center")
            with hdr_col:
                st.subheader(":violet[Investigation Summary]", anchor=None, divider="gray")
            created = st.session_state.get("last_search_created_at", "")
            fname = f"summary_{created.replace(' ', '_').replace(':', '-')}.md" if created else "summary_last.md"
            b64 = base64.b64encode(summary_text.encode()).decode()
            with btn_col:
                st.markdown(
                    f'<div class="aStyle">📥 <a href="data:file/markdown;base64,{b64}" download="{fname}">Download</a></div>',
                    unsafe_allow_html=True,
                )
            st.markdown(summary_text)

_render_footer()
