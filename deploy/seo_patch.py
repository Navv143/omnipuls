"""Make the site findable on Google: patch Streamlit's index.html (the page search engines fetch) with the Omnipuls
title, a description, link-preview tags and a short readable text, instead of the default "<title>Streamlit</title>"
and an empty page. Run by run_app.sh before the app starts (idempotent). Generic wording only: no setup details.

GOOGLE_SITE_VERIFICATION (environment, optional): the content of Google Search Console's HTML-tag verification.
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

import streamlit

SITE = os.environ.get("SITE_URL", "https://omnipuls.cloud/")
TITLE = "Omnipuls · Live F&O market intelligence for Indian traders"
DESC = ("Omnipuls: live market intelligence for Indian F&O traders. Money flow, unusual activity, sectors, option "
        "chains and live index prices in one dashboard. Private, invite-only access.")
MARK = "<!-- omnipuls-seo -->"


def main():
    f = Path(streamlit.__file__).parent / "static" / "index.html"
    s = f.read_text(encoding="utf-8")
    if MARK in s:                                   # already patched: refresh by removing the old block first
        s = re.sub(rf"{re.escape(MARK)}.*?{re.escape(MARK)}", "", s, flags=re.S)
        s = re.sub(rf"<noscript>{re.escape(MARK)}.*?</noscript>", "", s, flags=re.S)
    s = re.sub(r"<title>.*?</title>", f"<title>{html.escape(TITLE)}</title>", s, count=1, flags=re.S)
    ver = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
    e = html.escape
    head = (f'{MARK}\n<meta name="description" content="{e(DESC)}" />\n'
            f'<link rel="canonical" href="{e(SITE)}" />\n'
            '<meta name="robots" content="index, follow" />\n'
            '<meta name="application-name" content="Omnipuls" />\n'
            '<meta name="theme-color" content="#0B1220" />\n'
            '<meta property="og:type" content="website" />\n<meta property="og:site_name" content="Omnipuls" />\n'
            f'<meta property="og:title" content="{e(TITLE)}" />\n<meta property="og:description" content="{e(DESC)}" />\n'
            f'<meta property="og:url" content="{e(SITE)}" />\n'
            f'<meta property="og:image" content="{e(SITE)}app/static/icon-512.png" />\n'
            '<meta name="twitter:card" content="summary" />\n'
            + (f'<meta name="google-site-verification" content="{e(ver)}" />\n' if ver else "")
            + '<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebApplication",'
            f'"name":"Omnipuls","url":"{SITE}","applicationCategory":"FinanceApplication",'
            f'"description":{repr(DESC).replace(chr(39), chr(34))}}}</script>\n{MARK}\n')
    s = s.replace("</head>", head + "</head>", 1)
    body = (f"<noscript>{MARK}<h1>Omnipuls</h1><p>{e(DESC)}</p><p>Open <a href=\"{e(SITE)}\">omnipuls.cloud</a> "
            "with JavaScript on to sign in.</p></noscript>")
    s = re.sub(r"(<body[^>]*>)", r"\1" + body.replace("\\", "\\\\"), s, count=1)
    f.write_text(s, encoding="utf-8")
    print(f"seo: patched {f}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:   # never stop the app from starting
        print(f"seo: not patched ({ex})")
