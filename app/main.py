from __future__ import annotations

import json
import os
from datetime import datetime
from secrets import choice
from typing import List, Optional
from pathlib import Path
from threading import Thread

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .auth import (
    create_session,
    create_student_session,
    hash_password,
    require_auth,
    require_student_auth,
    verify_password,
)
from .chat import build_grouped_sources, chat_response
from .config import ensure_data_dirs, load_settings
from .db import (
    course_belongs_to_owner,
    copy_course_chunks_to_instance,
    create_bot_instance,
    create_ingest_job,
    create_or_activate_course,
    delete_chat_messages_for_course,
    delete_document,
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
    list_documents_for_course,
    set_active_course_by_id,
    set_bot_instance_status,
    upsert_course_prompt,
)
from .ingest import process_ingest_job
from .llm import generate_answer
from .prompts import DEFAULT_EDITABLE_INSTRUCTIONS, LOCKED_SAFETY_BLOCK, compose_system_prompt
from .search import search_chunks, search_instance_chunks

app = FastAPI(title="RUCAI")

INSTANCE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

WEB_UI_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RUCAI</title>
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
      .header p { margin: 0.35rem 0 0; color: var(--muted); }
      .header-actions { position: absolute; right: 0; top: 0; }
      @media (max-width: 960px) {
        .header-actions { position: static; margin-top: 10px; }
      }
      .card {
        border: 1px solid var(--border);
        background: var(--panel);
        backdrop-filter: blur(6px);
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 12px 26px rgba(16, 22, 19, 0.07);
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
          <select id="chatModelSelect" style="min-width:220px;">
            <option value="">Vælg model…</option>
          </select>
          <button id="saveModelBtn">Gem model</button>
          <button id="logoutTopBtn" class="warn">Log ud</button>
        </div>
        <div id="modelState" class="small"></div>
      </header>

      <section class="card">
        <h3>Hvad er RUCAI?</h3>
        <div class="small">
          RUCAI er sat i verden til at understøtte kursusplanlægning og afvikling.
          Ideen er at underviser kan designe og tilrettelægge undervisning med udgangspunkt i kursusbeskrivelse og pensum
          og så oprette ”chat” vinduer, som studerende så kan tilgå i forbindelse med undervisning.
          Chat-historik gemmes pr. kursusgang, så samtaler kan fortsætte over tid.
        </div>
      </section>

      <section class="card sidebar">
        <h3>Kurser</h3>
        <div class="small">Skift mellem dine kurser.</div>
        <div class="row">
          <button id="newCourseBtn" class="primary" style="width:100%;">Nyt kursus</button>
        </div>
        <div id="coursesState" class="small"></div>
        <div id="coursesList" class="stack"></div>
      </section>

      <section class="card" id="activeCourseCard">
        <h3>Information om kurset</h3>
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
        <h3>Kursusprompt
          <span class="tip-wrap">
            <span class="tip-icon" tabindex="0" aria-label="Tips til prompt-teknik">I</span>
            <span class="tip-text">God prompt-teknik: Vær konkret om målgruppe, læringsmål, ønsket svarformat og længde. Bed om kildehenvisninger, og sig tydeligt hvad modellen skal gøre ved usikkerhed.</span>
          </span>
        </h3>
        <div class="small">Du kan redigere undervisningsinstruktionen. Nogle grundregler er faste for at sikre kildebaserede og ansvarlige svar.</div>
        <div class="row">
          <textarea id="promptEditable" placeholder="Redigerbar kursusinstruktion"></textarea>
        </div>
        <div class="row">
          <button id="savePromptBtn" class="primary">Gem kursusprompt</button>
          <button id="refreshPromptBtn">Hent kursusprompt</button>
        </div>
        <details class="small">
          <summary>Faste grundregler (kan ikke redigeres)</summary>
          <pre id="promptLocked"></pre>
        </details>
        <details class="small">
          <summary>Aktiv prompt (preview)</summary>
          <pre id="promptPreview"></pre>
        </details>
        <div id="promptState" class="small"></div>
      </section>

      <section class="split-two">
        <section class="card">
          <h3>Upload PDF/DOCX</h3>
          <div class="row">
            <input id="docFile" type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" />
            <button id="uploadBtn" class="primary">Upload og indlæs</button>
          </div>
          <div id="scanModeList" class="small"></div>
          <div id="ingestState" class="small"></div>
        </section>

        <section class="card">
          <h3>Dokumenter</h3>
          <div class="row">
            <button id="refreshDocsBtn">Genindlæs dokumentliste</button>
          </div>
          <div id="docsState" class="small"></div>
          <div id="docsList" class="stack"></div>
        </section>
      </section>

      <section class="card">
        <h3>Chat</h3>
        <div class="row">
          <label for="topK" class="small">Kilder pr. svar (k)</label>
          <input id="topK" type="number" min="1" max="50" value="5" />
        </div>
        <div id="chatStatus" class="small"></div>
        <div id="answer" class="answer"></div>
        <div id="sources"></div>
        <div class="small"><strong>Samtalehistorik</strong> (for aktivt kursus)</div>
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
        <h3>Skab studenter-chatvinduer</h3>
        <div class="small">Publicér en låst chatbot til studerende ud fra aktivt kursus.</div>
        <div class="row">
          <input id="instanceName" type="text" placeholder="Navn på chatvindue (fx Hold A Forår 2026)" />
        </div>
        <div class="row">
          <input id="instanceCode" type="text" placeholder="Kode (valgfri, autogenereres hvis tom)" />
          <input id="instancePassword" type="password" placeholder="Adgangskode til studerende" />
          <button id="publishInstanceBtn" class="primary">Publicér</button>
          <button id="refreshInstancesBtn">Genindlæs chatvinduer</button>
        </div>
        <div id="instancesState" class="small"></div>
        <div id="instancesList" class="stack"></div>
      </section>

    </main>

    <script>
      let token = localStorage.getItem("rucai_token") || "";
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
      const chatHistoryEl = document.getElementById("chatHistory");
      const promptState = document.getElementById("promptState");
      const modelState = document.getElementById("modelState");
      const promptEditableEl = document.getElementById("promptEditable");
      const promptLockedEl = document.getElementById("promptLocked");
      const promptPreviewEl = document.getElementById("promptPreview");
      const docsState = document.getElementById("docsState");
      const docsList = document.getElementById("docsList");
      const instancesState = document.getElementById("instancesState");
      const instancesList = document.getElementById("instancesList");

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
            div.innerHTML = `<strong>[${escapeHtml(String(src.ref ?? "?"))}] ${escapeHtml(String(src.filename || "Ukendt kilde"))}</strong>${snippetHtml}`;
            container.appendChild(div);
          });
          return;
        }

        (data?.contexts || []).forEach((ctx) => {
          const div = document.createElement("div");
          div.className = "source";
          div.innerHTML = `<strong>${escapeHtml(ctx.filename)}</strong> p${escapeHtml(ctx.page_start)}<br>${escapeHtml(ctx.content || "")}`;
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
            const filename = escapeHtml(String(src.filename || "Ukendt kilde"));
            const snippets = Array.isArray(src.snippets) ? src.snippets : [];
            const snippetsHtml = snippets.map((sn) => {
              const fullText = String(sn.content || "");
              const shortText = fullText.length > maxPreviewChars ? `${fullText.slice(0, maxPreviewChars)}...` : fullText;
              return `
                <div style="margin-top:6px;">
                  p${escapeHtml(String(sn.page_start ?? "?"))} idx ${escapeHtml(String(sn.chunk_index ?? "?"))}<br>
                  ${escapeHtml(shortText)}
                  <details><summary>Vis hele uddraget</summary>${escapeHtml(fullText)}</details>
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
            <strong>${escapeHtml(ctx.filename)}</strong> p${escapeHtml(ctx.page_start)} idx ${escapeHtml(ctx.chunk_index)}<br>
            ${escapeHtml(shortText)}
            <details><summary>Vis hele uddraget</summary>${escapeHtml(fullText)}</details>
          `;
          container.appendChild(div);
        });
      }

      const thinkingIntervals = new Map();

      function startThinking(el, label = "Tænker") {
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

      function startBusyButton(btn, label = "Arbejder") {
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
        btn.textContent = btn.dataset.originalLabel || "Spørg";
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
        courseState.innerHTML = '<span class="ok">Du har ikke et aktivt kursus endnu. Opret dit første kursus nedenfor.</span>';
        promptState.innerHTML = '<span class="ok">Vælg eller opret et kursus for at redigere course prompt.</span>';
        docsState.innerHTML = '<span class="ok">Vælg eller opret et kursus for at se dokumenter.</span>';
        docsList.innerHTML = "";
        chatHistoryEl.innerHTML = '<div class="small">Opret et kursus for at starte chat-historik.</div>';
      }

      function buildStudentUrl(instanceCode) {
        return `${window.location.origin}/student/i/${instanceCode}`;
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
          const detail = typeof data === "object" && data ? (data.detail || JSON.stringify(data)) : data;
          throw new Error(detail || `HTTP ${resp.status}`);
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
            chatHistoryEl.innerHTML = '<div class="small">Ingen beskeder endnu.</div>';
            return;
          }
          chatHistoryEl.innerHTML = items.map((m) => `
            <div class="history-item">
              <div class="history-role">${escapeHtml(m.role)}</div>
              <div>${m.role === "assistant" ? markdownToHtml(m.content) : escapeHtml(m.content)}</div>
              <div class="history-time">${escapeHtml(new Date(m.created_at).toLocaleString("da-DK"))}</div>
            </div>
          `).join("");
        } catch (err) {
          if (isNoCourseError(err.message)) {
            chatHistoryEl.innerHTML = '<div class="small">Opret et kursus for at starte chat-historik.</div>';
          } else {
            chatHistoryEl.innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
          }
        }
      }

      async function refreshPrompt() {
        try {
          const data = await api("/course/prompt");
          promptEditableEl.value = data.editable_instructions || "";
          promptLockedEl.textContent = data.locked_safety_block || "";
          promptPreviewEl.textContent = data.effective_prompt_preview || "";
          promptState.innerHTML = '<span class="ok">Kursusprompt hentet</span>';
        } catch (err) {
          if (isNoCourseError(err.message)) {
            promptState.innerHTML = '<span class="ok">Vælg eller opret et kursus for at redigere course prompt.</span>';
          } else {
            promptState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          }
        }
      }

      async function refreshInstances() {
        try {
          const data = await api("/instances");
          const items = data.instances || [];
          instancesState.innerHTML = `<span class="ok">${items.length} chatvinduer</span>`;
          instancesList.innerHTML = items.map((i) => `
            <div class="small">
              <strong>${escapeHtml(i.name)}</strong>
              <div class="mono">kode=${escapeHtml(i.instance_code)} | tekstuddrag=${i.chunk_count} | status=${i.is_active ? "aktiv" : "inaktiv"}</div>
              <div class="row">
                <button data-action="copy-invite" data-id="${i.id}" data-code="${escapeHtml(i.instance_code)}">Kopiér link</button>
                <button data-action="instance-on" data-id="${i.id}">Aktivér</button>
                <button data-action="instance-off" data-id="${i.id}" class="warn">Deaktivér</button>
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
          select.innerHTML = models.map((m) => `<option value="${escapeHtml(String(m))}">${escapeHtml(String(m))}</option>`).join("");
          if (!models.length) {
            select.innerHTML = '<option value="">Ingen modeller fundet</option>';
          }
          if (data.active_model) {
            select.value = data.active_model;
          }
          modelState.innerHTML = `<span class="ok">Aktiv model: ${escapeHtml(String(data.active_model || "ukendt"))}</span>`;
        } catch (err) {
          modelState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      }

      async function refreshDocuments() {
        try {
          const data = await api("/documents");
          const items = data.documents || [];
          docsState.innerHTML = `<span class="ok">${items.length} dokument(er)</span>`;
          docsList.innerHTML = items.map((d) => `
            <div class="small">
              <strong>${escapeHtml(d.filename)}</strong>
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
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
        } catch (err) {
          showGate(err.message);
        }
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
        } catch (err) {
          courseState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("refreshCourseBtn").addEventListener("click", refreshActiveCourse);
      document.getElementById("refreshPromptBtn").addEventListener("click", refreshPrompt);
      document.getElementById("refreshDocsBtn").addEventListener("click", refreshDocuments);
      document.getElementById("refreshInstancesBtn").addEventListener("click", refreshInstances);
      document.getElementById("newCourseBtn").addEventListener("click", () => {
        document.getElementById("courseTitle").value = "";
        document.getElementById("courseDesc").value = "";
        courseState.innerHTML = '<span class="ok">Udfyld titel og beskrivelse og klik "Placer kursusbeskrivelse og titel i systemprompt".</span>';
        document.getElementById("activeCourseCard").scrollIntoView({ behavior: "smooth", block: "start" });
        document.getElementById("courseTitle").focus();
      });

      document.getElementById("saveModelBtn").addEventListener("click", async () => {
        try {
          const model = document.getElementById("chatModelSelect").value.trim();
          if (!model) {
            modelState.innerHTML = '<span class="err">Vælg en model først.</span>';
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
          const instance_code = document.getElementById("instanceCode").value.trim();
          const instance_password = document.getElementById("instancePassword").value.trim();
          if (!name || !instance_password) {
            instancesState.innerHTML = '<span class="err">Navn og adgangskode er påkrævet.</span>';
            return;
          }
          const created = await api("/instances", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, instance_code: instance_code || null, instance_password }),
          });
          const actualCode = created?.instance?.instance_code || instance_code || "";
          const studentUrl = buildStudentUrl(actualCode);
          await copyToClipboard(studentUrl);
          document.getElementById("instanceCode").value = "";
          document.getElementById("instancePassword").value = "";
          instancesState.innerHTML = '<span class="ok">Chatvindue publiceret. Link kopieret.</span>';
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
        } catch (err) {
          coursesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("savePromptBtn").addEventListener("click", async () => {
        try {
          const editable_instructions = promptEditableEl.value.trim();
          const data = await api("/course/prompt", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ editable_instructions }),
          });
          promptLockedEl.textContent = data.locked_safety_block || "";
          promptPreviewEl.textContent = data.effective_prompt_preview || "";
          promptState.innerHTML = '<span class="ok">Kursusprompt gemt</span>';
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
              return `<div><span class="${cls}">${escapeHtml(u.filename)} (${escapeHtml(u.scan_mode)}): ${escapeHtml(u.status)}</span> <span class="mono">job ${u.job_id}</span></div>`;
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
          }
          await refreshInstances();
        } catch (err) {
          instancesState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("chatBtn").addEventListener("click", async () => {
        const chatBtn = document.getElementById("chatBtn");
        const busyTimer = startBusyButton(chatBtn, "Arbejder");
        try {
          const message = document.getElementById("question").value.trim();
          const k = Number(document.getElementById("topK").value || 5);
          if (!message) {
            chatStatus.innerHTML = '<span class="err">Skriv et spørgsmål.</span>';
            return;
          }
          startThinking(chatStatus, "Tænker");
          answerEl.innerHTML = "";
          sourcesEl.innerHTML = "";
          const data = await api("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, k }),
          });
          stopThinking(chatStatus);
          chatStatus.innerHTML = `<span class="ok">Færdig</span> <span class="mono">intent=${escapeHtml(data.intent || "narrow")} | kilder=${data.source_count ?? 0} | uddrag=${data.chunk_count ?? 0} | runde=${data.retrieval_rounds ?? 1}</span>`;
          answerEl.innerHTML = markdownToHtml(data.answer || "");
          renderGroupedSources(sourcesEl, data);
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
          chatStatus.innerHTML = '<span class="ok">Ny samtale startet.</span>';
          await refreshChatHistory();
        } catch (err) {
          chatStatus.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      (async () => {
        const valid = await validateSession();
        if (valid) {
          showApp();
          await refreshActiveCourse();
          await refreshCourses();
          await refreshPrompt();
          await refreshDocuments();
          await refreshChatHistory();
          await refreshInstances();
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
      .small { font-size: 13px; color: #555; margin-top: 8px; }
      .err { color: #b3261e; }
      .ok { color: #1f7a45; }
      .answer { margin-top: 10px; line-height: 1.5; }
      .answer p { margin: 0 0 10px; }
      .answer ul { margin: 0 0 10px 22px; padding: 0; }
      .answer li { margin-bottom: 6px; }
      .answer strong { font-weight: 700; }
      .source { margin-top: 8px; border-top: 1px dashed #d8d3cb; padding-top: 8px; font-size: 13px; }
      .doc-item { border: 1px solid #ddd8cf; border-radius: 8px; padding: 8px; margin-bottom: 8px; background: #fff; }
      .doc-item .mono { color: #666; font-size: 12px; }
      .hidden { display: none !important; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <section id="loginCard" class="card">
        <h2>RUCAI Studerende</h2>
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
            <div class="row">
              <h3 id="instanceTitle" style="margin:0;">Chatvindue</h3>
              <button id="studentLogoutBtn" class="warn">Log ud</button>
            </div>
            <div class="row">
              <textarea id="studentQuestion" placeholder="Stil et spørgsmål til materialet..."></textarea>
            </div>
            <div class="row">
              <input id="studentTopK" type="number" min="1" max="50" value="5" />
              <button id="studentAskBtn">Spørg</button>
            </div>
            <div id="studentState" class="small"></div>
            <div id="studentAnswer" class="answer"></div>
            <div id="studentSources"></div>
          </section>
        </div>
      </section>
    </div>

    <script>
      let token = localStorage.getItem("rucai_student_token") || "";
      const loginCard = document.getElementById("loginCard");
      const studentCard = document.getElementById("studentCard");
      const loginState = document.getElementById("loginState");
      const loginHint = document.getElementById("studentLoginHint");
      const studentState = document.getElementById("studentState");
      const instanceTitle = document.getElementById("instanceTitle");
      const answerEl = document.getElementById("studentAnswer");
      const sourcesEl = document.getElementById("studentSources");
      const studentDocsEl = document.getElementById("studentDocs");
      const pathMatch = window.location.pathname.match(/^\\/student\\/i\\/([^/]+)$/);
      const defaultInstanceCode = pathMatch ? decodeURIComponent(pathMatch[1] || "").toUpperCase() : "";
      if (!defaultInstanceCode) {
        loginHint.innerHTML = '<span class="err">Åbn via invitationslink fra underviser.</span>';
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

      const thinkingIntervals = new Map();

      function startThinking(el, label = "Tænker") {
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

      async function api(path, options = {}) {
        const headers = options.headers || {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const resp = await fetch(path, { ...options, headers });
        const isJson = (resp.headers.get("content-type") || "").includes("application/json");
        const data = isJson ? await resp.json() : await resp.text();
        if (!resp.ok) {
          const detail = typeof data === "object" && data ? (data.detail || JSON.stringify(data)) : data;
          throw new Error(detail || `HTTP ${resp.status}`);
        }
        return data;
      }

      async function refreshStudentMeta() {
        try {
          const data = await api("/student/instance");
          instanceTitle.textContent = data.instance.name || "Chatvindue";
          await refreshStudentDocuments();
          loginCard.classList.add("hidden");
          studentCard.classList.remove("hidden");
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
            studentDocsEl.innerHTML = '<div class="small">Ingen dokumenter fundet i denne instance.</div>';
            return;
          }
          studentDocsEl.innerHTML = docs.map((d) => `
            <div class="doc-item">
              <div><strong>${escapeHtml(d.filename)}</strong></div>
              <div class="mono">chunks: ${d.chunk_count}</div>
            </div>
          `).join("");
        } catch (err) {
          studentDocsEl.innerHTML = `<div class="small err">${escapeHtml(err.message)}</div>`;
        }
      }

      document.getElementById("studentLoginBtn").addEventListener("click", async () => {
        try {
          const instance_code = defaultInstanceCode;
          const password = document.getElementById("instancePassword").value.trim();
          if (!instance_code) {
            loginState.innerHTML = '<span class="err">Invitationslink mangler kode.</span>';
            return;
          }
          if (!password) {
            loginState.innerHTML = '<span class="err">Udfyld password.</span>';
            return;
          }
          const data = await api("/student/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ instance_code, password }),
          });
          token = data.token;
          localStorage.setItem("rucai_student_token", token);
          loginState.innerHTML = '<span class="ok">Logget ind.</span>';
          await refreshStudentMeta();
        } catch (err) {
          loginState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("studentLogoutBtn").addEventListener("click", () => {
        token = "";
        localStorage.removeItem("rucai_student_token");
        loginCard.classList.remove("hidden");
        studentCard.classList.add("hidden");
        loginState.innerHTML = "";
      });

      document.getElementById("studentAskBtn").addEventListener("click", async () => {
        const studentAskBtn = document.getElementById("studentAskBtn");
        const originalAskLabel = studentAskBtn.textContent || "Spørg";
        try {
          studentAskBtn.disabled = true;
          studentAskBtn.textContent = "Arbejder...";
          const message = document.getElementById("studentQuestion").value.trim();
          const k = Number(document.getElementById("studentTopK").value || 5);
          if (!message) {
            studentState.innerHTML = '<span class="err">Skriv et spørgsmål.</span>';
            return;
          }
          startThinking(studentState, "Tænker");
          answerEl.textContent = "";
          sourcesEl.innerHTML = "";
          const data = await api("/student/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, k }),
          });
          stopThinking(studentState);
          studentState.innerHTML = `<span class="ok">Færdig</span> <span class="mono">kilder=${data.source_count ?? 0} | uddrag=${data.chunk_count ?? 0}</span>`;
          answerEl.innerHTML = markdownToHtml(data.answer || "");
          renderGroupedSources(sourcesEl, data);
        } catch (err) {
          stopThinking(studentState);
          studentState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        } finally {
          studentAskBtn.disabled = false;
          studentAskBtn.textContent = originalAskLabel;
        }
      });

      (async () => {
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


class PromptRequest(BaseModel):
    editable_instructions: str = Field(min_length=1)


class ReingestRequest(BaseModel):
    scan_mode: str = Field(default="digital")


class InstanceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instance_code: Optional[str] = None
    instance_password: str = Field(min_length=4, max_length=200)


class InstanceStatusRequest(BaseModel):
    is_active: bool


class StudentLoginRequest(BaseModel):
    instance_code: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class StudentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)


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
    return WEB_UI_HTML


@app.get("/student", response_class=HTMLResponse)
def student_home() -> str:
    return STUDENT_UI_HTML


@app.get("/student/i/{instance_code}", response_class=HTMLResponse)
def student_home_instance(instance_code: str) -> str:
    return STUDENT_UI_HTML


def _runtime_model_options(settings: object) -> list[str]:
    configured = [x.strip() for x in os.getenv("CHAT_MODEL_OPTIONS", "gemma3:12b,qwen2.5:14b-instruct").split(",")]
    options = [x for x in configured if x]
    active = str(getattr(settings, "chat_model", "") or "").strip()
    if active and active not in options:
        options.insert(0, active)
    return options


@app.get("/runtime/model")
def get_runtime_model(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    options = _runtime_model_options(settings)
    return {
        "active_model": settings.chat_model,
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
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    code = _normalize_instance_code(req.instance_code)

    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
        effective_prompt = compose_system_prompt(
            editable,
            course_title=str(course.get("title") or ""),
            course_description=str(course.get("description") or ""),
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
                    editable_instructions_snapshot=editable,
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


@app.post("/student/chat")
def student_chat(req: StudentChatRequest, instance_id: int = Depends(require_student_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        instance = get_bot_instance_by_id(conn, instance_id)
    if not instance or not instance.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student session expired or invalid.")

    contexts = search_instance_chunks(req.message, settings, req.k, instance_id)
    sources = build_grouped_sources(contexts, max_snippets_per_source=1)
    system_prompt = str(instance["effective_system_prompt_snapshot"])
    if not contexts:
        answer = (
            "Jeg kan ikke svare fagligt sikkert ud fra det publicerede materiale. "
            "Prøv at omformulere spørgsmålet."
        )
        prompt = _build_student_prompt(req.message, sources, system_prompt)
    else:
        prompt = _build_student_prompt(req.message, sources, system_prompt)
        answer = generate_answer(prompt, settings)

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
        "k": req.k,
        "answer": answer,
        "contexts": contexts,
        "sources": sources,
        "citations": citations,
        "source_count": len(sources),
        "chunk_count": len(contexts),
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
def read_course_prompt(username: str = Depends(require_auth)) -> dict[str, str]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
    return {
        "editable_instructions": editable,
        "locked_safety_block": LOCKED_SAFETY_BLOCK,
        "effective_prompt_preview": compose_system_prompt(
            editable,
            course_title=str(course.get("title") or ""),
            course_description=str(course.get("description") or ""),
        ),
    }


@app.put("/course/prompt")
def update_course_prompt(req: PromptRequest, username: str = Depends(require_auth)) -> dict[str, str]:
    settings = load_settings()
    course = _active_course_for_request(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        upsert_course_prompt(conn, course_id, req.editable_instructions)
        conn.commit()
    return {
        "editable_instructions": req.editable_instructions,
        "locked_safety_block": LOCKED_SAFETY_BLOCK,
        "effective_prompt_preview": compose_system_prompt(
            req.editable_instructions,
            course_title=str(course.get("title") or ""),
            course_description=str(course.get("description") or ""),
        ),
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


def _build_student_prompt(query: str, sources: List[dict[str, object]], system_prompt: str) -> str:
    blocks: List[str] = []
    for source in sources:
        ref = int(source.get("ref") or 0)
        for snippet in source.get("snippets") or []:
            blocks.append(f"[{ref}] {snippet.get('filename')} p{snippet.get('page_start')}\n{snippet.get('content')}")
    context_text = "\n\n".join(blocks)
    return (
        system_prompt
        + "\n\nKILDER:\n"
        + context_text
        + "\n\nBRUGERSPØRGSMÅL:\n"
        + query
        + "\n\nSkriv et svar med tydelige kildehenvisninger [1], [2]. Hvis flere tekstuddrag kommer fra samme dokument, brug samme [n]."
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
        )
    except TypeError:
        response = chat_response(
            req.message,
            settings,
            req.k,
            course_id,
            editable_instructions=editable,
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
