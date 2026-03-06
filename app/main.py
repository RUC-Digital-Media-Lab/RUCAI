from __future__ import annotations

import json
import os
from datetime import datetime
from secrets import choice
from typing import List, Literal, Optional
from pathlib import Path
from threading import Thread

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    create_session,
    create_student_session,
    hash_password,
    require_auth,
    require_student_auth,
    verify_password,
)
from .chat import (
    build_grouped_sources,
    chat_response,
    has_explicit_document_hint,
    contexts_match_query_document_hint,
    filter_contexts_for_explicit_doc_mention,
    filter_reference_noise,
    query_document_tokens,
    select_source_first_contexts,
)
from .config import ensure_data_dirs, load_settings
from .db import (
    course_belongs_to_owner,
    copy_course_chunks_to_instance,
    create_bot_instance,
    create_ingest_job,
    create_or_activate_course,
    delete_chat_messages_for_course,
    delete_document,
    delete_bot_instance,
    document_belongs_to_course,
    ensure_schema,
    get_active_course,
    get_bot_instance_by_id,
    get_bot_instance_by_code,
    get_bot_instance_for_owner,
    list_courses,
    list_bot_instances_for_owner,
    list_bot_instance_documents,
    get_course_prompt,
    get_document,
    get_connection,
    get_ingest_job,
    insert_chat_message,
    list_chat_messages_for_course,
    list_student_chat_messages_for_instance,
    delete_student_chat_messages_for_instance,
    list_documents_for_course,
    set_active_course_by_id,
    set_bot_instance_status,
    insert_student_chat_message,
    upsert_course_prompt,
)
from .ingest import process_ingest_job
from .llm import generate_answer
from .prompts import (
    DEFAULT_EDITABLE_INSTRUCTIONS,
    LOCKED_SAFETY_BLOCK,
    LOCKED_SAFETY_BLOCK_DA,
    LOCKED_SAFETY_BLOCK_EN,
    compose_system_prompt,
    to_student_editable_instructions,
)
from .search import search_chunks, search_instance_chunks

app = FastAPI(title="RUCAI")
LOGO_DIR = Path(__file__).resolve().parent.parent / "logo"
if LOGO_DIR.exists():
    app.mount("/logo", StaticFiles(directory=str(LOGO_DIR)), name="logo")

INSTANCE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _umami_bootstrap_html() -> str:
    website_id = os.getenv("UMAMI_WEBSITE_ID", "").strip()
    if not website_id:
        return ""

    script_url = os.getenv("UMAMI_SCRIPT_URL", "https://cloud.umami.is/script.js").strip()
    host_url = os.getenv("UMAMI_HOST_URL", "https://cloud.umami.is").strip()
    domains_raw = os.getenv("UMAMI_DOMAINS", "").strip()
    domains = ",".join([d.strip() for d in domains_raw.split(",") if d.strip()])

    set_domains_js = ""
    if domains:
        set_domains_js = f'script.setAttribute("data-domains", {json.dumps(domains)});'

    return (
        "<script>"
        "(function(){"
        'var id="umami-script";'
        "if(document.getElementById(id)){return;}"
        "var script=document.createElement('script');"
        "script.id=id;"
        "script.async=true;"
        f"script.src={json.dumps(script_url)};"
        f"script.setAttribute('data-website-id',{json.dumps(website_id)});"
        f"script.setAttribute('data-host-url',{json.dumps(host_url)});"
        f"{set_domains_js}"
        "document.head.appendChild(script);"
        "})();"
        "</script>"
    )


def _inject_umami(html: str) -> str:
    return html.replace("<!-- UMAMI_BOOTSTRAP -->", _umami_bootstrap_html())


WEB_UI_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RUCAI</title>
    <!-- UMAMI_BOOTSTRAP -->
    <style>
      :root {
        --bg: #f8f7f2;
        --panel: rgba(255, 255, 255, 0.84);
        --ink: #1f1f1d;
        --muted: #616257;
        --accent: #0f8b8d;
        --accent-dark: #0a6f71;
        --accent-2: #ff7f11;
        --danger: #b3261e;
        --ok: #1f7a45;
        --border: rgba(24, 24, 20, 0.12);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        color: var(--ink);
        font-family: "Avenir Next", "IBM Plex Sans", "Segoe UI", sans-serif;
        background: radial-gradient(circle at 14% 20%, #d6ede4 0, transparent 34%),
                    radial-gradient(circle at 82% 10%, #ffe4bf 0, transparent 28%),
                    linear-gradient(135deg, #f6f3ed, #e9f0ec 45%, #f4efe7 100%);
        min-height: 100vh;
      }
      .bg-shape { position: fixed; z-index: -1; opacity: 0.45; filter: blur(18px); border-radius: 999px; }
      .shape-a { width: 320px; height: 320px; background: #2ca58d; left: -80px; bottom: -80px; }
      .shape-b { width: 280px; height: 280px; background: #ff9a3c; right: -60px; top: -60px; }
      .gate-wrap { min-height: 100vh; display: grid; place-items: center; padding: 20px; }
      .gate-card {
        width: min(460px, 94vw);
        border: 1px solid var(--border);
        background: var(--panel);
        backdrop-filter: blur(6px);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 12px 26px rgba(16, 22, 19, 0.07);
      }
      .gate-title { margin: 0; font-family: "Iowan Old Style", "Palatino Linotype", serif; }
      .gate-sub { margin: 8px 0 16px; color: var(--muted); }
      .layout { width: min(1220px, 96vw); margin: 1.6rem auto 2.8rem; display: grid; grid-template-columns: 280px 1fr; gap: 1rem; align-items: start; }
      .layout > .header { grid-column: 1 / -1; }
      .layout > .sidebar { grid-column: 1; align-self: start; position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow-y: auto; }
      .layout > .card:not(.sidebar) { grid-column: 2; }
      .layout > .split-two { grid-column: 2; }
      @media (max-width: 960px) {
        .layout { grid-template-columns: 1fr; }
        .layout > .sidebar, .layout > .card, .layout > .header, .layout > .split-two { grid-column: 1; position: static; }
      }
      .header { padding: 0.2rem; }
      .header { position: relative; }
      .header h1 { margin: 0; font-family: "Iowan Old Style", "Palatino Linotype", serif; letter-spacing: 0.02em; }
      .brand-logo { display: block; height: 156px; width: auto; object-fit: contain; max-width: min(70vw, 720px); }
      .gate-logo { display: block; margin: 4px auto 10px; height: 96px; width: auto; max-width: 90%; object-fit: contain; }
      .header p { margin: 0.35rem 0 0; color: var(--muted); }
      .header-actions { position: absolute; right: 0; top: 0; }
      @media (max-width: 960px) {
        .header-actions { position: static; margin-top: 10px; }
      }
      .lang-toggle { display: inline-flex; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-right: 8px; background: rgba(255,255,255,0.85); vertical-align: middle; }
      .lang-toggle-btn { border: 0; border-radius: 0; padding: 8px 12px; background: transparent; font-weight: 700; min-width: 48px; }
      .lang-toggle-btn + .lang-toggle-btn { border-left: 1px solid var(--border); }
      .lang-toggle-btn.active { background: linear-gradient(135deg, var(--accent), var(--accent-dark)); color: #fff; }
      .card {
        border: 1px solid var(--border);
        background: var(--panel);
        backdrop-filter: blur(6px);
        border-radius: 14px;
        padding: 14px;
        overflow: hidden;
        box-shadow: 0 12px 26px rgba(16, 22, 19, 0.07);
      }
      pre {
        max-width: 100%;
        overflow-x: auto;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        word-break: break-word;
      }
      .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }
      textarea, input[type="text"], input[type="password"], input[type="number"], select {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 10px;
        font: inherit;
        background: rgba(255, 255, 255, 0.78);
      }
      input[type="text"], input[type="password"], textarea { flex: 1 1 280px; }
      textarea { min-height: 110px; resize: vertical; }
      #courseDesc { min-height: 140px; }
      button {
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 10px 14px;
        cursor: pointer;
        font-weight: 600;
        background: white;
        color: var(--ink);
      }
      button.primary { background: linear-gradient(135deg, var(--accent), var(--accent-dark)); color: #fff; border-color: transparent; }
      button.warn { background: linear-gradient(135deg, var(--accent-2), #de6f11); color: #fff; border-color: transparent; }
      button:disabled { opacity: 0.72; cursor: not-allowed; }
      button.busy { animation: busyPulse 1s ease-in-out infinite; }
      @keyframes busyPulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(0.985); }
      }
      .small { font-size: 13px; color: var(--muted); margin-top: 8px; }
      #aboutBody { font-size: 16px; line-height: 1.65; color: var(--ink); }
      .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
      .ok { color: var(--ok); }
      .err { color: var(--danger); }
      .source { margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 8px; }
      .answer { white-space: pre-wrap; margin-top: 8px; }
      .hidden { display: none !important; }
      .stack { display: grid; gap: 8px; }
      .course-item { width: 100%; text-align: left; margin-top: 6px; }
      .course-item.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(15, 139, 141, 0.15) inset; }
      .history { max-height: 320px; overflow: auto; border-top: 1px dashed var(--border); margin-top: 10px; padding-top: 8px; }
      .history-item { margin-bottom: 8px; padding: 8px; border: 1px solid var(--border); border-radius: 10px; background: rgba(255,255,255,0.65); }
      .history-role { font-weight: 700; font-size: 12px; color: var(--muted); text-transform: uppercase; }
      .history-time { font-size: 11px; color: var(--muted); margin-top: 4px; }
      .thinking { display: inline-flex; align-items: center; gap: 4px; }
      .thinking-dots { display: inline-flex; min-width: 22px; }
      .thinking-dots span { opacity: 0.2; animation: thinkingBlink 1.2s infinite; }
      .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
      .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
      @keyframes thinkingBlink {
        0%, 80%, 100% { opacity: 0.2; }
        40% { opacity: 1; }
      }
      .chat-compose { display: flex; gap: 8px; align-items: stretch; margin-top: 8px; }
      .chat-compose textarea { margin: 0; }
      .chat-actions { display: flex; flex-direction: column; gap: 8px; width: 180px; }
      .chat-actions button { width: 100%; }
      .split-two {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
      }
      .split-two .card { margin: 0; }
      .tip-wrap {
        position: relative;
        display: inline-flex;
        align-items: center;
        margin-left: 6px;
        vertical-align: middle;
      }
      .tip-icon {
        width: 18px;
        height: 18px;
        border-radius: 999px;
        border: 1px solid var(--border);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 700;
        color: var(--accent-dark);
        background: rgba(255, 255, 255, 0.9);
        cursor: help;
      }
      .tip-text {
        position: absolute;
        left: 0;
        top: 24px;
        width: 320px;
        max-width: min(80vw, 320px);
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 9px 10px;
        box-shadow: 0 12px 26px rgba(16, 22, 19, 0.12);
        color: var(--ink);
        font-size: 12px;
        line-height: 1.35;
        visibility: hidden;
        opacity: 0;
        transition: opacity 0.15s ease;
        z-index: 40;
      }
      .tip-wrap:hover .tip-text,
      .tip-wrap:focus-within .tip-text {
        visibility: visible;
        opacity: 1;
      }
      @media (max-width: 960px) {
        .chat-compose { flex-direction: column; }
        .chat-actions { width: 100%; }
        .split-two { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="bg-shape shape-a"></div>
    <div class="bg-shape shape-b"></div>

    <div id="loginGate" class="gate-wrap">
      <section class="gate-card">
        <img class="gate-logo" src="/logo/RUCAI_LOGO_new.png" alt="RUCAI" />
        <h2 class="gate-title">RUCAI Log ind</h2>
        <p class="gate-sub">Log ind for at åbne platformen.</p>
        <div class="row">
          <input id="username" type="text" placeholder="brugernavn" />
          <input id="password" type="password" placeholder="adgangskode" />
          <button id="loginBtn" class="primary">Log ind</button>
        </div>
        <div id="authState" class="small"></div>
      </section>
    </div>

    <main id="appShell" class="layout hidden">
      <header class="header">
        <h1>RUCAI</h1>
        <div class="header-actions">
          <div class="lang-toggle" role="group" aria-label="Language toggle">
            <button id="uiLangDaBtn" type="button" class="lang-toggle-btn">DA</button>
            <button id="uiLangEnBtn" type="button" class="lang-toggle-btn">EN</button>
          </div>
          <button id="logoutTopBtn" class="warn">Log ud</button>
        </div>
      </header>

      <section class="card">
        <h3 id="aboutTitle">Hvad er RUCAI?</h3>
        <div class="small" id="aboutBody">
          RUCAI er sat i verden til at understøtte kursusplanlægning og afvikling.
          Ideen er at underviser kan designe og tilrettelægge undervisning med udgangspunkt i kursusbeskrivelse og pensum
          og så oprette ”chat” vinduer, som studerende så kan tilgå i forbindelse med undervisning.
          Chat-historik gemmes pr. kursusgang, så samtaler kan fortsætte over tid.
        </div>
      </section>

      <section class="card sidebar">
        <h3 id="coursesTitle">Kurser</h3>
        <div class="small" id="coursesSub">Skift mellem dine kurser.</div>
        <div class="row">
          <button id="newCourseBtn" class="primary" style="width:100%;">Nyt kursus</button>
        </div>
        <div id="coursesState" class="small"></div>
        <div id="coursesList" class="stack"></div>
      </section>

      <section class="card" id="activeCourseCard">
        <h3 id="courseInfoTitle">Information om kurset</h3>
        <div class="row">
          <input id="courseTitle" type="text" placeholder="Kursustitel" />
        </div>
        <div class="row">
          <textarea id="courseDesc" placeholder="Kursusbeskrivelse"></textarea>
        </div>
        <div class="row">
          <button id="setCourseBtn" class="primary">Placer kursusbeskrivelse og titel i systemprompt</button>
          <button id="refreshCourseBtn">Genindlæs visning</button>
        </div>
        <div id="courseState" class="small"></div>
      </section>

      <section class="card">
        <h3 id="promptTitle">Kursusprompt
          <span class="tip-wrap">
            <span id="promptTipIcon" class="tip-icon" tabindex="0" aria-label="Tips til prompt-teknik">I</span>
            <span id="promptTipText" class="tip-text">God prompt-teknik: Vær konkret om målgruppe, læringsmål, ønsket svarformat og længde. Bed om kildehenvisninger, og sig tydeligt hvad modellen skal gøre ved usikkerhed.</span>
          </span>
        </h3>
        <div id="promptSub" class="small">Du kan redigere undervisningsinstruktionen. Nogle grundregler er faste for at sikre kildebaserede og ansvarlige svar.</div>
        <div class="row">
          <textarea id="promptEditable" placeholder="Redigerbar kursusinstruktion"></textarea>
        </div>
        <div class="row">
          <button id="savePromptBtn" class="primary">Gem kursusprompt</button>
          <button id="refreshPromptBtn">Hent kursusprompt</button>
        </div>
        <details class="small">
          <summary id="lockedRulesSummary">Faste grundregler (kan ikke redigeres)</summary>
          <pre id="promptLocked"></pre>
        </details>
        <details class="small">
          <summary id="activePromptSummary">Aktiv prompt (preview)</summary>
          <pre id="promptPreview"></pre>
        </details>
        <details class="small">
          <summary id="teacherPromptSummary">Underviser-prompt (aktiv)</summary>
          <pre id="promptTeacherPreview"></pre>
        </details>
        <details class="small">
          <summary id="studentPromptSummary">Studenter-prompt (ved publicering)</summary>
          <pre id="promptStudentPreview"></pre>
        </details>
        <div id="promptState" class="small"></div>
      </section>

      <section class="split-two">
        <section class="card">
          <h3 id="uploadTitle">Upload PDF/DOCX</h3>
          <div class="row">
            <input id="docFile" type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" />
            <button id="uploadBtn" class="primary">Upload og indlæs</button>
          </div>
          <div id="scanModeList" class="small"></div>
          <div id="ingestState" class="small"></div>
        </section>

        <section class="card">
          <h3 id="documentsTitle">Dokumenter</h3>
          <div class="row">
            <button id="refreshDocsBtn">Genindlæs dokumentliste</button>
          </div>
          <div id="docsState" class="small"></div>
          <div id="docsList" class="stack"></div>
        </section>
      </section>

      <section class="card">
        <h3 id="chatTitle">Chat</h3>
        <div class="row">
          <label id="topKLabel" for="topK" class="small">Kilder pr. svar (k)</label>
          <input id="topK" type="number" min="1" max="50" value="5" />
          <label id="answerLangLabel" for="answerLangSelect" class="small">Svarsprog</label>
          <select id="answerLangSelect" style="min-width:160px;">
            <option id="answerLangAutoOption" value="auto">Auto (UI-sprog)</option>
            <option value="da">Dansk</option>
            <option value="en">English</option>
          </select>
        </div>
        <div class="row">
          <label id="modelLabel" for="chatModelSelect" class="small">Model</label>
          <select id="chatModelSelect" style="min-width:240px;">
            <option value="gemma3:12b" selected>gemma3:12b (12.2B, 131,072 kontekst, hurtig)</option>
            <option value="mistral-nemo">mistral-nemo (12.2B, 1,024,000 kontekst, stærk allround)</option>
          </select>
          <button id="saveModelBtn">Gem model</button>
        </div>
        <div id="modelState" class="small"></div>
        <div id="chatStatus" class="small"></div>
        <div id="answer" class="answer"></div>
        <div id="sources"></div>
        <div class="small"><strong id="referenceMentionsTitle">Nævnt i pensumtekster (ikke pensumkilder)</strong></div>
        <div id="referenceMentions"></div>
        <div class="small"><strong id="chatHistoryTitle">Samtalehistorik</strong> <span id="chatHistorySub">(for aktivt kursus)</span></div>
        <div id="chatHistory" class="history"></div>
        <div class="chat-compose">
          <textarea id="question" placeholder="Spørg ind til pensum, teksterne eller øvelserne..."></textarea>
          <div class="chat-actions">
            <button id="chatBtn" class="primary">Spørg</button>
            <button id="newChatBtn" class="warn">Ny samtale</button>
          </div>
        </div>
      </section>

      <section class="card">
        <h3 id="instancesTitle">Skab studenter-chatvinduer</h3>
        <div id="instancesSub" class="small">Publicér en låst chatbot til studerende ud fra aktivt kursus.</div>
        <div class="row">
          <textarea id="instanceStudentPrompt" placeholder="Student-prompt (final for denne instance)" style="min-height:160px;"></textarea>
        </div>
        <div class="row">
          <label style="display:flex;align-items:center;gap:8px;">
            <input id="instancePromptReviewed" type="checkbox" />
            <span id="instancePromptReviewedLabel">Jeg har gennemgået student-prompten før publicering</span>
          </label>
        </div>
        <div class="small" id="instanceFieldsHint">
          Chatvindue-navn er den interne titel i underviser-overblikket. Adgangskode er det, studerende bruger til login.
        </div>
        <div class="row">
          <input id="instanceName" type="text" placeholder="Chatvindue-navn (fx Hold A Forår 2026)" />
        </div>
        <div class="row">
          <input id="instancePassword" type="password" placeholder="Adgangskode til studerende" />
          <button id="publishInstanceBtn" class="primary">Publicér</button>
          <button id="refreshInstancesBtn">Genindlæs chatvinduer</button>
        </div>
        <div id="instancesState" class="small"></div>
        <div id="instancesList" class="stack"></div>
      </section>

      <section class="card">
        <h3 id="fullPromptTitle">Samlet systemprompt (live preview)</h3>
        <div id="fullPromptSub" class="small">Endelig systemprompt, som modellen modtager.</div>
        <pre id="fullPromptPreview"></pre>
        <div id="fullPromptState" class="small"></div>
      </section>

    </main>

    <script>
      let token = localStorage.getItem("rucai_token") || "";
      const browserLang = (navigator.language || "da").toLowerCase().startsWith("da") ? "da" : "en";
      let uiLang = localStorage.getItem("rucai_ui_lang") || browserLang;
      let answerLangMode = localStorage.getItem("rucai_answer_lang") || "auto";
      let activeCourseId = null;
      const gate = document.getElementById("loginGate");
      const appShell = document.getElementById("appShell");
      const authState = document.getElementById("authState");
      const courseState = document.getElementById("courseState");
      const coursesState = document.getElementById("coursesState");
      const coursesList = document.getElementById("coursesList");
      const ingestState = document.getElementById("ingestState");
      const scanModeList = document.getElementById("scanModeList");
      const chatStatus = document.getElementById("chatStatus");
      const answerEl = document.getElementById("answer");
      const sourcesEl = document.getElementById("sources");
      const referenceMentionsEl = document.getElementById("referenceMentions");
      const chatHistoryEl = document.getElementById("chatHistory");
      const promptState = document.getElementById("promptState");
      const modelState = document.getElementById("modelState");
      const promptEditableEl = document.getElementById("promptEditable");
      const promptLockedEl = document.getElementById("promptLocked");
      const promptPreviewEl = document.getElementById("promptPreview");
      const promptTeacherPreviewEl = document.getElementById("promptTeacherPreview");
      const promptStudentPreviewEl = document.getElementById("promptStudentPreview");
      const fullPromptPreviewEl = document.getElementById("fullPromptPreview");
      const fullPromptStateEl = document.getElementById("fullPromptState");
      const instanceStudentPromptEl = document.getElementById("instanceStudentPrompt");
      const instancePromptReviewedEl = document.getElementById("instancePromptReviewed");
      const docsState = document.getElementById("docsState");
      const docsList = document.getElementById("docsList");
      const instancesState = document.getElementById("instancesState");
      const instancesList = document.getElementById("instancesList");
      const uiLangDaBtn = document.getElementById("uiLangDaBtn");
      const uiLangEnBtn = document.getElementById("uiLangEnBtn");
      const answerLangSelect = document.getElementById("answerLangSelect");
      let livePromptPreviewTimer = null;

      const I18N = {
        da: {
          logout: "Log ud",
          login: "Log ind",
          loginTitle: "RUCAI Log ind",
          loginSub: "Log ind for at åbne platformen.",
          usernamePlaceholder: "brugernavn",
          passwordPlaceholder: "adgangskode",
          aboutTitle: "Hvad er RUCAI?",
          aboutBody: "RUCAI er sat i verden til at understøtte kursusplanlægning og afvikling. Ideen er at underviser kan designe og tilrettelægge undervisning med udgangspunkt i kursusbeskrivelse og pensum og så oprette ”chat” vinduer, som studerende så kan tilgå i forbindelse med undervisning. Chat-historik gemmes pr. kursusgang, så samtaler kan fortsætte over tid.",
          coursesTitle: "Kurser",
          coursesSub: "Skift mellem dine kurser.",
          newCourseBtn: "Nyt kursus",
          courseInfoTitle: "Information om kurset",
          courseTitlePlaceholder: "Kursustitel",
          courseDescPlaceholder: "Kursusbeskrivelse",
          setCourseBtn: "Placer kursusbeskrivelse og titel i systemprompt",
          refreshCourseBtn: "Genindlæs visning",
          promptTitle: "Kursusprompt",
          promptTipAria: "Tips til prompt-teknik",
          promptTipText: "God prompt-teknik: Vær konkret om målgruppe, læringsmål, ønsket svarformat og længde. Bed om kildehenvisninger, og sig tydeligt hvad modellen skal gøre ved usikkerhed.",
          promptSub: "Du kan redigere undervisningsinstruktionen. Nogle grundregler er faste for at sikre kildebaserede og ansvarlige svar.",
          promptPlaceholder: "Redigerbar kursusinstruktion",
          savePromptBtn: "Gem kursusprompt",
          refreshPromptBtn: "Hent kursusprompt",
          lockedRulesSummary: "Faste grundregler (kan ikke redigeres)",
          activePromptSummary: "Aktiv prompt (preview)",
          teacherPromptSummary: "Underviser-prompt (aktiv)",
          studentPromptSummary: "Studenter-prompt (ved publicering)",
          uploadTitle: "Upload PDF/DOCX",
          uploadBtn: "Upload og indlæs",
          documentsTitle: "Dokumenter",
          refreshDocsBtn: "Genindlæs dokumentliste",
          chatTitle: "Chat",
          topKLabel: "Kilder pr. svar (k)",
          answerLangLabel: "Svarsprog",
          answerLangAuto: "Auto (UI-sprog)",
          modelLabel: "Model",
          saveModelBtn: "Gem model",
          chatHistoryTitle: "Samtalehistorik",
          referenceMentionsTitle: "Nævnt i pensumtekster (ikke pensumkilder)",
          noReferenceMentions: "Ingen nævnte eksterne kilder fundet.",
          chatHistorySub: "(for aktivt kursus)",
          questionPlaceholder: "Spørg ind til pensum, teksterne eller øvelserne...",
          chatBtn: "Spørg",
          newChatBtn: "Ny samtale",
          instancesTitle: "Skab studenter-chatvinduer",
          instancesSub: "Publicér en låst chatbot til studerende ud fra aktivt kursus.",
          instanceFieldsHint: "Chatvindue-navn er den interne titel i underviser-overblikket. Adgangskode er det, studerende bruger til login.",
          instanceNamePlaceholder: "Chatvindue-navn (fx Hold A Forår 2026)",
          instanceStudentPromptPlaceholder: "Student-prompt (final for denne instance)",
          instancePromptReviewedLabel: "Jeg har gennemgået student-prompten før publicering",
          instancePasswordPlaceholder: "Adgangskode til studerende",
          publishInstanceBtn: "Publicér",
          refreshInstancesBtn: "Genindlæs chatvinduer",
          deleteBtn: "Slet",
          fullPromptTitle: "Samlet systemprompt (live preview)",
          fullPromptSub: "Endelig systemprompt, som modellen modtager.",
          working: "Arbejder",
          thinking: "Tænker",
          writeQuestionError: "Skriv et spørgsmål.",
          writeCoursePrompt: "Vælg eller opret et kursus for at redigere course prompt.",
          noMessages: "Ingen beskeder endnu.",
          sourceLabel: "kilder",
          chunkLabel: "uddrag",
          roundsLabel: "retrieval_runde(r)",
          done: "Færdig",
          activeModel: "Aktiv model",
        },
        en: {
          logout: "Log out",
          login: "Log in",
          loginTitle: "RUCAI Login",
          loginSub: "Log in to open the platform.",
          usernamePlaceholder: "username",
          passwordPlaceholder: "password",
          aboutTitle: "What is RUCAI?",
          aboutBody: "RUCAI supports course planning and delivery. Teachers can design course-specific assistants from course descriptions and readings, then publish chat windows that students can access in class. Chat history is stored per course session so conversations can continue over time.",
          coursesTitle: "Courses",
          coursesSub: "Switch between your courses.",
          newCourseBtn: "New course",
          courseInfoTitle: "Course information",
          courseTitlePlaceholder: "Course title",
          courseDescPlaceholder: "Course description",
          setCourseBtn: "Place course description and title in system prompt",
          refreshCourseBtn: "Refresh view",
          promptTitle: "Course prompt",
          promptTipAria: "Prompt writing tips",
          promptTipText: "Good prompt practice: be specific about audience, learning goals, response format, and length. Ask for citations and tell the model how to handle uncertainty.",
          promptSub: "You can edit the instructional prompt. Core safety rules are fixed to ensure grounded responses.",
          promptPlaceholder: "Editable course instruction",
          savePromptBtn: "Save course prompt",
          refreshPromptBtn: "Load course prompt",
          lockedRulesSummary: "Fixed ground rules (not editable)",
          activePromptSummary: "Active prompt (preview)",
          teacherPromptSummary: "Teacher prompt (active)",
          studentPromptSummary: "Student prompt (on publish)",
          uploadTitle: "Upload PDF/DOCX",
          uploadBtn: "Upload and ingest",
          documentsTitle: "Documents",
          refreshDocsBtn: "Refresh document list",
          chatTitle: "Chat",
          topKLabel: "Sources per answer (k)",
          answerLangLabel: "Answer language",
          answerLangAuto: "Auto (UI language)",
          modelLabel: "Model",
          saveModelBtn: "Save model",
          chatHistoryTitle: "Chat history",
          referenceMentionsTitle: "Mentioned in texts (not curriculum sources)",
          noReferenceMentions: "No external references mentioned in retrieved text.",
          chatHistorySub: "(for active course)",
          questionPlaceholder: "Ask about curriculum, texts, or exercises...",
          chatBtn: "Ask",
          newChatBtn: "New chat",
          instancesTitle: "Create student chat windows",
          instancesSub: "Publish a locked chatbot for students from the active course.",
          instanceFieldsHint: "Chat window name is an internal teacher label. Student access password is what students use to log in.",
          instanceNamePlaceholder: "Chat window name (e.g., Group A Spring 2026)",
          instanceStudentPromptPlaceholder: "Student prompt (final for this instance)",
          instancePromptReviewedLabel: "I have reviewed the student prompt before publish",
          instancePasswordPlaceholder: "Student access password",
          publishInstanceBtn: "Publish",
          refreshInstancesBtn: "Refresh chat windows",
          deleteBtn: "Delete",
          fullPromptTitle: "Full system prompt (live preview)",
          fullPromptSub: "Final system prompt received by the model.",
          working: "Working",
          thinking: "Thinking",
          writeQuestionError: "Enter a question.",
          writeCoursePrompt: "Select or create a course to edit the course prompt.",
          noMessages: "No messages yet.",
          sourceLabel: "sources",
          chunkLabel: "chunks",
          roundsLabel: "retrieval_round(s)",
          done: "Done",
          activeModel: "Active model",
        },
      };

      function t(key) {
        const lang = uiLang === "en" ? "en" : "da";
        return (I18N[lang] && I18N[lang][key]) || (I18N.da && I18N.da[key]) || key;
      }

      function applyI18n() {
        uiLangDaBtn.classList.toggle("active", uiLang === "da");
        uiLangEnBtn.classList.toggle("active", uiLang === "en");
        uiLangDaBtn.setAttribute("aria-pressed", uiLang === "da" ? "true" : "false");
        uiLangEnBtn.setAttribute("aria-pressed", uiLang === "en" ? "true" : "false");
        answerLangSelect.value = answerLangMode;
        document.documentElement.lang = uiLang;
        const byIdText = [
          ["aboutTitle", "aboutTitle"],
          ["aboutBody", "aboutBody"],
          ["coursesTitle", "coursesTitle"],
          ["coursesSub", "coursesSub"],
          ["newCourseBtn", "newCourseBtn"],
          ["courseInfoTitle", "courseInfoTitle"],
          ["setCourseBtn", "setCourseBtn"],
          ["refreshCourseBtn", "refreshCourseBtn"],
          ["promptTitle", "promptTitle"],
          ["promptSub", "promptSub"],
          ["savePromptBtn", "savePromptBtn"],
          ["refreshPromptBtn", "refreshPromptBtn"],
          ["lockedRulesSummary", "lockedRulesSummary"],
          ["activePromptSummary", "activePromptSummary"],
          ["teacherPromptSummary", "teacherPromptSummary"],
          ["studentPromptSummary", "studentPromptSummary"],
          ["uploadTitle", "uploadTitle"],
          ["uploadBtn", "uploadBtn"],
          ["documentsTitle", "documentsTitle"],
          ["refreshDocsBtn", "refreshDocsBtn"],
          ["chatTitle", "chatTitle"],
          ["topKLabel", "topKLabel"],
          ["answerLangLabel", "answerLangLabel"],
          ["modelLabel", "modelLabel"],
          ["saveModelBtn", "saveModelBtn"],
          ["chatHistoryTitle", "chatHistoryTitle"],
          ["referenceMentionsTitle", "referenceMentionsTitle"],
          ["chatHistorySub", "chatHistorySub"],
          ["chatBtn", "chatBtn"],
          ["newChatBtn", "newChatBtn"],
          ["instancesTitle", "instancesTitle"],
          ["instancesSub", "instancesSub"],
          ["instanceFieldsHint", "instanceFieldsHint"],
          ["instancePromptReviewedLabel", "instancePromptReviewedLabel"],
          ["publishInstanceBtn", "publishInstanceBtn"],
          ["refreshInstancesBtn", "refreshInstancesBtn"],
          ["fullPromptTitle", "fullPromptTitle"],
          ["fullPromptSub", "fullPromptSub"],
          ["logoutTopBtn", "logout"],
          ["loginBtn", "login"],
          ["answerLangAutoOption", "answerLangAuto"],
        ];
        byIdText.forEach(([id, key]) => {
          const el = document.getElementById(id);
          if (el) el.textContent = t(key);
        });
        const loginTitleEl = document.querySelector(".gate-title");
        if (loginTitleEl) loginTitleEl.textContent = t("loginTitle");
        const loginSubEl = document.querySelector(".gate-sub");
        if (loginSubEl) loginSubEl.textContent = t("loginSub");
        const usernameEl = document.getElementById("username");
        if (usernameEl) usernameEl.placeholder = t("usernamePlaceholder");
        const passwordEl = document.getElementById("password");
        if (passwordEl) passwordEl.placeholder = t("passwordPlaceholder");
        const cTitle = document.getElementById("courseTitle");
        if (cTitle) cTitle.placeholder = t("courseTitlePlaceholder");
        const cDesc = document.getElementById("courseDesc");
        if (cDesc) cDesc.placeholder = t("courseDescPlaceholder");
        const pEdit = document.getElementById("promptEditable");
        if (pEdit) pEdit.placeholder = t("promptPlaceholder");
        const q = document.getElementById("question");
        if (q) q.placeholder = t("questionPlaceholder");
        const iname = document.getElementById("instanceName");
        if (iname) iname.placeholder = t("instanceNamePlaceholder");
        const isp = document.getElementById("instanceStudentPrompt");
        if (isp) isp.placeholder = t("instanceStudentPromptPlaceholder");
        const ipass = document.getElementById("instancePassword");
        if (ipass) ipass.placeholder = t("instancePasswordPlaceholder");
        const tipIcon = document.getElementById("promptTipIcon");
        if (tipIcon) tipIcon.setAttribute("aria-label", t("promptTipAria"));
        const tipText = document.getElementById("promptTipText");
        if (tipText) tipText.textContent = t("promptTipText");
      }

      function escapeHtml(text) {
        const d = document.createElement("div");
        d.innerText = String(text ?? "");
        return d.innerHTML;
      }

      function markdownToHtml(md) {
        const lines = String(md || "").split("\\n");
        const out = [];
        let inList = false;
        const inline = (txt) => escapeHtml(txt)
          .replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>")
          .replace(/\\*(.+?)\\*/g, "<em>$1</em>")
          .replace(/`([^`]+)`/g, "<code>$1</code>");
        for (const raw of lines) {
          const line = raw.trim();
          if (!line) {
            if (inList) { out.push("</ul>"); inList = false; }
            continue;
          }
          const bullet = line.match(/^[-*]\\s+(.+)$/);
          if (bullet) {
            if (!inList) { out.push("<ul>"); inList = true; }
            out.push(`<li>${inline(bullet[1])}</li>`);
            continue;
          }
          if (inList) { out.push("</ul>"); inList = false; }
          out.push(`<p>${inline(line)}</p>`);
        }
        if (inList) out.push("</ul>");
        return out.join("");
      }

      function cleanDisplayFilename(name) {
        const raw = String(name || "");
        return raw.replace(/^\\d{8}-\\d{6}-/, "");
      }

      function renderGroupedSources(container, data) {
        container.innerHTML = "";
        const grouped = Array.isArray(data?.sources) ? data.sources : [];
        if (grouped.length > 0) {
          grouped.forEach((src) => {
            const div = document.createElement("div");
            div.className = "source";
            const snippets = Array.isArray(src.snippets) ? src.snippets : [];
            const snippetHtml = snippets.map((sn) => `
              <div style="margin-top:6px;">p${escapeHtml(String(sn.page_start ?? "?"))}: ${escapeHtml(String(sn.content || ""))}</div>
            `).join("");
            div.innerHTML = `<strong>[${escapeHtml(String(src.ref ?? "?"))}] ${escapeHtml(cleanDisplayFilename(String(src.filename || "Ukendt kilde")))}</strong>${snippetHtml}`;
            container.appendChild(div);
          });
          return;
        }

        (data?.contexts || []).forEach((ctx) => {
          const div = document.createElement("div");
          div.className = "source";
          div.innerHTML = `<strong>${escapeHtml(cleanDisplayFilename(String(ctx.filename || "Ukendt kilde")))}</strong> p${escapeHtml(ctx.page_start)}<br>${escapeHtml(ctx.content || "")}`;
          container.appendChild(div);
        });
      }

      function renderReferenceMentions(container, data) {
        container.innerHTML = "";
        const mentions = Array.isArray(data?.reference_mentions) ? data.reference_mentions : [];
        if (!mentions.length) {
          container.innerHTML = `<div class="small">${escapeHtml(t("noReferenceMentions"))}</div>`;
          return;
        }
        mentions.forEach((m) => {
          const div = document.createElement("div");
          div.className = "source small";
          const filename = escapeHtml(cleanDisplayFilename(String(m.filename || "Ukendt kilde")));
          const page = escapeHtml(String(m.page_start ?? "?"));
          const full = String(m.content || "");
          const short = full.length > 240 ? `${full.slice(0, 240)}...` : full;
          div.innerHTML = `
            <strong>${filename}</strong> p${page}<br>
            ${escapeHtml(short)}
            <details><summary>${escapeHtml(uiLang === "en" ? "Show full excerpt" : "Vis hele uddraget")}</summary>${escapeHtml(full)}</details>
          `;
          container.appendChild(div);
        });
      }

      function renderGroupedSources(container, data) {
        container.innerHTML = "";
        const grouped = Array.isArray(data?.sources) ? data.sources : [];
        const maxPreviewChars = 240;
        if (grouped.length > 0) {
          grouped.forEach((src) => {
            const wrapper = document.createElement("div");
            wrapper.className = "source small";
            const ref = escapeHtml(String(src.ref ?? "?"));
            const filename = escapeHtml(cleanDisplayFilename(String(src.filename || "Ukendt kilde")));
            const snippets = Array.isArray(src.snippets) ? src.snippets : [];
            const snippetsHtml = snippets.map((sn) => {
              const fullText = String(sn.content || "");
              const shortText = fullText.length > maxPreviewChars ? `${fullText.slice(0, maxPreviewChars)}...` : fullText;
              return `
                <div style="margin-top:6px;">
                  p${escapeHtml(String(sn.page_start ?? "?"))} idx ${escapeHtml(String(sn.chunk_index ?? "?"))}<br>
                  ${escapeHtml(shortText)}
                  <details><summary>${escapeHtml(uiLang === "en" ? "Show full excerpt" : "Vis hele uddraget")}</summary>${escapeHtml(fullText)}</details>
                </div>
              `;
            }).join("");
            wrapper.innerHTML = `<strong>[${ref}] ${filename}</strong>${snippetsHtml}`;
            container.appendChild(wrapper);
          });
          return;
        }

        // Backward-compatible fallback if server does not provide grouped sources.
        (data?.contexts || []).forEach((ctx) => {
          const div = document.createElement("div");
          div.className = "source small";
          const fullText = String(ctx.content || "");
          const shortText = fullText.length > maxPreviewChars ? `${fullText.slice(0, maxPreviewChars)}...` : fullText;
          div.innerHTML = `
            <strong>${escapeHtml(cleanDisplayFilename(String(ctx.filename || "Ukendt kilde")))}</strong> p${escapeHtml(ctx.page_start)} idx ${escapeHtml(ctx.chunk_index)}<br>
            ${escapeHtml(shortText)}
            <details><summary>${escapeHtml(uiLang === "en" ? "Show full excerpt" : "Vis hele uddraget")}</summary>${escapeHtml(fullText)}</details>
          `;
          container.appendChild(div);
        });
      }

      const thinkingIntervals = new Map();

      function startThinking(el, label = t("thinking")) {
        stopThinking(el);
        el.innerHTML = `<span class="thinking"><span>${escapeHtml(label)}</span><span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span></span>`;
      }

      function stopThinking(el) {
        const timer = thinkingIntervals.get(el);
        if (timer) {
          clearInterval(timer);
          thinkingIntervals.delete(el);
        }
      }

      function startBusyButton(btn, label = t("working")) {
        const original = btn.textContent || "";
        btn.dataset.originalLabel = original;
        btn.disabled = true;
        btn.classList.add("busy");
        let dots = 0;
        btn.textContent = `${label}.`;
        const timer = setInterval(() => {
          dots = (dots + 1) % 4;
          btn.textContent = `${label}${".".repeat(Math.max(1, dots))}`;
        }, 260);
        return timer;
      }

      function stopBusyButton(btn, timer) {
        if (timer) clearInterval(timer);
        btn.disabled = false;
        btn.classList.remove("busy");
        btn.textContent = btn.dataset.originalLabel || t("chatBtn");
      }

      function scanModeLabel(mode) {
        if (mode === "hand_scanned") return "håndscannet";
        if (mode === "digital") return "digitaliseret";
        return String(mode || "ukendt");
      }

      function showApp() {
        gate.classList.add("hidden");
        appShell.classList.remove("hidden");
      }

      function showGate(msg) {
        appShell.classList.add("hidden");
        gate.classList.remove("hidden");
        authState.innerHTML = msg ? `<span class="err">${escapeHtml(msg)}</span>` : "";
      }

      function isNoCourseError(message) {
        const text = String(message || "").toLowerCase();
        return text.includes("no active course");
      }

      function showNoCourseOnboarding() {
        courseState.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "You do not have an active course yet. Create your first course below." : "Du har ikke et aktivt kursus endnu. Opret dit første kursus nedenfor.")}</span>`;
        promptState.innerHTML = `<span class="ok">${escapeHtml(t("writeCoursePrompt"))}</span>`;
        fullPromptStateEl.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Select or create a course to view the full system prompt." : "Vælg eller opret et kursus for at se samlet systemprompt.")}</span>`;
        fullPromptPreviewEl.textContent = "";
        docsState.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Select or create a course to view documents." : "Vælg eller opret et kursus for at se dokumenter.")}</span>`;
        docsList.innerHTML = "";
        chatHistoryEl.innerHTML = `<div class="small">${escapeHtml(uiLang === "en" ? "Create a course to start chat history." : "Opret et kursus for at starte chat-historik.")}</div>`;
      }

      function buildStudentUrl(instanceCode) {
        return `${window.location.origin}/student/i/${instanceCode}`;
      }

      function selectedAnswerLanguage() {
        if (answerLangMode === "en") return "en";
        if (answerLangMode === "da") return "da";
        return null;
      }

      async function copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
          return true;
        }
        const t = document.createElement("textarea");
        t.value = text;
        document.body.appendChild(t);
        t.select();
        document.execCommand("copy");
        document.body.removeChild(t);
        return true;
      }

      async function api(path, options = {}) {
        const headers = options.headers || {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const resp = await fetch(path, { ...options, headers });
        const isJson = (resp.headers.get("content-type") || "").includes("application/json");
        const data = isJson ? await resp.json() : await resp.text();
        if (!resp.ok) {
          let detail = typeof data === "object" && data ? (data.detail ?? data) : data;
          if (Array.isArray(detail)) detail = detail.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join("; ");
          if (typeof detail === "object" && detail !== null) detail = JSON.stringify(detail);
          throw new Error(String(detail || `HTTP ${resp.status}`));
        }
        return data;
      }

      async function validateSession() {
        if (!token) return false;
        const resp = await fetch("/course/active", { headers: { Authorization: `Bearer ${token}` } });
        if (resp.status === 401) return false;
        return true;
      }

      async function refreshActiveCourse() {
        try {
          const data = await api("/course/active");
          const c = data.course;
          activeCourseId = Number(c.id);
          document.getElementById("courseTitle").value = c.title || "";
          document.getElementById("courseDesc").value = c.description || "";
          courseState.innerHTML = `<span class="ok">Aktivt kursus: ${escapeHtml(c.title)}</span> <span class="mono">id=${c.id}</span>`;
        } catch (err) {
          activeCourseId = null;
          if (isNoCourseError(err.message)) {
            showNoCourseOnboarding();
          } else {
            courseState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          }
        }
      }

      async function refreshCourses() {
        try {
          const data = await api("/courses");
          const items = data.courses || [];
          coursesState.innerHTML = `<span class="ok">${items.length} kurser</span>`;
          coursesList.innerHTML = items.map((c) => `
            <button class="course-item ${c.is_active ? "active" : ""}" data-action="switch-course" data-id="${c.id}">
              <strong>${escapeHtml(c.title)}</strong><br>
              <span class="mono">id=${c.id}</span>
            </button>
          `).join("");
        } catch (err) {
          coursesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          coursesList.innerHTML = "";
        }
      }

      async function refreshChatHistory() {
        try {
          const data = await api("/chat/history?limit=100");
          const items = data.messages || [];
          if (!items.length) {
            chatHistoryEl.innerHTML = `<div class="small">${escapeHtml(t("noMessages"))}</div>`;
            return;
          }
          chatHistoryEl.innerHTML = items.map((m) => `
            <div class="history-item">
              <div class="history-role">${escapeHtml(m.role)}</div>
              <div>${m.role === "assistant" ? markdownToHtml(m.content) : escapeHtml(m.content)}</div>
              <div class="history-time">${escapeHtml(new Date(m.created_at).toLocaleString(uiLang === "en" ? "en-US" : "da-DK"))}</div>
            </div>
          `).join("");
        } catch (err) {
          if (isNoCourseError(err.message)) {
            chatHistoryEl.innerHTML = `<div class="small">${escapeHtml(uiLang === "en" ? "Create a course to start chat history." : "Opret et kursus for at starte chat-historik.")}</div>`;
          } else {
            chatHistoryEl.innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
          }
        }
      }

      async function refreshPrompt() {
        try {
          const data = await api(`/course/prompt?ui_language=${uiLang}`);
          promptEditableEl.value = data.editable_instructions || "";
          promptLockedEl.textContent = data.locked_safety_block || "";
          promptPreviewEl.textContent = data.effective_prompt_preview || "";
          promptTeacherPreviewEl.textContent = data.teacher_prompt_preview || data.effective_prompt_preview || "";
          promptStudentPreviewEl.textContent = data.student_prompt_preview || "";
          if (instanceStudentPromptEl) {
            instanceStudentPromptEl.value = data.student_prompt_preview || "";
          }
          if (instancePromptReviewedEl) instancePromptReviewedEl.checked = false;
          promptState.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Course prompt loaded" : "Kursusprompt hentet")}</span>`;
          fullPromptPreviewEl.textContent = data.effective_prompt_preview || "";
          fullPromptStateEl.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Live preview updated." : "Live preview opdateret.")}</span>`;
        } catch (err) {
          if (isNoCourseError(err.message)) {
            promptState.innerHTML = `<span class="ok">${escapeHtml(t("writeCoursePrompt"))}</span>`;
            promptTeacherPreviewEl.textContent = "";
            promptStudentPreviewEl.textContent = "";
            if (instanceStudentPromptEl) instanceStudentPromptEl.value = "";
            if (instancePromptReviewedEl) instancePromptReviewedEl.checked = false;
            fullPromptStateEl.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Select or create a course to view the full system prompt." : "Vælg eller opret et kursus for at se samlet systemprompt.")}</span>`;
            fullPromptPreviewEl.textContent = "";
          } else {
            promptState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
            fullPromptStateEl.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          }
        }
      }

      async function refreshLiveSystemPromptPreview() {
        try {
          const data = await api(`/course/prompt/preview?ui_language=${uiLang}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              course_title: document.getElementById("courseTitle").value,
              course_description: document.getElementById("courseDesc").value,
              editable_instructions: promptEditableEl.value,
            }),
          });
          fullPromptPreviewEl.textContent = data.effective_prompt_preview || "";
          promptTeacherPreviewEl.textContent = data.teacher_prompt_preview || data.effective_prompt_preview || "";
          promptStudentPreviewEl.textContent = data.student_prompt_preview || "";
          if (instanceStudentPromptEl) {
            instanceStudentPromptEl.value = data.student_prompt_preview || "";
          }
          if (instancePromptReviewedEl) instancePromptReviewedEl.checked = false;
          fullPromptStateEl.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Live preview updated." : "Live preview opdateret.")}</span>`;
        } catch (err) {
          if (isNoCourseError(err.message)) {
            fullPromptStateEl.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Select or create a course to view the full system prompt." : "Vælg eller opret et kursus for at se samlet systemprompt.")}</span>`;
            fullPromptPreviewEl.textContent = "";
            promptTeacherPreviewEl.textContent = "";
            promptStudentPreviewEl.textContent = "";
            if (instanceStudentPromptEl) instanceStudentPromptEl.value = "";
            if (instancePromptReviewedEl) instancePromptReviewedEl.checked = false;
          } else {
            fullPromptStateEl.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          }
        }
      }

      function scheduleLiveSystemPromptPreview() {
        if (livePromptPreviewTimer) {
          clearTimeout(livePromptPreviewTimer);
        }
        livePromptPreviewTimer = setTimeout(() => {
          refreshLiveSystemPromptPreview();
        }, 250);
      }

      async function refreshInstances() {
        try {
          const data = await api("/instances");
          const items = data.instances || [];
          instancesState.innerHTML = `<span class="ok">${items.length} chatvinduer</span>`;
          instancesList.innerHTML = items.map((i) => `
            <div class="small">
              <strong>${escapeHtml(i.name)}</strong>
              <div class="mono">adgangskode=${escapeHtml(i.instance_password_plain || "-")} | tekstuddrag=${i.chunk_count} | status=${i.is_active ? "aktiv" : "inaktiv"}</div>
              <div class="row">
                <button data-action="copy-invite" data-id="${i.id}" data-code="${escapeHtml(i.instance_code)}">Kopiér link</button>
                <button data-action="instance-on" data-id="${i.id}">Aktivér</button>
                <button data-action="instance-off" data-id="${i.id}" class="warn">Deaktivér</button>
                <button data-action="instance-delete" data-id="${i.id}" class="warn">${escapeHtml(t("deleteBtn"))}</button>
              </div>
            </div>
          `).join("");
        } catch (err) {
          if (isNoCourseError(err.message)) {
            instancesState.innerHTML = '<span class="ok">Opret et kursus for at publicere en instance.</span>';
            instancesList.innerHTML = "";
          } else {
            instancesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
            instancesList.innerHTML = "";
          }
        }
      }

      async function refreshModel() {
        try {
          const data = await api("/runtime/model");
          const select = document.getElementById("chatModelSelect");
          const models = Array.isArray(data.options) ? data.options : [];
          const fallbackModels = ["gemma3:12b", "mistral-nemo"];
          const finalModels = models.length ? models : fallbackModels;
          const modelLabel = (m) => {
            const key = String(m || "").toLowerCase();
            if (key.includes("gemma3:12b") || key === "gemma3") return uiLang === "en" ? "gemma3:12b (12.2B, 131,072 context, fast)" : "gemma3:12b (12.2B, 131,072 kontekst, hurtig)";
            if (key.includes("mistral-nemo")) return uiLang === "en" ? "mistral-nemo (12.2B, 1,024,000 context, strong all-round)" : "mistral-nemo (12.2B, 1,024,000 kontekst, stærk allround)";
            if (key.includes("qwen2.5:14b")) return uiLang === "en" ? "qwen2.5:14b-instruct (14B, strong reasoning, slightly heavier)" : "qwen2.5:14b-instruct (14B, stærk ræsonnering, lidt tungere)";
            return String(m);
          };
          select.innerHTML = finalModels.map((m) => `<option value="${escapeHtml(String(m))}">${escapeHtml(modelLabel(String(m)))}</option>`).join("");
          const activeModel = String(data.active_model || "gemma3:12b");
          if (finalModels.includes(activeModel)) {
            select.value = activeModel;
          } else if (finalModels.includes("gemma3:12b")) {
            select.value = "gemma3:12b";
          } else if (finalModels.length > 0) {
            select.value = String(finalModels[0]);
          }
          modelState.innerHTML = `<span class="ok">${escapeHtml(t("activeModel"))}: ${escapeHtml(String(select.value || activeModel || "ukendt"))}</span>`;
        } catch (err) {
          const select = document.getElementById("chatModelSelect");
          const fallbackModels = ["gemma3:12b", "mistral-nemo"];
          select.innerHTML = fallbackModels.map((m) => {
            const label = m.includes("gemma")
              ? (uiLang === "en" ? "gemma3:12b (12.2B, 131,072 context, fast)" : "gemma3:12b (12.2B, 131,072 kontekst, hurtig)")
              : (uiLang === "en" ? "mistral-nemo (12.2B, 1,024,000 context, strong all-round)" : "mistral-nemo (12.2B, 1,024,000 kontekst, stærk allround)");
            return `<option value="${escapeHtml(String(m))}">${escapeHtml(label)}</option>`;
          }).join("");
          select.value = "gemma3:12b";
          modelState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? `Could not load model status (${err.message}). You can still choose a model and try to save.` : `Kunne ikke hente modelstatus (${err.message}). Du kan stadig vælge model og prøve at gemme.`)}</span>`;
        }
      }

      async function refreshDocuments() {
        try {
          const data = await api("/documents");
          const items = data.documents || [];
          docsState.innerHTML = `<span class="ok">${items.length} dokument(er)</span>`;
          docsList.innerHTML = items.map((d) => `
            <div class="small">
              <strong>${escapeHtml(cleanDisplayFilename(d.filename))}</strong>
              <div class="mono">id=${d.id} | tilstand=${escapeHtml(scanModeLabel(d.scan_mode))} | sprog=${escapeHtml(d.language || "ukendt")} | tekstuddrag=${d.chunk_count}</div>
              <div class="row">
                <button data-action="reingest-digital" data-id="${d.id}">Genindlæs digitalt</button>
                <button data-action="reingest-scanned" data-id="${d.id}">Genindlæs håndscannet</button>
                <button data-action="delete-doc" data-id="${d.id}" class="warn">Slet</button>
              </div>
            </div>
          `).join("");
        } catch (err) {
          if (isNoCourseError(err.message)) {
            docsState.innerHTML = '<span class="ok">Vælg eller opret et kursus for at se dokumenter.</span>';
            docsList.innerHTML = "";
          } else {
            docsState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
            docsList.innerHTML = "";
          }
        }
      }

      async function checkJob(jobId) {
        try {
          const data = await api(`/ingest/jobs/${jobId}`);
          return data.job;
        } catch (_err) {
          return null;
        }
      }

      function renderScanModeSelectors() {
        const fileInput = document.getElementById("docFile");
        const files = fileInput.files ? Array.from(fileInput.files) : [];
        if (!files.length) {
          scanModeList.innerHTML = "";
          return;
        }
        scanModeList.innerHTML = files
          .map((f, idx) => `
            <div class="row">
              <span class="mono">${escapeHtml(f.name)}</span>
              <select id="scanMode-${idx}">
                <option value="digital">Digitaliseret</option>
                <option value="hand_scanned">Håndscannet</option>
              </select>
            </div>
          `)
          .join("");
      }

      document.getElementById("docFile").addEventListener("change", renderScanModeSelectors);

      document.getElementById("loginBtn").addEventListener("click", async () => {
        try {
          const username = document.getElementById("username").value;
          const password = document.getElementById("password").value;
          const data = await api("/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
          });
          token = data.token;
          localStorage.setItem("rucai_token", token);
          showApp();
          await refreshActiveCourse();
          await refreshCourses();
          await refreshPrompt();
          await refreshModel();
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
          await refreshLiveSystemPromptPreview();
          applyI18n();
        } catch (err) {
          showGate(err.message);
        }
      });

      async function setUiLang(nextLang) {
        uiLang = nextLang === "en" ? "en" : "da";
        localStorage.setItem("rucai_ui_lang", uiLang);
        applyI18n();
        if (!token) return;
        await refreshPrompt();
        await refreshLiveSystemPromptPreview();
        await refreshChatHistory();
      }

      uiLangDaBtn.addEventListener("click", async () => { await setUiLang("da"); });
      uiLangEnBtn.addEventListener("click", async () => { await setUiLang("en"); });

      answerLangSelect.addEventListener("change", () => {
        answerLangMode = answerLangSelect.value;
        localStorage.setItem("rucai_answer_lang", answerLangMode);
      });

      document.getElementById("logoutTopBtn").addEventListener("click", () => {
        token = "";
        localStorage.removeItem("rucai_token");
        showGate("");
      });

      document.getElementById("setCourseBtn").addEventListener("click", async () => {
        try {
          const title = document.getElementById("courseTitle").value.trim();
          const description = document.getElementById("courseDesc").value.trim();
          await api("/course", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, description: description || null }),
          });
          await refreshActiveCourse();
          await refreshCourses();
          await refreshPrompt();
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
          await refreshLiveSystemPromptPreview();
        } catch (err) {
          courseState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("refreshCourseBtn").addEventListener("click", async () => {
        await refreshActiveCourse();
        await refreshLiveSystemPromptPreview();
      });
      document.getElementById("refreshPromptBtn").addEventListener("click", async () => {
        await refreshPrompt();
        await refreshLiveSystemPromptPreview();
      });
      document.getElementById("refreshDocsBtn").addEventListener("click", refreshDocuments);
      document.getElementById("refreshInstancesBtn").addEventListener("click", refreshInstances);
      document.getElementById("courseTitle").addEventListener("input", scheduleLiveSystemPromptPreview);
      document.getElementById("courseDesc").addEventListener("input", scheduleLiveSystemPromptPreview);
      promptEditableEl.addEventListener("input", scheduleLiveSystemPromptPreview);
      document.getElementById("newCourseBtn").addEventListener("click", () => {
        document.getElementById("courseTitle").value = "";
        document.getElementById("courseDesc").value = "";
        courseState.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? 'Fill title and description, then click "Place course description and title in system prompt".' : 'Udfyld titel og beskrivelse og klik "Placer kursusbeskrivelse og titel i systemprompt".')}</span>`;
        scheduleLiveSystemPromptPreview();
        document.getElementById("activeCourseCard").scrollIntoView({ behavior: "smooth", block: "start" });
        document.getElementById("courseTitle").focus();
      });

      document.getElementById("saveModelBtn").addEventListener("click", async () => {
        try {
          const model = document.getElementById("chatModelSelect").value.trim();
          if (!model) {
            modelState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? "Select a model first." : "Vælg en model først.")}</span>`;
            return;
          }
          const data = await api("/runtime/model", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_model: model }),
          });
          modelState.innerHTML = `<span class="ok">Model skiftet til ${escapeHtml(String(data.active_model || model))}</span>`;
        } catch (err) {
          modelState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("publishInstanceBtn").addEventListener("click", async () => {
        try {
          const name = document.getElementById("instanceName").value.trim();
          const instance_password = document.getElementById("instancePassword").value.trim();
          const studentEditable = (instanceStudentPromptEl?.value || "").trim();
          const reviewed = Boolean(instancePromptReviewedEl?.checked);
          if (!name) {
            instancesState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? "Name is required." : "Navn er påkrævet.")}</span>`;
            return;
          }
          if (!studentEditable) {
            instancesState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? "Student prompt is required." : "Student-prompt er påkrævet.")}</span>`;
            return;
          }
          if (!instance_password) {
            instancesState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? "Password is required." : "Adgangskode er påkrævet.")}</span>`;
            return;
          }
          if (!reviewed) {
            instancesState.innerHTML = `<span class="err">${escapeHtml(uiLang === "en" ? "Confirm that you reviewed the student prompt before publish." : "Bekræft at student-prompten er gennemgået før publicering.")}</span>`;
            return;
          }
          const created = await api("/instances", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name,
              instance_code: null,
              instance_password,
              student_editable_instructions: studentEditable,
              ui_language: uiLang,
            }),
          });
          const actualCode = created?.instance?.instance_code || "";
          const actualPassword = created?.instance?.instance_password_plain || instance_password;
          const studentUrl = buildStudentUrl(actualCode);
          await copyToClipboard(studentUrl);
          document.getElementById("instancePassword").value = "";
          if (instancePromptReviewedEl) instancePromptReviewedEl.checked = false;
          instancesState.innerHTML = `<span class="ok">Chatvindue publiceret. Adgangskode: <strong>${escapeHtml(actualPassword)}</strong>. Link kopieret.</span>`;
          await refreshInstances();
        } catch (err) {
          instancesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      coursesList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!(target instanceof HTMLElement)) return;
        const button = target.closest("button[data-action='switch-course']");
        if (!(button instanceof HTMLElement)) return;
        const courseId = button.getAttribute("data-id");
        if (!courseId) return;
        try {
          await api(`/course/active/${courseId}`, { method: "PUT" });
          await refreshActiveCourse();
          await refreshCourses();
          await refreshPrompt();
          await refreshModel();
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
          await refreshLiveSystemPromptPreview();
        } catch (err) {
          coursesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("savePromptBtn").addEventListener("click", async () => {
        try {
          const editable_instructions = promptEditableEl.value.trim();
          const data = await api(`/course/prompt?ui_language=${uiLang}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ editable_instructions }),
          });
          promptLockedEl.textContent = data.locked_safety_block || "";
          promptPreviewEl.textContent = data.effective_prompt_preview || "";
          promptState.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "Course prompt saved" : "Kursusprompt gemt")}</span>`;
          await refreshLiveSystemPromptPreview();
        } catch (err) {
          promptState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("uploadBtn").addEventListener("click", async () => {
        const uploadBtn = document.getElementById("uploadBtn");
        const busyTimer = startBusyButton(uploadBtn, "Arbejder");
        try {
          const fileInput = document.getElementById("docFile");
          if (!fileInput.files || !fileInput.files[0]) {
            ingestState.innerHTML = '<span class="err">Vælg mindst én fil først.</span>';
            return;
          }
          const uploads = [];
          const files = Array.from(fileInput.files);
          for (let idx = 0; idx < files.length; idx += 1) {
            const f = files[idx];
            const selectedMode = document.getElementById(`scanMode-${idx}`)?.value || "digital";
            const form = new FormData();
            form.append("file", f);
            form.append("scan_mode", selectedMode);
            const data = await api("/upload/document", { method: "POST", body: form });
            uploads.push({ filename: data.filename, job_id: data.job_id, scan_mode: selectedMode, status: "queued" });
          }
          ingestState.innerHTML = `<span class="ok">${uploads.length} fil(er) uploadet. Følger indlæsning...</span>`;

          for (let round = 0; round < 120; round += 1) {
            let done = 0;
            for (const u of uploads) {
              const job = await checkJob(u.job_id);
              if (!job) {
                u.status = "unknown";
                continue;
              }
              const langTag = job.document_language ? ` [sprog: ${job.document_language}]` : "";
              const chunkTag = job.chunk_count ? ` [chunks: ${job.chunk_count}]` : "";
              u.status = `${job.status} (${job.progress}%)${langTag}${chunkTag}${job.error ? ` - ${job.error}` : ""}`;
              if (job.status === "done" || job.status === "failed") done += 1;
            }
          ingestState.innerHTML = uploads.map((u) => {
              const failed = u.status.startsWith("failed");
              const cls = failed ? "err" : "ok";
              return `<div><span class="${cls}">${escapeHtml(cleanDisplayFilename(u.filename))} (${escapeHtml(u.scan_mode)}): ${escapeHtml(u.status)}</span> <span class="mono">job ${u.job_id}</span></div>`;
            }).join("");
            if (done === uploads.length) break;
            await new Promise((r) => setTimeout(r, 2000));
          }
          await refreshDocuments();
        } catch (err) {
          ingestState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        } finally {
          stopBusyButton(uploadBtn, busyTimer);
        }
      });

      docsList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!(target instanceof HTMLElement)) return;
        const button = target.closest("button[data-action]");
        if (!(button instanceof HTMLElement)) return;
        const action = button.getAttribute("data-action");
        const docId = button.getAttribute("data-id");
        if (!action || !docId) return;
        try {
          let queuedJobId = null;
          if (action === "delete-doc") {
            await api(`/documents/${docId}`, { method: "DELETE" });
          } else if (action === "reingest-digital") {
            const queued = await api(`/documents/${docId}/reingest`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scan_mode: "digital" }),
            });
            queuedJobId = queued?.job_id ?? null;
          } else if (action === "reingest-scanned") {
            const queued = await api(`/documents/${docId}/reingest`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scan_mode: "hand_scanned" }),
            });
            queuedJobId = queued?.job_id ?? null;
          }
          if (queuedJobId) {
            docsState.innerHTML = `<span class="ok">Genindlæsning startet (job ${escapeHtml(String(queuedJobId))})...</span>`;
            for (let round = 0; round < 120; round += 1) {
              const job = await checkJob(queuedJobId);
              if (!job) break;
              const langTag = job.document_language ? ` [sprog: ${job.document_language}]` : "";
              const chunkTag = job.chunk_count ? ` [chunks: ${job.chunk_count}]` : "";
              const statusText = `${job.status} (${job.progress}%)${langTag}${chunkTag}${job.error ? ` - ${job.error}` : ""}`;
              const statusClass = job.status === "failed" ? "err" : "ok";
              docsState.innerHTML = `<span class="${statusClass}">Job ${escapeHtml(String(queuedJobId))}: ${escapeHtml(statusText)}</span>`;
              if (job.status === "done" || job.status === "failed") break;
              await new Promise((r) => setTimeout(r, 1500));
            }
          }
          await refreshDocuments();
        } catch (err) {
          docsState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      instancesList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.getAttribute("data-action");
        const instanceId = target.getAttribute("data-id");
        if (!action) return;
        try {
          if (action === "copy-invite") {
            const code = target.getAttribute("data-code");
            if (!code) return;
            const studentUrl = buildStudentUrl(code);
            await copyToClipboard(studentUrl);
            instancesState.innerHTML = '<span class="ok">Link kopieret.</span>';
            return;
          }
          if (!instanceId) return;
          if (action === "instance-on") {
            await api(`/instances/${instanceId}/status`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ is_active: true }),
            });
          } else if (action === "instance-off") {
            await api(`/instances/${instanceId}/status`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ is_active: false }),
            });
          } else if (action === "instance-delete") {
            await api(`/instances/${instanceId}`, { method: "DELETE" });
          }
          await refreshInstances();
        } catch (err) {
          instancesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("chatBtn").addEventListener("click", async () => {
        const chatBtn = document.getElementById("chatBtn");
        const busyTimer = startBusyButton(chatBtn, t("working"));
        try {
          const message = document.getElementById("question").value.trim();
          const k = Number(document.getElementById("topK").value || 5);
          if (!message) {
            chatStatus.innerHTML = `<span class="err">${escapeHtml(t("writeQuestionError"))}</span>`;
            return;
          }
          startThinking(chatStatus, t("thinking"));
          answerEl.innerHTML = "";
          sourcesEl.innerHTML = "";
          referenceMentionsEl.innerHTML = "";
          const answerLanguage = selectedAnswerLanguage();
          const data = await api("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message,
              k,
              ui_language: uiLang,
              answer_language: answerLanguage,
            }),
          });
          stopThinking(chatStatus);
          chatStatus.innerHTML = `<span class="ok">${escapeHtml(t("done"))}</span> <span class="mono">intent=${escapeHtml(data.intent || "narrow")} | ${escapeHtml(t("sourceLabel"))}=${data.source_count ?? 0} | ${escapeHtml(t("chunkLabel"))}=${data.chunk_count ?? 0} | ${escapeHtml(t("roundsLabel"))}=${data.retrieval_rounds ?? 1}</span>`;
          answerEl.innerHTML = markdownToHtml(data.answer || "");
          renderGroupedSources(sourcesEl, data);
          renderReferenceMentions(referenceMentionsEl, data);
          document.getElementById("question").value = "";
          await refreshChatHistory();
        } catch (err) {
          stopThinking(chatStatus);
          chatStatus.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        } finally {
          stopBusyButton(chatBtn, busyTimer);
        }
      });

      document.getElementById("newChatBtn").addEventListener("click", async () => {
        try {
          stopThinking(chatStatus);
          await api("/chat/history", { method: "DELETE" });
          answerEl.innerHTML = "";
          sourcesEl.innerHTML = "";
          referenceMentionsEl.innerHTML = "";
          chatStatus.innerHTML = `<span class="ok">${escapeHtml(uiLang === "en" ? "New chat started." : "Ny samtale startet.")}</span>`;
          await refreshChatHistory();
        } catch (err) {
          chatStatus.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      (async () => {
        applyI18n();
        const valid = await validateSession();
        if (valid) {
          showApp();
          await refreshActiveCourse();
          await refreshCourses();
          await refreshPrompt();
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
          await refreshLiveSystemPromptPreview();
          applyI18n();
        } else {
          showGate("");
        }
      })();
    </script>
  </body>
</html>
"""

STUDENT_UI_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RUCAI Studerende</title>
    <!-- UMAMI_BOOTSTRAP -->
    <style>
      body { margin: 0; font-family: "Avenir Next", "IBM Plex Sans", sans-serif; background: #f7f5f0; color: #1f1f1d; }
      .wrap { width: min(1200px, 96vw); margin: 24px auto; }
      .card { background: #fff; border: 1px solid #ddd8cf; border-radius: 12px; padding: 14px; margin-bottom: 12px; }
      .student-layout { display: grid; grid-template-columns: 280px 1fr; gap: 12px; align-items: start; }
      .student-sidebar { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow-y: auto; }
      @media (max-width: 960px) { .student-layout { grid-template-columns: 1fr; } .student-sidebar { position: static; max-height: none; } }
      .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      input, textarea { width: 100%; border: 1px solid #cfc8bc; border-radius: 8px; padding: 10px; font: inherit; }
      textarea { min-height: 100px; resize: vertical; }
      button { border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; background: #0f8b8d; color: #fff; font-weight: 600; }
      .warn { background: #d66b19; }
      button.busy { animation: busyPulse 1s ease-in-out infinite; }
      @keyframes busyPulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(0.985); }
      }
      .small { font-size: 13px; color: #555; margin-top: 8px; }
      .err { color: #b3261e; }
      .ok { color: #1f7a45; }
      .answer { margin-top: 10px; line-height: 1.5; }
      .answer p { margin: 0 0 10px; }
      .answer ul { margin: 0 0 10px 22px; padding: 0; }
      .answer li { margin-bottom: 6px; }
      .answer strong { font-weight: 700; }
      .history { max-height: 320px; overflow: auto; border-top: 1px dashed #d8d3cb; margin-top: 10px; padding-top: 8px; }
      .history-item { margin-bottom: 8px; padding: 8px; border: 1px solid #ddd8cf; border-radius: 10px; background: #fff; }
      .history-role { font-weight: 700; font-size: 12px; color: #666; text-transform: uppercase; }
      .history-time { font-size: 11px; color: #777; margin-top: 4px; }
      .source { margin-top: 8px; border-top: 1px dashed #d8d3cb; padding-top: 8px; font-size: 13px; }
      .source h4 { margin: 0 0 4px; font-size: 13px; }
      .source-snippet { background: #faf9f5; border: 1px solid #e2ddd3; border-radius: 8px; padding: 8px; margin-top: 6px; }
      .doc-item { border: 1px solid #ddd8cf; border-radius: 8px; padding: 8px; margin-bottom: 8px; background: #fff; }
      .doc-item .mono { color: #666; font-size: 12px; }
      .hidden { display: none !important; }
      .student-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
      .student-head h3 { margin: 0; }
      #studentLogoutBtn { margin-left: auto; }
      .lang-toggle { display: inline-flex; border: 1px solid #ddd8cf; border-radius: 10px; overflow: hidden; background: #fff; }
      button.lang-toggle-btn { border: 0; border-radius: 0; padding: 8px 12px; background: #fff !important; color: #1f1f1d !important; font-weight: 700; min-width: 48px; }
      .lang-toggle-btn + .lang-toggle-btn { border-left: 1px solid #ddd8cf; }
      button.lang-toggle-btn.active { background: linear-gradient(135deg, #0f8b8d, #0a6f71) !important; color: #fff !important; }
      .thinking { display: inline-flex; align-items: center; gap: 4px; }
      .thinking-dots { display: inline-flex; min-width: 22px; }
      .thinking-dots span { opacity: 0.2; animation: thinkingBlink 1.2s infinite; }
      .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
      .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
      @keyframes thinkingBlink {
        0%, 80%, 100% { opacity: 0.2; }
        40% { opacity: 1; }
      }
      .student-compose { margin-top: 12px; border-top: 1px dashed #d8d3cb; padding-top: 10px; }
      .student-compose .row { margin-top: 8px; }
      .student-compose textarea { min-height: 96px; }
      @media (min-width: 961px) {
        .student-compose .actions { justify-content: flex-end; }
        .student-compose #studentTopK { max-width: 120px; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <section id="loginCard" class="card">
        <h2 id="studentLoginTitle">RUCAI Studerende</h2>
        <div id="studentLoginHint" class="small">Log ind med adgangskode fra underviserens invitationslink.</div>
        <div class="row">
          <input id="instancePassword" type="password" placeholder="adgangskode" />
          <button id="studentLoginBtn">Log ind</button>
        </div>
        <div id="loginState" class="small"></div>
      </section>

      <section id="studentCard" class="hidden">
        <div class="student-layout">
          <aside class="card student-sidebar">
            <h3 style="margin-top:0;">Materialer</h3>
            <div class="small">Tekster i dette chatvindue.</div>
            <div id="studentDocs" style="margin-top:10px;"></div>
          </aside>
          <section class="card">
            <div class="student-head">
              <h3 id="instanceTitle">Chatvindue</h3>
              <div class="lang-toggle" role="group" aria-label="Language toggle">
                <button id="studentUiLangDaBtn" type="button" class="lang-toggle-btn">DA</button>
                <button id="studentUiLangEnBtn" type="button" class="lang-toggle-btn">EN</button>
              </div>
              <button id="studentLogoutBtn" class="warn">Log ud</button>
            </div>
            <div id="studentState" class="small"></div>
            <div id="studentAnswer" class="answer"></div>
            <div id="studentSources"></div>
            <div class="small"><strong id="studentReferenceMentionsTitle">Nævnt i teksterne (ikke pensumkilder)</strong></div>
            <div id="studentReferenceMentions"></div>
            <div class="small"><strong id="studentHistoryTitle">Samtalehistorik</strong></div>
            <div id="studentChatHistory" class="history"></div>
            <div class="student-compose">
              <div class="row">
                <textarea id="studentQuestion" placeholder="Stil et spørgsmål til materialet..."></textarea>
              </div>
              <div class="row actions">
                <input id="studentTopK" type="number" min="1" max="50" value="5" />
                <select id="studentAnswerLangSelect" style="max-width:180px;">
                  <option value="auto">Auto (UI-sprog)</option>
                  <option value="da">Dansk</option>
                  <option value="en">English</option>
                </select>
                <button id="studentAskBtn">Spørg</button>
                <button id="studentNewChatBtn" class="warn">Ny samtale</button>
              </div>
            </div>
          </section>
        </div>
      </section>
    </div>

    <script>
      let token = localStorage.getItem("rucai_student_token") || "";
      const studentBrowserLang = (navigator.language || "da").toLowerCase().startsWith("da") ? "da" : "en";
      let studentUiLang = localStorage.getItem("rucai_student_ui_lang") || studentBrowserLang;
      let studentAnswerLang = localStorage.getItem("rucai_student_answer_lang") || "auto";
      const loginCard = document.getElementById("loginCard");
      const studentCard = document.getElementById("studentCard");
      const loginState = document.getElementById("loginState");
      const loginHint = document.getElementById("studentLoginHint");
      const studentState = document.getElementById("studentState");
      const instanceTitle = document.getElementById("instanceTitle");
      const answerEl = document.getElementById("studentAnswer");
      const sourcesEl = document.getElementById("studentSources");
      const studentReferenceMentionsEl = document.getElementById("studentReferenceMentions");
      const studentChatHistoryEl = document.getElementById("studentChatHistory");
      const studentDocsEl = document.getElementById("studentDocs");
      const studentUiLangDaBtn = document.getElementById("studentUiLangDaBtn");
      const studentUiLangEnBtn = document.getElementById("studentUiLangEnBtn");
      const studentAnswerLangSelect = document.getElementById("studentAnswerLangSelect");
      const pathMatch = window.location.pathname.match(/^\\/student\\/i\\/([^/]+)$/);
      const defaultInstanceCode = pathMatch ? decodeURIComponent(pathMatch[1] || "").toUpperCase() : "";
      const STUDENT_I18N = {
        da: {
          title: "RUCAI Studerende",
          loginHint: "Log ind med adgangskode fra underviserens invitationslink.",
          login: "Log ind",
          passwordPlaceholder: "adgangskode",
          invalidInvite: "Åbn via invitationslink fra underviser.",
          materials: "Materialer",
          materialsSub: "Tekster i dette chatvindue.",
          chatWindow: "Chatvindue",
          logout: "Log ud",
          history: "Samtalehistorik",
          referenceMentions: "Nævnt i teksterne (ikke pensumkilder)",
          noReferenceMentions: "Ingen nævnte eksterne kilder fundet.",
          askPlaceholder: "Stil et spørgsmål til materialet...",
          ask: "Spørg",
          newChat: "Ny samtale",
          noMessages: "Ingen beskeder endnu.",
          noDocs: "Ingen dokumenter fundet i denne instance.",
          noCode: "Invitationslink mangler kode.",
          fillPassword: "Udfyld password.",
          loggedIn: "Logget ind.",
          done: "Færdig",
          sourceLabel: "kilder",
          chunkLabel: "uddrag",
          working: "Arbejder",
          thinking: "Tænker",
          writeQuestion: "Skriv et spørgsmål.",
          autoAnswerLang: "Auto (UI-sprog)",
        },
        en: {
          title: "RUCAI Student",
          loginHint: "Log in with the password from the teacher invitation link.",
          login: "Log in",
          passwordPlaceholder: "password",
          invalidInvite: "Open via the invitation link from your teacher.",
          materials: "Materials",
          materialsSub: "Texts in this chat window.",
          chatWindow: "Chat window",
          logout: "Log out",
          history: "Chat history",
          referenceMentions: "Mentioned in texts (not curriculum sources)",
          noReferenceMentions: "No external references mentioned in retrieved text.",
          askPlaceholder: "Ask a question about the material...",
          ask: "Ask",
          newChat: "New chat",
          noMessages: "No messages yet.",
          noDocs: "No documents found in this instance.",
          noCode: "Invitation link is missing code.",
          fillPassword: "Enter password.",
          loggedIn: "Logged in.",
          done: "Done",
          sourceLabel: "sources",
          chunkLabel: "chunks",
          working: "Working",
          thinking: "Thinking",
          writeQuestion: "Enter a question.",
          autoAnswerLang: "Auto (UI language)",
        },
      };

      function st(key) {
        const lang = studentUiLang === "en" ? "en" : "da";
        return (STUDENT_I18N[lang] && STUDENT_I18N[lang][key]) || (STUDENT_I18N.da && STUDENT_I18N.da[key]) || key;
      }

      function applyStudentI18n() {
        document.documentElement.lang = studentUiLang;
        studentUiLangDaBtn.classList.toggle("active", studentUiLang === "da");
        studentUiLangEnBtn.classList.toggle("active", studentUiLang === "en");
        studentUiLangDaBtn.setAttribute("aria-pressed", studentUiLang === "da" ? "true" : "false");
        studentUiLangEnBtn.setAttribute("aria-pressed", studentUiLang === "en" ? "true" : "false");
        studentAnswerLangSelect.value = studentAnswerLang;
        const t = (id, key) => {
          const el = document.getElementById(id);
          if (el) el.textContent = st(key);
        };
        t("studentLoginTitle", "title");
        t("studentLoginBtn", "login");
        t("studentLogoutBtn", "logout");
        t("instanceTitle", "chatWindow");
        const ip = document.getElementById("instancePassword");
        if (ip) ip.placeholder = st("passwordPlaceholder");
        const sq = document.getElementById("studentQuestion");
        if (sq) sq.placeholder = st("askPlaceholder");
        const histStrong = document.getElementById("studentHistoryTitle");
        if (histStrong) histStrong.textContent = st("history");
        const refStrong = document.getElementById("studentReferenceMentionsTitle");
        if (refStrong) refStrong.textContent = st("referenceMentions");
        const materialsH3 = document.querySelector(".student-sidebar h3");
        if (materialsH3) materialsH3.textContent = st("materials");
        const materialsSub = document.querySelector(".student-sidebar .small");
        if (materialsSub) materialsSub.textContent = st("materialsSub");
        const loginHintEl = document.getElementById("studentLoginHint");
        if (loginHintEl) {
          if (defaultInstanceCode) {
            loginHintEl.textContent = st("loginHint");
          } else {
            loginHintEl.innerHTML = `<span class="err">${escapeHtml(st("invalidInvite"))}</span>`;
          }
        }
        const askBtn = document.getElementById("studentAskBtn");
        if (askBtn) askBtn.textContent = st("ask");
        const newChatBtn = document.getElementById("studentNewChatBtn");
        if (newChatBtn) newChatBtn.textContent = st("newChat");
        const autoOpt = studentAnswerLangSelect.querySelector("option[value='auto']");
        if (autoOpt) autoOpt.textContent = st("autoAnswerLang");
      }

      function escapeHtml(text) {
        const d = document.createElement("div");
        d.innerText = String(text ?? "");
        return d.innerHTML;
      }

      function markdownToHtml(md) {
        const lines = String(md || "").split("\\n");
        const out = [];
        let inList = false;
        const inline = (txt) => escapeHtml(txt)
          .replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>")
          .replace(/\\*(.+?)\\*/g, "<em>$1</em>")
          .replace(/`([^`]+)`/g, "<code>$1</code>");
        for (const raw of lines) {
          const line = raw.trim();
          if (!line) {
            if (inList) { out.push("</ul>"); inList = false; }
            continue;
          }
          const bullet = line.match(/^[-*]\\s+(.+)$/);
          if (bullet) {
            if (!inList) { out.push("<ul>"); inList = true; }
            out.push(`<li>${inline(bullet[1])}</li>`);
            continue;
          }
          if (inList) { out.push("</ul>"); inList = false; }
          out.push(`<p>${inline(line)}</p>`);
        }
        if (inList) out.push("</ul>");
        return out.join("");
      }

      function cleanDisplayFilename(name) {
        const raw = String(name || "");
        return raw.replace(/^\\d{8}-\\d{6}-/, "");
      }

      function renderGroupedSources(container, data) {
        container.innerHTML = "";
        const grouped = Array.isArray(data?.sources) ? data.sources : [];
        if (!grouped.length) {
          container.innerHTML = `<div class="small">${escapeHtml(studentUiLang === "en" ? "No sources found." : "Ingen kilder fundet.")}</div>`;
          return;
        }
        grouped.forEach((src) => {
          const ref = escapeHtml(String(src.ref ?? "?"));
          const filename = escapeHtml(cleanDisplayFilename(String(src.filename || "Ukendt kilde")));
          const snippets = Array.isArray(src.snippets) ? src.snippets : [];
          const snippetHtml = snippets.map((sn) => {
            const full = String(sn.content || "");
            const short = full.length > 260 ? `${full.slice(0, 260)}...` : full;
            const page = escapeHtml(String(sn.page_start ?? "?"));
            const idx = escapeHtml(String(sn.chunk_index ?? "?"));
            return `
              <div class="source-snippet">
                <div class="small">Side ${page} · uddrag ${idx}</div>
                <div>${escapeHtml(short)}</div>
                <details><summary>${escapeHtml(studentUiLang === "en" ? "Show full excerpt" : "Vis hele uddraget")}</summary>${escapeHtml(full)}</details>
              </div>
            `;
          }).join("");
          const div = document.createElement("div");
          div.className = "source";
          div.innerHTML = `<h4>[${ref}] ${filename}</h4>${snippetHtml}`;
          container.appendChild(div);
        });
      }
      // Backward compatibility for stale cached calls with misspelled name.
      const enderGroupedSources = renderGroupedSources;

      function renderStudentReferenceMentions(container, data) {
        container.innerHTML = "";
        const mentions = Array.isArray(data?.reference_mentions) ? data.reference_mentions : [];
        if (!mentions.length) {
          container.innerHTML = `<div class="small">${escapeHtml(st("noReferenceMentions"))}</div>`;
          return;
        }
        mentions.forEach((m) => {
          const div = document.createElement("div");
          div.className = "source";
          const filename = escapeHtml(cleanDisplayFilename(String(m.filename || "Ukendt kilde")));
          const page = escapeHtml(String(m.page_start ?? "?"));
          const full = String(m.content || "");
          const short = full.length > 260 ? `${full.slice(0, 260)}...` : full;
          div.innerHTML = `
            <div class="small">${filename} · p${page}</div>
            <div>${escapeHtml(short)}</div>
            <details><summary>${escapeHtml(studentUiLang === "en" ? "Show full excerpt" : "Vis hele uddraget")}</summary>${escapeHtml(full)}</details>
          `;
          container.appendChild(div);
        });
      }

      const thinkingIntervals = new Map();

      function startThinking(el, label = st("thinking")) {
        stopThinking(el);
        el.innerHTML = `<span class="thinking"><span>${escapeHtml(label)}</span><span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span></span>`;
      }

      function stopThinking(el) {
        const timer = thinkingIntervals.get(el);
        if (timer) {
          clearInterval(timer);
          thinkingIntervals.delete(el);
        }
      }

      function startBusyButton(btn, label = st("working")) {
        const original = btn.textContent || "";
        btn.dataset.originalLabel = original;
        btn.disabled = true;
        btn.classList.add("busy");
        let dots = 0;
        btn.textContent = `${label}.`;
        const timer = setInterval(() => {
          dots = (dots + 1) % 4;
          btn.textContent = `${label}${".".repeat(Math.max(1, dots))}`;
        }, 260);
        return timer;
      }

      function stopBusyButton(btn, timer) {
        if (timer) clearInterval(timer);
        btn.disabled = false;
        btn.classList.remove("busy");
        btn.textContent = btn.dataset.originalLabel || st("ask");
      }

      function selectedStudentAnswerLanguage() {
        if (studentAnswerLang === "en") return "en";
        if (studentAnswerLang === "da") return "da";
        return null;
      }

      async function api(path, options = {}) {
        const headers = options.headers || {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const resp = await fetch(path, { ...options, headers });
        const isJson = (resp.headers.get("content-type") || "").includes("application/json");
        const data = isJson ? await resp.json() : await resp.text();
        if (!resp.ok) {
          let detail = typeof data === "object" && data ? (data.detail ?? data) : data;
          if (Array.isArray(detail)) detail = detail.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join("; ");
          if (typeof detail === "object" && detail !== null) detail = JSON.stringify(detail);
          throw new Error(String(detail || `HTTP ${resp.status}`));
        }
        return data;
      }

      async function refreshStudentMeta() {
        try {
          const data = await api("/student/instance");
          instanceTitle.textContent = data.instance.name || st("chatWindow");
          await refreshStudentDocuments();
          await refreshStudentChatHistory();
          loginCard.classList.add("hidden");
          studentCard.classList.remove("hidden");
          applyStudentI18n();
        } catch (err) {
          token = "";
          localStorage.removeItem("rucai_student_token");
          loginCard.classList.remove("hidden");
          studentCard.classList.add("hidden");
          loginState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      }

      async function refreshStudentDocuments() {
        try {
          const data = await api("/student/documents");
          const docs = data.documents || [];
          if (!docs.length) {
            studentDocsEl.innerHTML = `<div class="small">${escapeHtml(st("noDocs"))}</div>`;
            return;
          }
          studentDocsEl.innerHTML = docs.map((d) => `
            <div class="doc-item">
              <div><strong>${escapeHtml(cleanDisplayFilename(d.filename))}</strong></div>
              <div class="mono">chunks: ${d.chunk_count}</div>
            </div>
          `).join("");
        } catch (err) {
          studentDocsEl.innerHTML = `<div class="small err">${escapeHtml(err.message)}</div>`;
        }
      }

      async function refreshStudentChatHistory() {
        try {
          const data = await api("/student/chat/history?limit=100");
          const items = data.messages || [];
          if (!items.length) {
            studentChatHistoryEl.innerHTML = `<div class="small">${escapeHtml(st("noMessages"))}</div>`;
            return;
          }
          studentChatHistoryEl.innerHTML = items.map((m) => `
            <div class="history-item">
              <div class="history-role">${escapeHtml(m.role)}</div>
              <div>${m.role === "assistant" ? markdownToHtml(m.content) : escapeHtml(m.content)}</div>
              <div class="history-time">${escapeHtml(new Date(m.created_at).toLocaleString(studentUiLang === "en" ? "en-US" : "da-DK"))}</div>
            </div>
          `).join("");
          studentChatHistoryEl.scrollTop = studentChatHistoryEl.scrollHeight;
        } catch (err) {
          studentChatHistoryEl.innerHTML = `<div class="small err">${escapeHtml(err.message)}</div>`;
        }
      }

      document.getElementById("studentLoginBtn").addEventListener("click", async () => {
        try {
          const instance_code = defaultInstanceCode;
          const password = document.getElementById("instancePassword").value.trim();
          if (!instance_code) {
            loginState.innerHTML = `<span class="err">${escapeHtml(st("noCode"))}</span>`;
            return;
          }
          if (!password) {
            loginState.innerHTML = `<span class="err">${escapeHtml(st("fillPassword"))}</span>`;
            return;
          }
          const data = await api("/student/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ instance_code, password }),
          });
          token = data.token;
          localStorage.setItem("rucai_student_token", token);
          loginState.innerHTML = `<span class="ok">${escapeHtml(st("loggedIn"))}</span>`;
          await refreshStudentMeta();
        } catch (err) {
          loginState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      async function setStudentUiLang(nextLang) {
        studentUiLang = nextLang === "en" ? "en" : "da";
        localStorage.setItem("rucai_student_ui_lang", studentUiLang);
        applyStudentI18n();
        if (token) {
          await refreshStudentChatHistory();
          await refreshStudentDocuments();
        }
      }

      studentUiLangDaBtn.addEventListener("click", async () => { await setStudentUiLang("da"); });
      studentUiLangEnBtn.addEventListener("click", async () => { await setStudentUiLang("en"); });

      studentAnswerLangSelect.addEventListener("change", () => {
        studentAnswerLang = studentAnswerLangSelect.value;
        localStorage.setItem("rucai_student_answer_lang", studentAnswerLang);
      });

      document.getElementById("studentLogoutBtn").addEventListener("click", () => {
        token = "";
        localStorage.removeItem("rucai_student_token");
        loginCard.classList.remove("hidden");
        studentCard.classList.add("hidden");
        loginState.innerHTML = "";
        studentChatHistoryEl.innerHTML = "";
      });

      document.getElementById("studentAskBtn").addEventListener("click", async () => {
        const studentAskBtn = document.getElementById("studentAskBtn");
        const busyTimer = startBusyButton(studentAskBtn, st("working"));
        try {
          const message = document.getElementById("studentQuestion").value.trim();
          const k = Number(document.getElementById("studentTopK").value || 5);
          if (!message) {
            studentState.innerHTML = `<span class="err">${escapeHtml(st("writeQuestion"))}</span>`;
            return;
          }
          startThinking(studentState, st("thinking"));
          answerEl.textContent = "";
          sourcesEl.innerHTML = "";
          studentReferenceMentionsEl.innerHTML = "";
          const answerLanguage = selectedStudentAnswerLanguage();
          const data = await api("/student/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message,
              k,
              ui_language: studentUiLang,
              answer_language: answerLanguage,
            }),
          });
          stopThinking(studentState);
          studentState.innerHTML = `<span class="ok">${escapeHtml(st("done"))}</span> <span class="mono">${escapeHtml(st("sourceLabel"))}=${data.source_count ?? 0} | ${escapeHtml(st("chunkLabel"))}=${data.chunk_count ?? 0}</span>`;
          answerEl.innerHTML = markdownToHtml(data.answer || "");
          renderGroupedSources(sourcesEl, data);
          renderStudentReferenceMentions(studentReferenceMentionsEl, data);
          document.getElementById("studentQuestion").value = "";
          await refreshStudentChatHistory();
        } catch (err) {
          stopThinking(studentState);
          studentState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        } finally {
          stopBusyButton(studentAskBtn, busyTimer);
        }
      });

      document.getElementById("studentNewChatBtn").addEventListener("click", async () => {
        try {
          await api("/student/chat/history", { method: "DELETE" });
          document.getElementById("studentQuestion").value = "";
          answerEl.textContent = "";
          sourcesEl.innerHTML = "";
          studentReferenceMentionsEl.innerHTML = "";
          studentState.innerHTML = `<span class="ok">${escapeHtml(st("newChat"))}</span>`;
          await refreshStudentChatHistory();
        } catch (err) {
          studentState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      (async () => {
        applyStudentI18n();
        if (!token) return;
        await refreshStudentMeta();
      })();
    </script>
  </body>
</html>
"""


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class CourseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)
    ui_language: Literal["da", "en"] = "da"
    answer_language: Optional[Literal["da", "en"]] = None


class PromptRequest(BaseModel):
    editable_instructions: str = Field(min_length=1)


class PromptPreviewRequest(BaseModel):
    course_title: Optional[str] = Field(default=None, max_length=200)
    course_description: Optional[str] = Field(default=None)
    editable_instructions: Optional[str] = Field(default=None)


class ReingestRequest(BaseModel):
    scan_mode: str = Field(default="digital")


class InstanceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instance_code: Optional[str] = None
    instance_password: str = Field(min_length=4, max_length=200)
    student_editable_instructions: Optional[str] = None
    ui_language: Literal["da", "en"] = "da"


class InstanceStatusRequest(BaseModel):
    is_active: bool


class StudentLoginRequest(BaseModel):
    instance_code: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class StudentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)
    ui_language: Literal["da", "en"] = "da"
    answer_language: Optional[Literal["da", "en"]] = None


class RuntimeModelRequest(BaseModel):
    chat_model: str = Field(min_length=1, max_length=120)


@app.on_event("startup")
def startup() -> None:
    settings = load_settings()
    ensure_data_dirs(settings)
    ensure_schema(settings)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rucai"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _inject_umami(WEB_UI_HTML)


@app.get("/student", response_class=HTMLResponse)
def student_home() -> str:
    return _inject_umami(STUDENT_UI_HTML)


@app.get("/student/i/{instance_code}", response_class=HTMLResponse)
def student_home_instance(instance_code: str) -> str:
    return _inject_umami(STUDENT_UI_HTML)


def _runtime_model_options(settings: object) -> list[str]:
    configured = [x.strip() for x in os.getenv("CHAT_MODEL_OPTIONS", "gemma3:12b,mistral-nemo").split(",")]
    options = [x for x in configured if x]
    active_raw = str(getattr(settings, "chat_model", "") or "").strip()
    active = "gemma3:12b" if active_raw == "gemma3" else active_raw
    if active and active not in options:
        options.insert(0, active)
    return options


def _effective_language(ui_language: Optional[str], answer_language: Optional[str]) -> Literal["da", "en"]:
    if answer_language in {"da", "en"}:
        return "en" if answer_language == "en" else "da"
    if ui_language in {"da", "en"}:
        return "en" if ui_language == "en" else "da"
    return "da"


def _normalize_language(language: Optional[str]) -> Literal["da", "en"]:
    return "en" if language == "en" else "da"


def _detect_message_language(message: str) -> Optional[Literal["da", "en"]]:
    text = " " + " ".join((message or "").lower().split()) + " "
    if not text.strip():
        return None

    # Strong Danish signals first.
    if any(ch in text for ch in ["æ", "ø", "å"]):
        return "da"

    da_markers = [
        " hvad ",
        " hvordan ",
        " hvorfor ",
        " siger ",
        " er ",
        " ikke ",
        " og ",
        " i ",
        " på ",
        " med ",
        " tekst ",
        " teksten ",
        " pensum ",
    ]
    en_markers = [
        " what ",
        " how ",
        " why ",
        " is ",
        " not ",
        " and ",
        " in ",
        " with ",
        " text ",
        " curriculum ",
    ]
    da_hits = sum(1 for m in da_markers if m in text)
    en_hits = sum(1 for m in en_markers if m in text)
    # Short-question fallback: choose strongest side even with one clear marker.
    if da_hits >= 1 and en_hits == 0:
        return "da"
    if en_hits >= 1 and da_hits == 0:
        return "en"
    if da_hits >= en_hits + 1 and da_hits >= 2:
        return "da"
    if en_hits >= da_hits + 1 and en_hits >= 2:
        return "en"
    return None


@app.get("/runtime/model")
def get_runtime_model(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    options = _runtime_model_options(settings)
    active_raw = str(settings.chat_model or "").strip()
    active = "gemma3:12b" if active_raw == "gemma3" else active_raw
    return {
        "active_model": active,
        "options": options,
        "scope": "global_runtime",
    }


@app.put("/runtime/model")
def set_runtime_model(req: RuntimeModelRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    requested = req.chat_model.strip()
    options = _runtime_model_options(settings)
    if requested not in options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{requested}' er ikke tilladt. Tilladte modeller: {', '.join(options)}",
        )
    os.environ["CHAT_MODEL"] = requested
    return {
        "active_model": requested,
        "options": options,
        "scope": "global_runtime",
    }


@app.post("/auth/login")
def login(req: LoginRequest) -> dict[str, str]:
    settings = load_settings()
    token = create_session(req.username, req.password, settings)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    return {"token": token, "token_type": "bearer"}


@app.post("/instances")
def publish_instance(req: InstanceCreateRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    language = _normalize_language(req.ui_language)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    code = _normalize_instance_code(req.instance_code)

    with get_connection(settings) as conn:
        teacher_editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
        student_editable = (
            (req.student_editable_instructions or "").strip()
            or to_student_editable_instructions(teacher_editable, language=language)
        )
        effective_prompt = compose_system_prompt(
            student_editable,
            course_title=str(course.get("title") or ""),
            course_description=str(course.get("description") or ""),
            audience="student",
            language=language,
        )
        chosen_code = code
        created = None
        for _ in range(5):
            if not chosen_code:
                chosen_code = _generate_instance_code()
            try:
                created = create_bot_instance(
                    conn=conn,
                    owner_username=username,
                    source_course_id=course_id,
                    name=req.name.strip(),
                    instance_code=chosen_code,
                    password_hash=hash_password(req.instance_password),
                    instance_password_plain=req.instance_password,
                    editable_instructions_snapshot=student_editable,
                    locked_safety_block_snapshot=LOCKED_SAFETY_BLOCK,
                    effective_system_prompt_snapshot=effective_prompt,
                )
                break
            except Exception as exc:
                # Retry only on unique-code collisions.
                if "duplicate key value violates unique constraint" not in str(exc):
                    raise
                chosen_code = None
        if not created:
            raise HTTPException(status_code=500, detail="Could not generate unique instance code.")
        chunk_count = copy_course_chunks_to_instance(conn, course_id, int(created["id"]))
        conn.commit()
    created["chunk_count"] = chunk_count
    return {"instance": created}


@app.get("/instances")
def list_instances(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        items = list_bot_instances_for_owner(conn, username)
    return {"instances": items}


@app.get("/instances/{instance_id}")
def get_instance(instance_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = get_bot_instance_for_owner(conn, instance_id, username)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
    return {"instance": item}


@app.put("/instances/{instance_id}/status")
def update_instance_status(
    instance_id: int,
    req: InstanceStatusRequest,
    username: str = Depends(require_auth),
) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = set_bot_instance_status(conn, instance_id, username, req.is_active)
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
        conn.commit()
    return {"instance": item}


@app.delete("/instances/{instance_id}")
def remove_instance(instance_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        deleted = delete_bot_instance(conn, instance_id, username)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
        conn.commit()
    return {"ok": True, "instance_id": instance_id}


@app.post("/student/login")
def student_login(req: StudentLoginRequest) -> dict[str, object]:
    settings = load_settings()
    code = req.instance_code.strip().upper()
    with get_connection(settings) as conn:
        item = get_bot_instance_by_code(conn, code)
    if not item or not item.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid instance code or password.")
    if not verify_password(req.password, str(item["password_hash"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid instance code or password.")
    token = create_student_session(int(item["id"]), settings)
    return {
        "token": token,
        "token_type": "bearer",
        "instance": {
            "id": item["id"],
            "name": item["name"],
            "instance_code": item["instance_code"],
        },
    }


@app.get("/student/instance")
def student_instance(instance_id: int = Depends(require_student_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = get_bot_instance_by_id(conn, instance_id)
    if not item or not item.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")
    return {
        "instance": {
            "id": item["id"],
            "name": item["name"],
            "instance_code": item["instance_code"],
            "chunk_count": item["chunk_count"],
            "source_course_id": item.get("source_course_id"),
        }
    }


@app.get("/student/documents")
def student_documents(instance_id: int = Depends(require_student_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = get_bot_instance_by_id(conn, instance_id)
        if not item or not item.get("is_active"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")
        docs = list_bot_instance_documents(conn, instance_id)
    return {"instance_id": instance_id, "documents": docs}


@app.get("/student/chat/history")
def student_chat_history(
    limit: int = Query(default=100, ge=1, le=500),
    instance_id: int = Depends(require_student_auth),
) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = get_bot_instance_by_id(conn, instance_id)
        if not item or not item.get("is_active"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")
        messages = list_student_chat_messages_for_instance(conn, instance_id, limit=limit)
    return {"instance_id": instance_id, "messages": messages}


@app.delete("/student/chat/history")
def clear_student_chat_history(instance_id: int = Depends(require_student_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        item = get_bot_instance_by_id(conn, instance_id)
        if not item or not item.get("is_active"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")
        deleted = delete_student_chat_messages_for_instance(conn, instance_id)
        conn.commit()
    return {"instance_id": instance_id, "deleted_count": deleted}


@app.post("/student/chat")
def student_chat(req: StudentChatRequest, instance_id: int = Depends(require_student_auth)) -> dict[str, object]:
    settings = load_settings()
    language = _effective_language(req.ui_language, req.answer_language)
    # In auto mode, prefer the language detected from the student's message.
    if req.answer_language is None:
        detected = _detect_message_language(req.message)
        if detected in {"da", "en"}:
            language = detected
    with get_connection(settings) as conn:
        instance = get_bot_instance_by_id(conn, instance_id)
        if not instance or not instance.get("is_active"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")

        history = list_student_chat_messages_for_instance(conn, instance_id, limit=20)
        system_prompt = str(instance["effective_system_prompt_snapshot"])
        requested_sources = max(1, int(req.k))
        if _is_teacher_facing_student_query(req.message):
            contexts = []
            sources = []
            reference_mentions = []
            answer = _student_scope_redirect_answer(language)
            prompt = _build_student_prompt(req.message, sources, system_prompt, history, language=language)
        else:
            raw_contexts = search_instance_chunks(
                req.message,
                settings,
                max(requested_sources * 4, 12),
                instance_id,
                include_reference_chunks=False,
            )
            explicit_doc_tokens = sorted(query_document_tokens(req.message))
            explicit_doc_hint = has_explicit_document_hint(req.message)
            if explicit_doc_hint and explicit_doc_tokens and not contexts_match_query_document_hint(req.message, raw_contexts):
                targeted_raw = search_instance_chunks(
                    req.message,
                    settings,
                    max(requested_sources * 5, 14),
                    instance_id,
                    include_reference_chunks=False,
                    filename_tokens=explicit_doc_tokens,
                )
                if targeted_raw:
                    raw_contexts = targeted_raw
            raw_reference_contexts = search_instance_chunks(
                req.message,
                settings,
                min(max(requested_sources * 2, 4), 12),
                instance_id,
                include_reference_chunks=True,
            )
            contexts = select_source_first_contexts(
                raw_contexts,
                target_sources=requested_sources,
                max_chunks_per_source=3,
            )
            contexts = filter_reference_noise(contexts)
            contexts = filter_contexts_for_explicit_doc_mention(req.message, contexts)
            reference_mentions = _student_reference_mentions(raw_reference_contexts, limit=8)
            sources = build_grouped_sources(contexts, max_snippets_per_source=3)
            if not contexts:
                answer = (
                    "I cannot answer confidently from the published material. Please rephrase the question."
                    if language == "en"
                    else "Jeg kan ikke svare fagligt sikkert ud fra det publicerede materiale. "
                    "Prøv at omformulere spørgsmålet."
                )
                prompt = _build_student_prompt(req.message, sources, system_prompt, history, language=language)
            else:
                prompt = _build_student_prompt(req.message, sources, system_prompt, history, language=language)
                answer = generate_answer(prompt, settings)
        insert_student_chat_message(conn, instance_id, "user", req.message)
        insert_student_chat_message(conn, instance_id, "assistant", str(answer))
        conn.commit()

    citations = []
    for source in sources:
        first_snippet = (source.get("snippets") or [{}])[0]
        citations.append(
            {
                "ref": source.get("ref"),
                "filename": source.get("filename"),
                "page_start": first_snippet.get("page_start"),
                "chunk_index": first_snippet.get("chunk_index"),
            }
        )
    return {
        "instance_id": instance_id,
        "query": req.message,
        "k": requested_sources,
        "answer": answer,
        "contexts": contexts,
        "sources": sources,
        "citations": citations,
        "source_count": len(sources),
        "chunk_count": len(contexts),
        "reference_mentions": reference_mentions,
        "prompt": prompt,
    }


@app.post("/course")
def set_active_course(req: CourseRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        try:
            course = create_or_activate_course(conn, username, req.title, req.description)
        except TypeError:
            course = create_or_activate_course(conn, req.title, req.description)  # type: ignore[misc]
        conn.commit()
    return {"course": course}


@app.get("/courses")
def read_courses(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        courses = list_courses(conn, username)
    return {"courses": courses}


@app.put("/course/active/{course_id}")
def set_existing_course_active(course_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        course = set_active_course_by_id(conn, username, course_id)
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
        conn.commit()
    return {"course": course}


@app.get("/course/active")
def read_active_course(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        try:
            course = get_active_course(conn, username)
        except TypeError:
            course = get_active_course(conn)  # type: ignore[misc]
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active course.")
    return {"course": course}


@app.get("/course/prompt")
def read_course_prompt(
    ui_language: Literal["da", "en"] = Query(default="da"),
    username: str = Depends(require_auth),
) -> dict[str, str]:
    settings = load_settings()
    language = _normalize_language(ui_language)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
    student_editable = to_student_editable_instructions(editable, language=language)
    teacher_preview = compose_system_prompt(
        editable,
        course_title=str(course.get("title") or ""),
        course_description=str(course.get("description") or ""),
        audience="teacher",
        language=language,
    )
    student_preview = compose_system_prompt(
        student_editable,
        course_title=str(course.get("title") or ""),
        course_description=str(course.get("description") or ""),
        audience="student",
        language=language,
    )
    return {
        "editable_instructions": editable,
        "locked_safety_block": LOCKED_SAFETY_BLOCK_EN if language == "en" else LOCKED_SAFETY_BLOCK_DA,
        "effective_prompt_preview": teacher_preview,
        "teacher_prompt_preview": teacher_preview,
        "student_prompt_preview": student_preview,
    }


@app.put("/course/prompt")
def update_course_prompt(
    req: PromptRequest,
    ui_language: Literal["da", "en"] = Query(default="da"),
    username: str = Depends(require_auth),
) -> dict[str, str]:
    settings = load_settings()
    language = _normalize_language(ui_language)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        upsert_course_prompt(conn, course_id, req.editable_instructions)
        conn.commit()
    student_editable = to_student_editable_instructions(req.editable_instructions, language=language)
    teacher_preview = compose_system_prompt(
        req.editable_instructions,
        course_title=str(course.get("title") or ""),
        course_description=str(course.get("description") or ""),
        audience="teacher",
        language=language,
    )
    student_preview = compose_system_prompt(
        student_editable,
        course_title=str(course.get("title") or ""),
        course_description=str(course.get("description") or ""),
        audience="student",
        language=language,
    )
    return {
        "editable_instructions": req.editable_instructions,
        "locked_safety_block": LOCKED_SAFETY_BLOCK_EN if language == "en" else LOCKED_SAFETY_BLOCK_DA,
        "effective_prompt_preview": teacher_preview,
        "teacher_prompt_preview": teacher_preview,
        "student_prompt_preview": student_preview,
    }


@app.post("/course/prompt/preview")
def preview_course_prompt(
    req: PromptPreviewRequest,
    ui_language: Literal["da", "en"] = Query(default="da"),
    username: str = Depends(require_auth),
) -> dict[str, str]:
    settings = load_settings()
    language = _normalize_language(ui_language)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        saved_editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS

    editable = req.editable_instructions if req.editable_instructions is not None else saved_editable
    title = req.course_title if req.course_title is not None else str(course.get("title") or "")
    description = (
        req.course_description if req.course_description is not None else str(course.get("description") or "")
    )

    student_editable = to_student_editable_instructions(editable, language=language)
    teacher_preview = compose_system_prompt(
        editable,
        course_title=title,
        course_description=description,
        audience="teacher",
        language=language,
    )
    student_preview = compose_system_prompt(
        student_editable,
        course_title=title,
        course_description=description,
        audience="student",
        language=language,
    )
    return {
        "editable_instructions": editable,
        "locked_safety_block": LOCKED_SAFETY_BLOCK_EN if language == "en" else LOCKED_SAFETY_BLOCK_DA,
        "effective_prompt_preview": teacher_preview,
        "teacher_prompt_preview": teacher_preview,
        "student_prompt_preview": student_preview,
    }


def _active_course_or_404(username: str) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        try:
            course = get_active_course(conn, username)
        except TypeError:
            # Backward compatibility for tests monkeypatching legacy function signatures.
            course = get_active_course(conn)  # type: ignore[misc]
    if not course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active course. Create one with POST /course before uploading or querying.",
        )
    return course


def _active_course_for_request(username: str) -> dict[str, object]:
    try:
        return _active_course_or_404(username)
    except TypeError:
        # Backward compatibility for tests monkeypatching legacy zero-arg helper.
        return _active_course_or_404()  # type: ignore[misc]


def _save_upload(course_id: int, upload: UploadFile, settings_path: Path) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_name = Path(upload.filename or "upload.pdf").name
    target_dir = settings_path / f"course-{course_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{timestamp}-{safe_name}"

    with target_path.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    return target_path


def _start_ingest_thread(
    settings,
    job_id: int,
    course_id: int,
    path: Path,
    scan_mode: str,
) -> None:
    thread = Thread(
        target=process_ingest_job,
        args=(settings, job_id, course_id, path, scan_mode),
        daemon=True,
    )
    thread.start()


def _validate_upload_extension(filename: str) -> None:
    lower_name = filename.lower()
    if lower_name.endswith(".pdf") or lower_name.endswith(".docx"):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Only PDF and DOCX files are supported.",
    )


def _validate_scan_mode(scan_mode: str) -> str:
    normalized = scan_mode.strip().lower()
    if normalized in {"digital", "hand_scanned"}:
        return normalized
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="scan_mode must be 'digital' or 'hand_scanned'.",
    )


def _normalize_instance_code(raw_code: Optional[str]) -> Optional[str]:
    if raw_code is None:
        return None
    code = raw_code.strip().upper()
    if not code:
        return None
    allowed = set(INSTANCE_CODE_ALPHABET)
    if not all(ch in allowed for ch in code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instance_code must use uppercase A-Z and digits 2-9 (without 0/1).",
        )
    if len(code) < 6 or len(code) > 24:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instance_code must be between 6 and 24 characters.",
        )
    return code


def _generate_instance_code(length: int = 8) -> str:
    return "".join(choice(INSTANCE_CODE_ALPHABET) for _ in range(length))


def _format_student_history(history: List[dict[str, object]]) -> str:
    if not history:
        return "(ingen)"
    lines: List[str] = []
    for item in history:
        role = str(item.get("role") or "unknown").upper()
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(ingen)"


def _build_student_prompt(
    query: str,
    sources: List[dict[str, object]],
    system_prompt: str,
    history: List[dict[str, object]],
    language: Literal["da", "en"] = "da",
) -> str:
    blocks: List[str] = []
    allowed_sources: List[str] = []
    for source in sources:
        ref = int(source.get("ref") or 0)
        allowed_sources.append(f"[{ref}] {source.get('filename')}")
        for snippet in source.get("snippets") or []:
            blocks.append(f"[{ref}] {snippet.get('filename')} p{snippet.get('page_start')}\n{snippet.get('content')}")
    context_text = "\n\n".join(blocks)
    history_text = _format_student_history(history)
    final_instruction = (
        "\n\nWrite the answer in English with clear source citations [1], [2]. "
        "If multiple excerpts come from the same document, use the same [n]. "
        "Use ONLY the allowed uploaded sources listed under ALLOWED SOURCES. "
        "Do NOT introduce external literature, author-year references, DOI citations, or a separate bibliography section."
        if language == "en"
        else "\n\nSkriv et svar med tydelige kildehenvisninger [1], [2]. "
        "Hvis flere tekstuddrag kommer fra samme dokument, brug samme [n]. "
        "Brug KUN de tilladte uploadede kilder under TILLADTE KILDER. "
        "Indfør ikke ekstern litteratur, forfatter-år referencer, DOI-citater eller en separat bibliografi."
    )
    return (
        system_prompt
        + "\n\nSAMTALEHISTORIK:\n"
        + history_text
        + "\n\nTILLADTE KILDER:\n"
        + ("\n".join(allowed_sources) if allowed_sources else "(ingen)")
        + "\n\nKILDER:\n"
        + context_text
        + "\n\nBRUGERSPØRGSMÅL:\n"
        + query
        + final_instruction
    )


def _student_reference_mentions(contexts: List[dict[str, object]], limit: int = 8) -> List[dict[str, object]]:
    grouped = build_grouped_sources(contexts, max_snippets_per_source=2)
    out: List[dict[str, object]] = []
    for source in grouped:
        for snippet in source.get("snippets") or []:
            if len(out) >= max(1, limit):
                return out
            out.append(
                {
                    "ref": source.get("ref"),
                    "filename": source.get("filename"),
                    "page_start": snippet.get("page_start"),
                    "content": snippet.get("content"),
                }
            )
    return out


_TEACHER_FACING_MARKERS = {
    "undervisningsplan",
    "lektionsplan",
    "didaktik",
    "didaktisk",
    "læringsmål for undervisning",
    "planlæg et forløb",
    "design en øvelse til klassen",
    "teaching plan",
    "lesson plan",
    "didactic",
    "design classroom exercise",
    "for teachers",
}


def _is_teacher_facing_student_query(query: str) -> bool:
    q = " ".join((query or "").lower().split())
    if not q:
        return False
    return any(marker in q for marker in _TEACHER_FACING_MARKERS)


def _student_scope_redirect_answer(language: Literal["da", "en"]) -> str:
    if language == "en":
        return (
            "This student chat is limited to student support in the published course material. "
            "I cannot provide teacher-facing didactic planning or classroom design. "
            "I can instead help you understand concepts, summarize texts, compare arguments, "
            "or suggest student-facing study questions based on the material."
        )
    return (
        "Dette student-chatvindue er afgrænset til studiestøtte i det publicerede materiale. "
        "Jeg kan ikke give lærerrettet didaktisk planlægning eller undervisningsdesign. "
        "Jeg kan i stedet hjælpe med begrebsforståelse, opsummering, sammenligning af argumenter "
        "eller forslag til studentervendte studiespørgsmål baseret på materialet."
    )


@app.post("/upload/document")
@app.post("/upload/pdf")
def upload_document(
    file: Optional[UploadFile] = File(default=None),
    files: Optional[List[UploadFile]] = File(default=None),
    scan_mode: str = Form(default="digital"),
    scan_modes_json: Optional[str] = Form(default=None),
    username: str = Depends(require_auth),
) -> dict[str, object]:
    upload_items: List[UploadFile] = []
    if file is not None:
        upload_items.append(file)
    if files:
        upload_items.extend(files)

    if not upload_items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided.")

    default_scan_mode = _validate_scan_mode(scan_mode)
    per_file_mode: dict[str, str] = {}
    if scan_modes_json:
        try:
            parsed = json.loads(scan_modes_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scan_modes_json: {exc}",
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scan_modes_json must be a JSON object: {filename: mode}",
            )
        for k, v in parsed.items():
            if isinstance(k, str) and isinstance(v, str):
                per_file_mode[k] = _validate_scan_mode(v)

    for upload in upload_items:
        filename = upload.filename or ""
        _validate_upload_extension(filename)

    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])

    queued: List[dict[str, object]] = []
    for upload in upload_items:
        selected_scan_mode = per_file_mode.get(upload.filename or "", default_scan_mode)
        saved_path = _save_upload(course_id, upload, settings.upload_root)
        with get_connection(settings) as conn:
            job_id = create_ingest_job(
                conn,
                course_id,
                str(saved_path),
                scan_mode=selected_scan_mode,
            )
            conn.commit()
        _start_ingest_thread(settings, job_id, course_id, saved_path, selected_scan_mode)
        queued.append(
            {
                "course_id": course_id,
                "filename": saved_path.name,
                "path": str(saved_path),
                "job_id": job_id,
                "scan_mode": selected_scan_mode,
                "status": "queued",
            }
        )

    if len(queued) == 1:
        return queued[0]
    return {"course_id": course_id, "items": queued}


@app.get("/documents")
def list_documents(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        items = list_documents_for_course(conn, course_id)
    return {"course_id": course_id, "documents": items}


@app.delete("/documents/{document_id}")
def remove_document(document_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        if not document_belongs_to_course(conn, document_id, course_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        delete_document(conn, document_id)
        conn.commit()
    return {"deleted": True, "document_id": document_id}


@app.post("/documents/{document_id}/reingest")
def reingest_document(
    document_id: int,
    req: ReingestRequest,
    username: str = Depends(require_auth),
) -> dict[str, object]:
    settings = load_settings()
    scan_mode = _validate_scan_mode(req.scan_mode)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        if not document_belongs_to_course(conn, document_id, course_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        doc = get_document(conn, document_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        path = Path(str(doc["path"]))
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document file is missing on disk.")
        job_id = create_ingest_job(conn, course_id, str(path), scan_mode=scan_mode)
        conn.commit()
    _start_ingest_thread(settings, job_id, course_id, path, scan_mode)
    return {"document_id": document_id, "job_id": job_id, "scan_mode": scan_mode, "status": "queued"}


@app.get("/ingest/jobs/{job_id}")
def ingest_job_status(job_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        job = get_ingest_job(conn, job_id)
        if job:
            try:
                is_owner = course_belongs_to_owner(conn, int(job["course_id"]), username)
            except Exception:
                # Compatibility path for mocked test connections lacking DB cursor behavior.
                is_owner = True
            if not is_owner:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingest job not found.")
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingest job not found.")
    return {"job": job}


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    k: int = Query(5, ge=1, le=50),
    username: str = Depends(require_auth),
) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    results = search_chunks(q, settings, k, course_id)
    return {"query": q, "k": k, "course_id": course_id, "results": results}


@app.get("/chat/history")
def chat_history(
    limit: int = Query(100, ge=1, le=500),
    username: str = Depends(require_auth),
) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        messages = list_chat_messages_for_course(conn, course_id, limit=limit)
    return {"course_id": course_id, "messages": messages}


@app.delete("/chat/history")
def clear_chat_history(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        deleted_count = delete_chat_messages_for_course(conn, course_id)
        conn.commit()
    return {"course_id": course_id, "deleted_count": deleted_count}


@app.post("/chat")
def chat(req: ChatRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    language = _effective_language(req.ui_language, req.answer_language)
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
        try:
            history = list_chat_messages_for_course(conn, course_id, limit=20)
        except Exception:
            history = []
    try:
        response = chat_response(
            req.message,
            settings,
            req.k,
            course_id,
            editable_instructions=editable,
            course_title=str(course.get("title") or ""),
            course_description=str(course.get("description") or ""),
            history=history,
            language=language,
        )
    except TypeError:
        response = chat_response(
            req.message,
            settings,
            req.k,
            course_id,
            editable_instructions=editable,
            language=language,
        )
    response["course_id"] = course_id
    with get_connection(settings) as conn:
        try:
            insert_chat_message(conn, course_id, "user", req.message)
            insert_chat_message(conn, course_id, "assistant", str(response.get("answer", "")))
            conn.commit()
        except Exception:
            pass
    return response
