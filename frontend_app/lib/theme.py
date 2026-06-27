"""Thème visuel partagé du frontend Casapedia — reproduit la maquette HF.

Design system (tokens issus de la maquette Claude Design) :
  - police Inter, fond #F4F6FB, encre #1E293B ;
  - Dashboard : hero header dégradé (badge + titre + sous-titre), SANS emoji ;
  - autres pages : top-bar clair (titre + sous-titre + chip), sans dégradé ;
  - cartes KPI custom (label / valeur+unité / sous-texte) ;
  - cartes-graphiques blanches (rayon 16px, bord #E2E8F0, ombre douce) ;
  - sidebar : logo dégradé + label de section + carte "Données ouvertes".

API :
  inject_css(), hero_header(), topbar(), kpi_cards(), card_title(),
  style_fig(), footer().
"""

import html as _html

import streamlit as st

# ── Tokens ────────────────────────────────────────────────────────────────────
BRAND = "#2B59C3"
BRAND_DARK = "#1E3A8A"
BRAND_LIGHT = "#3D6FD6"
INK = "#1E293B"
INK_SOFT = "#334155"
MUTED = "#64748B"
MUTED_LIGHT = "#94A3B8"
BORDER = "#E2E8F0"
BG = "#F4F6FB"
SURFACE_BLUE = "#F1F4FA"
GRID = "#EEF1F6"

PALETTE = ["#2B59C3", "#4C9A45", "#3D6FD6", "#54A24B", "#EECA3B", "#EE7711", "#E45756", "#94A3B8"]

DPE_COLORS = {
    "A": "#00A84F", "B": "#52B043", "C": "#A8D44A", "D": "#F4E70F",
    "E": "#F4B30F", "F": "#EE7711", "G": "#E52322",
}
SCALE_PRICE = ["#00A84F", "#52B043", "#A8D44A", "#F4E70F", "#F4B30F", "#EE7711", "#E52322"]
SENTIMENT_COLORS = {"Positif": "#4C9A45", "Neutre": "#EECA3B", "Négatif": "#E45756", "Inconnu": "#CBD5E1"}

_FONT = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"


# ── CSS global ────────────────────────────────────────────────────────────────
_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [data-testid="stAppViewContainer"], .stMarkdown,
button, input, select, textarea {{ font-family: {_FONT} !important; }}

[data-testid="stAppViewContainer"] {{ background: {BG}; }}
/* Header fixe Streamlit rendu transparent + non bloquant pour ne pas masquer le contenu */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 0.5rem; }}
.block-container {{ padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1340px; }}

h1, h2, h3, h4 {{ color: {INK}; font-weight: 800; letter-spacing: -0.02em; }}

/* ===== Hero header (Dashboard) ===== */
.cp-hero {{
  position: relative; overflow: hidden;
  padding: 26px 30px 30px; margin: 0 0 20px 0; border-radius: 18px;
  background: linear-gradient(125deg, {BRAND_DARK} 0%, {BRAND} 60%, {BRAND_LIGHT} 100%);
  box-shadow: 0 10px 30px rgba(43,89,195,.24);
}}
.cp-hero::before {{
  content:""; position:absolute; right:-60px; top:-80px; width:280px; height:280px;
  border-radius:50%; background:rgba(255,255,255,.07);
}}
.cp-hero::after {{
  content:""; position:absolute; right:120px; bottom:-120px; width:220px; height:220px;
  border-radius:50%; background:rgba(255,255,255,.05);
}}
.cp-hero-badge {{
  display:inline-block; font-size:11px; font-weight:600; color:#DCE6FB;
  background:rgba(255,255,255,.14); padding:5px 11px; border-radius:20px;
}}
.cp-hero-note {{ font-size:11px; color:#BFD0F2; margin-left:9px; }}
.cp-hero-title {{ font-size:26px; font-weight:800; letter-spacing:-.8px; color:#fff; margin-top:10px; }}
.cp-hero-sub {{ font-size:13px; color:#CFDDF7; margin-top:5px; max-width:620px; }}

/* ===== Top-bar (autres pages) ===== */
.cp-topbar {{
  display:flex; align-items:flex-start; justify-content:space-between;
  gap:18px; flex-wrap:wrap; margin: 0 0 16px 0;
}}
.cp-topbar-title {{ font-size:22px; font-weight:800; letter-spacing:-.6px; color:{INK}; }}
.cp-topbar-sub {{ font-size:12.5px; color:{MUTED}; margin-top:2px; }}
.cp-chip {{
  display:inline-flex; align-items:center; gap:8px; background:#FFFFFF;
  border:1px solid {BORDER}; border-radius:11px; padding:9px 13px;
  font-size:12.5px; color:{MUTED}; box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
.cp-chip-dot {{ width:7px; height:7px; border-radius:50%; background:{BRAND}; }}

/* ===== Cartes KPI ===== */
.cp-kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:4px; }}
.cp-kpi {{
  background:#fff; border:1px solid {BORDER}; border-radius:16px; padding:18px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); transition:box-shadow .18s, transform .18s;
}}
.cp-kpi:hover {{ box-shadow:0 12px 30px rgba(16,24,40,.10); transform:translateY(-2px); }}
.cp-kpi-label {{ font-size:12px; color:{MUTED}; font-weight:600; }}
.cp-kpi-val {{ font-size:30px; font-weight:800; letter-spacing:-1.2px; color:{INK}; margin-top:12px; }}
.cp-kpi-unit {{ font-size:12.5px; font-weight:600; color:{MUTED_LIGHT}; margin-left:6px; }}
.cp-kpi-sub {{ font-size:11px; color:{MUTED_LIGHT}; margin-top:12px; }}
@media (max-width: 1100px) {{ .cp-kpis {{ grid-template-columns:repeat(2,1fr); }} }}

/* ===== Cartes (conteneurs bordés Streamlit -> cartes maquette) ===== */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background:#fff; border:1px solid {BORDER} !important; border-radius:16px;
  padding:20px 22px; box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
.cp-card-title {{ font-size:15px; font-weight:800; letter-spacing:-.3px; color:{INK}; }}
.cp-card-sub {{ font-size:12px; color:{MUTED}; margin-top:3px; margin-bottom:6px; }}

/* ===== Cartes KPI st.metric (fallback si utilisé) ===== */
[data-testid="stMetric"] {{
  background:#fff; border:1px solid {BORDER}; border-radius:16px; padding:1rem 1.15rem;
  box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
[data-testid="stMetricLabel"] p {{ color:{MUTED}; font-weight:600; font-size:.78rem; }}
[data-testid="stMetricValue"] {{ color:{INK}; font-weight:800; }}

/* ===== Sidebar ===== */
[data-testid="stSidebar"] {{ background:#FFFFFF; border-right:1px solid {BORDER}; }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
[data-testid="stSidebarNav"] {{ margin-top:.2rem; }}
.cp-logo {{ display:flex; align-items:center; gap:11px; padding:6px 4px 14px; }}
.cp-logo-sq {{
  width:38px; height:38px; border-radius:11px; flex:0 0 38px;
  background:linear-gradient(150deg,{BRAND},{BRAND_DARK});
  display:flex; align-items:center; justify-content:center; font-size:20px;
  box-shadow:0 6px 16px rgba(43,89,195,.34);
}}
.cp-logo-name {{ font-size:15.5px; font-weight:800; letter-spacing:-.4px; color:{INK}; line-height:1.1; }}
.cp-logo-tag {{ font-size:10.5px; color:{MUTED_LIGHT}; font-weight:500; }}
.cp-side-card {{
  margin-top:10px; padding:14px; border-radius:14px;
  background:linear-gradient(155deg,#EEF3FC,#F7F9FD); border:1px solid #E6EDF9;
}}
.cp-side-card-t {{ font-size:11.5px; font-weight:700; color:{INK}; }}
.cp-side-card-d {{ font-size:10.5px; color:{MUTED}; line-height:1.45; margin-top:4px; }}
.cp-side-card-s {{ display:flex; align-items:center; gap:6px; margin-top:10px; }}
.cp-side-dot {{ width:7px; height:7px; border-radius:50%; background:#54A24B; box-shadow:0 0 0 3px rgba(84,162,75,.18); }}

/* Onglets / dataframes / pied de page */
.stTabs [aria-selected="true"] {{ color:{BRAND} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color:{BRAND} !important; }}
[data-testid="stDataFrame"] {{ border-radius:14px; overflow:hidden; border:1px solid {BORDER}; }}
hr {{ margin:1rem 0; border-color:{BORDER}; }}
.cp-footer {{ color:{MUTED}; font-size:.8rem; margin-top:1.6rem; padding-top:.85rem; border-top:1px dashed {BORDER}; }}

/* Scrollbar */
::-webkit-scrollbar {{ width:10px; height:10px; }}
::-webkit-scrollbar-thumb {{ background:#D7DEEA; border-radius:8px; border:3px solid {BG}; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _esc(s) -> str:
    return _html.escape(str(s)) if s is not None else ""


def sidebar_brand() -> None:
    """Logo + tagline en haut de la sidebar (maquette)."""
    st.markdown(
        f"""
        <div class="cp-logo">
          <div class="cp-logo-sq">🏠</div>
          <div>
            <div class="cp-logo-name">Casapedia</div>
            <div class="cp-logo-tag">Exploring housing insights</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_footer() -> None:
    """Carte 'Données ouvertes' en bas de la sidebar (maquette)."""
    st.markdown(
        """
        <div class="cp-side-card">
          <div class="cp-side-card-t">Données ouvertes</div>
          <div class="cp-side-card-d">DVF · INSEE · ADEME (DPE) · BPE équipements · NLP avis habitants</div>
          <div class="cp-side-card-s">
            <span class="cp-side-dot"></span>
            <span style="font-size:10.5px;color:#64748B;font-weight:500;">Mise à jour T2 2025</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def hero_header(title: str, subtitle: str = "", badge: str = "", note: str = "") -> None:
    """Hero header dégradé (Dashboard) — badge + titre + sous-titre, sans emoji."""
    top = ""
    if badge or note:
        top = (
            '<div style="margin-bottom:4px;">'
            + (f'<span class="cp-hero-badge">{_esc(badge)}</span>' if badge else "")
            + (f'<span class="cp-hero-note">{_esc(note)}</span>' if note else "")
            + "</div>"
        )
    sub = f'<div class="cp-hero-sub">{_esc(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="cp-hero">
          {top}
          <div class="cp-hero-title">{_esc(title)}</div>
          {sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def topbar(title: str, subtitle: str = "", chip: str = "") -> None:
    """Top-bar clair (pages hors dashboard) — titre + sous-titre + chip, sans emoji."""
    chip_html = (
        f'<div class="cp-chip"><span class="cp-chip-dot"></span>{_esc(chip)}</div>'
        if chip else ""
    )
    sub = f'<div class="cp-topbar-sub">{_esc(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="cp-topbar">
          <div>
            <div class="cp-topbar-title">{_esc(title)}</div>
            {sub}
          </div>
          {chip_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_cards(items: list[dict]) -> None:
    """Rangée de cartes KPI (maquette).

    items: liste de dicts {label, value, unit?, sub?}.
    """
    cards = []
    for it in items:
        unit = f'<span class="cp-kpi-unit">{_esc(it.get("unit",""))}</span>' if it.get("unit") else ""
        sub = f'<div class="cp-kpi-sub">{_esc(it.get("sub",""))}</div>' if it.get("sub") else ""
        cards.append(
            f"""<div class="cp-kpi">
              <div class="cp-kpi-label">{_esc(it.get("label",""))}</div>
              <div class="cp-kpi-val">{_esc(it.get("value","—"))}{unit}</div>
              {sub}
            </div>"""
        )
    st.markdown(f'<div class="cp-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def card_title(title: str, subtitle: str = "") -> None:
    """Titre de carte-graphique (à utiliser dans un st.container(border=True))."""
    sub = f'<div class="cp-card-sub">{_esc(subtitle)}</div>' if subtitle else ""
    st.markdown(f'<div class="cp-card-title">{_esc(title)}</div>{sub}', unsafe_allow_html=True)


def footer(text: str) -> None:
    st.markdown(f'<div class="cp-footer">{text}</div>', unsafe_allow_html=True)


def style_fig(fig, height: int | None = None):
    """Gabarit Plotly commun (Inter, fond transparent, grille douce)."""
    fig.update_layout(
        font=dict(family=_FONT, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=PALETTE,
        margin=dict(l=0, r=0, t=6, b=0),
        hoverlabel=dict(bgcolor="#1E293B", font=dict(color="#F8FAFC", family=_FONT, size=12), bordercolor="#1E293B"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED, size=12)),
        xaxis=dict(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER),
        yaxis=dict(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER),
    )
    if height is not None:
        fig.update_layout(height=height)
    return fig
