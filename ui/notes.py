"""Render a move note (tracker.services.MoveNote) with Streamlit. All model text goes through md()."""

import streamlit as st

from ui.text import md


def _refs(links) -> str:
    return " · ".join(f"[{md(l.label)}]({l.url})" if l.url else md(l.label) for l in links)


def move_note(note, title: str) -> None:
    color = "green" if note.return_pct >= 0 else "red"
    with st.container(border=True):
        st.markdown(f"**{md(title)}** · :{color}[{note.return_pct:+.1f}%] on {note.date} · :gray[{note.scope_label}]")
        st.markdown(md(note.summary))
        for p in note.points:
            refs = _refs(p.sources)
            st.markdown(f"- {md(p.text)}" + (f"  \n  :gray[{refs}]" if refs else ""))
        if note.links:
            st.markdown(":gray[Coverage: " + _refs(note.links) + "]")
        label = "Based on headlines; causes are not confirmed." if note.headline_based else "Based on the company's SEC filing and coverage."
        st.caption(f"AI note, written {note.written}. {label}")
