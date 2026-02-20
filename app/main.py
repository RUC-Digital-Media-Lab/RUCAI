from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from threading import Thread

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .auth import create_session, require_auth
from .chat import chat_response
from .config import ensure_data_dirs, load_settings
from .db import (
    course_belongs_to_owner,
    create_ingest_job,
    create_or_activate_course,
    delete_chat_messages_for_course,
    delete_document,
    document_belongs_to_course,
    ensure_schema,
    get_active_course,
    list_courses,
    get_course_prompt,
    get_document,
    get_connection,
    get_ingest_job,
    insert_chat_message,
    list_chat_messages_for_course,
    list_documents_for_course,
    set_active_course_by_id,
    upsert_course_prompt,
)
from .ingest import process_ingest_job
from .prompts import DEFAULT_EDITABLE_INSTRUCTIONS, LOCKED_SAFETY_BLOCK, compose_system_prompt
from .search import search_chunks

app = FastAPI(title="RUCAI")

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
      @media (max-width: 960px) {
        .layout { grid-template-columns: 1fr; }
        .layout > .sidebar, .layout > .card, .layout > .header { grid-column: 1; position: static; }
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
    </style>
  </head>
  <body>
    <div class="bg-shape shape-a"></div>
    <div class="bg-shape shape-b"></div>

    <div id="loginGate" class="gate-wrap">
      <section class="gate-card">
        <h2 class="gate-title">RUCAI Login</h2>
        <p class="gate-sub">Log ind for at åbne platformen.</p>
        <div class="row">
          <input id="username" type="text" placeholder="username" />
          <input id="password" type="password" placeholder="password" />
          <button id="loginBtn" class="primary">Log ind</button>
        </div>
        <div id="authState" class="small"></div>
      </section>
    </div>

    <main id="appShell" class="layout hidden">
      <header class="header">
        <h1>RUCAI</h1>
        <p>Underviser-copilot til kursusforankrede svar, upload og sparring.</p>
        <div class="header-actions">
          <button id="logoutTopBtn" class="warn">Log ud</button>
        </div>
      </header>

      <section class="card">
        <h3>Documentation</h3>
        <div class="small">
          RUCAI hjælper undervisere med at arbejde direkte i kursusmaterialet.
          1) Vælg eller opret et kursus. 2) Upload PDF/DOCX og vælg scanningstype.
          3) Stil spørgsmål i chatten og brug kildehenvisningerne til planlægning, begrebsafklaring og øvelsesdesign.
          Chat-historik gemmes pr. kursus, så samtaler kan fortsætte over tid.
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
        <h3>Aktivt Kursus</h3>
        <div class="row">
          <input id="courseTitle" type="text" placeholder="Course title" />
        </div>
        <div class="row">
          <textarea id="courseDesc" placeholder="Course description"></textarea>
        </div>
        <div class="row">
          <button id="setCourseBtn" class="primary">Set Active Course</button>
          <button id="refreshCourseBtn">Refresh</button>
        </div>
        <div id="courseState" class="small"></div>
      </section>

      <section class="card">
        <h3>Course Prompt</h3>
        <div class="small">Du kan redigere undervisningsinstruktionen. Sikkerhedsblokken er låst.</div>
        <div class="row">
          <textarea id="promptEditable" placeholder="Editable course instructions"></textarea>
        </div>
        <div class="row">
          <button id="savePromptBtn" class="primary">Save Prompt</button>
          <button id="refreshPromptBtn">Refresh Prompt</button>
        </div>
        <details class="small">
          <summary>Låst sikkerhedsblok</summary>
          <pre id="promptLocked"></pre>
        </details>
        <details class="small">
          <summary>Effective prompt preview</summary>
          <pre id="promptPreview"></pre>
        </details>
        <div id="promptState" class="small"></div>
      </section>

      <section class="card">
        <h3>Documents</h3>
        <div class="row">
          <button id="refreshDocsBtn">Refresh Documents</button>
        </div>
        <div id="docsState" class="small"></div>
        <div id="docsList" class="stack"></div>
      </section>

      <section class="card">
        <h3>Upload PDF/DOCX</h3>
        <div class="row">
          <input id="docFile" type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" />
          <button id="uploadBtn" class="primary">Upload + Ingest</button>
        </div>
        <div id="scanModeList" class="small"></div>
        <div id="ingestState" class="small"></div>
      </section>

      <section class="card">
        <h3>Chat With Curriculum</h3>
        <div class="row">
          <textarea id="question" placeholder="Ask a curriculum question..."></textarea>
        </div>
        <div class="row">
          <label for="topK" class="small">Kilder pr. svar (k)</label>
          <input id="topK" type="number" min="1" max="50" value="5" />
          <button id="chatBtn" class="primary">Ask</button>
          <button id="newChatBtn" class="warn">Ny samtale</button>
        </div>
        <div id="chatStatus" class="small"></div>
        <div id="answer" class="answer"></div>
        <div id="sources"></div>
        <div class="small"><strong>Samtalehistorik</strong> (for aktivt kursus)</div>
        <div id="chatHistory" class="history"></div>
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
      const promptEditableEl = document.getElementById("promptEditable");
      const promptLockedEl = document.getElementById("promptLocked");
      const promptPreviewEl = document.getElementById("promptPreview");
      const docsState = document.getElementById("docsState");
      const docsList = document.getElementById("docsList");

      function escapeHtml(text) {
        const d = document.createElement("div");
        d.innerText = String(text ?? "");
        return d.innerHTML;
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
          courseState.innerHTML = `<span class="ok">Active: ${escapeHtml(c.title)}</span> <span class="mono">id=${c.id}</span>`;
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
              <div>${escapeHtml(m.content)}</div>
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
          promptState.innerHTML = '<span class="ok">Prompt loaded</span>';
        } catch (err) {
          if (isNoCourseError(err.message)) {
            promptState.innerHTML = '<span class="ok">Vælg eller opret et kursus for at redigere course prompt.</span>';
          } else {
            promptState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
          }
        }
      }

      async function refreshDocuments() {
        try {
          const data = await api("/documents");
          const items = data.documents || [];
          docsState.innerHTML = `<span class="ok">${items.length} document(s)</span>`;
          docsList.innerHTML = items.map((d) => `
            <div class="small">
              <strong>${escapeHtml(d.filename)}</strong>
              <div class="mono">id=${d.id} | mode=${escapeHtml(d.scan_mode || "digital")} | lang=${escapeHtml(d.language || "unknown")} | chunks=${d.chunk_count}</div>
              <div class="row">
                <button data-action="reingest-digital" data-id="${d.id}">Reingest Digital</button>
                <button data-action="reingest-scanned" data-id="${d.id}">Reingest Håndscannet</button>
                <button data-action="delete-doc" data-id="${d.id}" class="warn">Delete</button>
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
        } catch (err) {
          courseState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("refreshCourseBtn").addEventListener("click", refreshActiveCourse);
      document.getElementById("refreshPromptBtn").addEventListener("click", refreshPrompt);
      document.getElementById("refreshDocsBtn").addEventListener("click", refreshDocuments);
      document.getElementById("newCourseBtn").addEventListener("click", () => {
        document.getElementById("courseTitle").value = "";
        document.getElementById("courseDesc").value = "";
        courseState.innerHTML = '<span class="ok">Udfyld titel og beskrivelse og klik "Set Active Course".</span>';
        document.getElementById("activeCourseCard").scrollIntoView({ behavior: "smooth", block: "start" });
        document.getElementById("courseTitle").focus();
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
          await refreshDocuments();
          await refreshChatHistory();
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
          promptState.innerHTML = '<span class="ok">Prompt saved</span>';
        } catch (err) {
          promptState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("uploadBtn").addEventListener("click", async () => {
        try {
          const fileInput = document.getElementById("docFile");
          if (!fileInput.files || !fileInput.files[0]) {
            ingestState.innerHTML = '<span class="err">Choose file(s) first.</span>';
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
          ingestState.innerHTML = `<span class="ok">${uploads.length} file(s) uploaded. Tracking jobs...</span>`;

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
        }
      });

      docsList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.getAttribute("data-action");
        const docId = target.getAttribute("data-id");
        if (!action || !docId) return;
        try {
          if (action === "delete-doc") {
            await api(`/documents/${docId}`, { method: "DELETE" });
          } else if (action === "reingest-digital") {
            await api(`/documents/${docId}/reingest`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scan_mode: "digital" }),
            });
          } else if (action === "reingest-scanned") {
            await api(`/documents/${docId}/reingest`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scan_mode: "hand_scanned" }),
            });
          }
          await refreshDocuments();
        } catch (err) {
          docsState.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("chatBtn").addEventListener("click", async () => {
        try {
          const message = document.getElementById("question").value.trim();
          const k = Number(document.getElementById("topK").value || 5);
          if (!message) {
            chatStatus.innerHTML = '<span class="err">Enter a question.</span>';
            return;
          }
          chatStatus.textContent = "Thinking...";
          answerEl.textContent = "";
          sourcesEl.innerHTML = "";
          const data = await api("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, k }),
          });
          chatStatus.innerHTML = `<span class="ok">Done</span> <span class="mono">kilder=${data.source_count ?? 0}</span>`;
          answerEl.textContent = data.answer || "";
          const maxPreviewChars = 240;
          (data.contexts || []).forEach((ctx) => {
            const div = document.createElement("div");
            div.className = "source small";
            const fullText = String(ctx.content || "");
            const shortText = fullText.length > maxPreviewChars ? `${fullText.slice(0, maxPreviewChars)}...` : fullText;
            div.innerHTML = `
              <strong>${escapeHtml(ctx.filename)}</strong> p${escapeHtml(ctx.page_start)} idx ${escapeHtml(ctx.chunk_index)}<br>
              ${escapeHtml(shortText)}
              <details><summary>Vis hele uddraget</summary>${escapeHtml(fullText)}</details>
            `;
            sourcesEl.appendChild(div);
          });
          await refreshChatHistory();
        } catch (err) {
          chatStatus.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
        }
      });

      document.getElementById("newChatBtn").addEventListener("click", async () => {
        try {
          await api("/chat/history", { method: "DELETE" });
          answerEl.textContent = "";
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
        } else {
          showGate("");
        }
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


@app.post("/auth/login")
def login(req: LoginRequest) -> dict[str, str]:
    settings = load_settings()
    token = create_session(req.username, req.password, settings)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    return {"token": token, "token_type": "bearer"}


@app.post("/course")
def set_active_course(req: CourseRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        course = create_or_activate_course(conn, username, req.title, req.description)
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
        course = get_active_course(conn, username)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active course.")
    return {"course": course}


@app.get("/course/prompt")
def read_course_prompt(username: str = Depends(require_auth)) -> dict[str, str]:
    settings = load_settings()
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
    return {
        "editable_instructions": editable,
        "locked_safety_block": LOCKED_SAFETY_BLOCK,
        "effective_prompt_preview": compose_system_prompt(editable),
    }


@app.put("/course/prompt")
def update_course_prompt(req: PromptRequest, username: str = Depends(require_auth)) -> dict[str, str]:
    settings = load_settings()
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        upsert_course_prompt(conn, course_id, req.editable_instructions)
        conn.commit()
    return {
        "editable_instructions": req.editable_instructions,
        "locked_safety_block": LOCKED_SAFETY_BLOCK,
        "effective_prompt_preview": compose_system_prompt(req.editable_instructions),
    }


def _active_course_or_404(username: str) -> dict[str, object]:
    settings = load_settings()
    with get_connection(settings) as conn:
        course = get_active_course(conn, username)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active course. Create one with POST /course before uploading or querying.",
        )
    return course


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
    course = _active_course_or_404(username)
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
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        items = list_documents_for_course(conn, course_id)
    return {"course_id": course_id, "documents": items}


@app.delete("/documents/{document_id}")
def remove_document(document_id: int, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_or_404(username)
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
    course = _active_course_or_404(username)
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
        if job and not course_belongs_to_owner(conn, int(job["course_id"]), username):
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
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    results = search_chunks(q, settings, k, course_id)
    return {"query": q, "k": k, "course_id": course_id, "results": results}


@app.get("/chat/history")
def chat_history(
    limit: int = Query(100, ge=1, le=500),
    username: str = Depends(require_auth),
) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        messages = list_chat_messages_for_course(conn, course_id, limit=limit)
    return {"course_id": course_id, "messages": messages}


@app.delete("/chat/history")
def clear_chat_history(username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        deleted_count = delete_chat_messages_for_course(conn, course_id)
        conn.commit()
    return {"course_id": course_id, "deleted_count": deleted_count}


@app.post("/chat")
def chat(req: ChatRequest, username: str = Depends(require_auth)) -> dict[str, object]:
    settings = load_settings()
    course = _active_course_or_404(username)
    course_id = int(course["id"])
    with get_connection(settings) as conn:
        editable = get_course_prompt(conn, course_id) or DEFAULT_EDITABLE_INSTRUCTIONS
        history = list_chat_messages_for_course(conn, course_id, limit=20)
    response = chat_response(
        req.message,
        settings,
        req.k,
        course_id,
        editable_instructions=editable,
        history=history,
    )
    response["course_id"] = course_id
    with get_connection(settings) as conn:
        insert_chat_message(conn, course_id, "user", req.message)
        insert_chat_message(conn, course_id, "assistant", str(response.get("answer", "")))
        conn.commit()
    return response
