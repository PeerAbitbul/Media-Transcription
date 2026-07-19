import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, post, formatDur } from "./api.js";
import { T, LANGS } from "./i18n.js";
import { PreviewModal, LogsModal, TelegramModal } from "./Modals.jsx";
import { Film, Clock, Users, Eye, Trash, List, Settings, DownloadCloud } from "./icons.jsx";

const MODEL_STAGES = new Set(["downloading_model", "loading_model"]);

export default function App() {
  const [lang, setLang] = useState(() => (T[localStorage.getItem("lang")] ? localStorage.getItem("lang") : "he"));
  const t = useCallback((k) => T[lang][k], [lang]);

  const [videos, setVideos] = useState([]);
  const [config, setConfig] = useState(null);
  const [online, setOnline] = useState(false);
  const [status, setStatus] = useState({ msg: "", err: false });
  const [modal, setModal] = useState(null);       // 'preview' | 'logs' | 'telegram'
  const [preview, setPreview] = useState(null);    // { job, file }

  // Reflect UI language on <html>.
  useEffect(() => {
    document.documentElement.lang = T[lang].htmlLang;
    document.documentElement.dir = T[lang].dir;
    document.title = T[lang].docTitle;
  }, [lang]);

  const loadVideos = useCallback(() => {
    api("/api/videos").then(({ videos }) => setVideos(videos))
      .catch(e => setStatus({ msg: t("netErr") + ": " + e.message, err: true }));
  }, [t]);
  const loadConfig = useCallback(() => { api("/api/config").then(setConfig).catch(() => {}); }, []);
  const loadHealth = useCallback(() => { api("/api/health").then(h => setOnline(!!h.worker_online)).catch(() => setOnline(false)); }, []);

  useEffect(() => {
    loadVideos(); loadConfig(); loadHealth();
    const a = setInterval(loadVideos, 4000);
    const b = setInterval(loadHealth, 5000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [loadVideos, loadConfig, loadHealth]);

  function switchLang(l) { setLang(l); localStorage.setItem("lang", l); }

  async function transcribe(filename) {
    try { await post("/api/transcribe", { filename }); setStatus({ msg: "", err: false }); loadVideos(); }
    catch (e) { setStatus({ msg: t("err") + ": " + e.message, err: true }); }
  }
  async function processAll() {
    try { const r = await post("/api/transcribe-all", {}); setStatus({ msg: r.count ? T[lang].added(r.count) : t("addedNone"), err: false }); loadVideos(); }
    catch (e) { setStatus({ msg: t("err") + ": " + e.message, err: true }); }
  }
  async function del(filename) {
    if (!confirm(T[lang].deleteConfirm(filename))) return;
    try { await post("/api/delete", { filename }); setStatus({ msg: "", err: false }); loadVideos(); }
    catch (e) { setStatus({ msg: t("err") + ": " + e.message, err: true }); }
  }
  async function setLanguage(code) {
    try { await post("/api/language", { language: code }); setStatus({ msg: t("langSaved"), err: false }); loadConfig(); }
    catch (e) { setStatus({ msg: t("err") + ": " + e.message, err: true }); }
  }
  async function toggleDiar() {
    try { const r = await post("/api/diarization", { enabled: !config.diarization });
      setConfig(c => ({ ...c, diarization: r.enabled }));
      setStatus({ msg: r.enabled ? t("diarSavedOn") : t("diarSavedOff"), err: false }); }
    catch (e) { setStatus({ msg: t("err") + ": " + e.message, err: true }); }
  }

  const counts = useMemo(() => {
    let done = 0, processing = 0, queued = 0;
    videos.forEach(v => { const s = v.job && v.job.status; if (s === "done") done++; else if (s === "processing") processing++; else if (s === "queued") queued++; });
    return { done, processing, queued };
  }, [videos]);

  // Banner only for an actual (slow, one-time) download — not a quick cached load.
  const modelPrep = videos.some(v => v.job && v.job.status === "processing" && v.job.stage === "downloading_model");
  const modelName = config ? String(config.model).split("/").pop() : "";

  return (
    <>
      <header className="header">
        <div className="brand">
          <div className="logo" aria-hidden="true"><span /><span /><span /><span /><span /></div>
          <div className="titles"><div className="eyebrow">{t("eyebrow")}</div><h1>{t("title")}</h1></div>
        </div>
        <div className="spacer" />
        <div className="head-tools">
          <span className={`engine ${online ? "online" : "offline"}`} title={online ? t("workerOnlineTitle") : t("workerOfflineTitle")}>
            <span className="dot" /><span className="lbl">{online ? t("workerOnline") : t("workerOffline")}</span>
          </span>
          <span className="head-div" />
          <button className="icon-btn" onClick={() => setModal("logs")} title={t("logs")} aria-label={t("logs")}><List /></button>
          <button className="icon-btn" onClick={() => setModal("telegram")} title="Telegram" aria-label="Telegram"><Settings /></button>
          <div className="ui-lang" role="group" aria-label="Language">
            <button className={lang === "he" ? "active" : ""} onClick={() => switchLang("he")}>עב</button>
            <button className={lang === "en" ? "active" : ""} onClick={() => switchLang("en")}>EN</button>
          </div>
        </div>
      </header>

      <main className="main">
        {modelPrep && (
          <div className="banner">
            <div className="b-icon"><DownloadCloud /></div>
            <div className="b-body">
              <div className="b-title">{t("bannerModel")}</div>
              <div className="b-sub">{t("bannerModelSub")}</div>
            </div>
            <button className="b-link" onClick={() => setModal("logs")}>{t("logs")} →</button>
          </div>
        )}

        <div className="controlbar">
          <div className="cb-actions">
            <button className="btn btn-primary" onClick={processAll}>{t("processAll")}</button>
            <button className="btn btn-ghost" onClick={() => { setStatus({ msg: "", err: false }); loadVideos(); }}>{t("refresh")}</button>
          </div>
          <div className="spacer" />
          <div className="cb-settings">
            <label className="field">
              <span className="field-label">{t("language")}</span>
              <select className="lang-select" aria-label="Transcription language" value={config?.language || "he"} onChange={e => setLanguage(e.target.value)}>
                {langOptions(config, lang)}
              </select>
            </label>
            <span className="cb-div" />
            {config && (
              <button className={`switch ${config.diarization ? "on" : ""}`} onClick={toggleDiar} aria-pressed={!!config.diarization} title={t("diarTitle")}>
                <span className="switch-track"><span className="switch-knob" /></span>
                <span>{config.diarization ? t("diarOn") : t("diarOff")}</span>
              </button>
            )}
          </div>
        </div>

        <div className="meta-row">
          <div className="counts">
            {counts.done ? <span className="count done"><i /><b>{counts.done}</b> {t("cntDone")}</span> : null}
            {counts.processing ? <span className="count processing"><i /><b>{counts.processing}</b> {t("cntProcessing")}</span> : null}
            {counts.queued ? <span className="count queued"><i /><b>{counts.queued}</b> {t("cntQueued")}</span> : null}
          </div>
          <div className="spacer" />
          {modelName && <span className="model-tag">{t("model")} · {modelName}</span>}
          <span className={`status-msg ${status.err ? "err" : ""}`}>{status.msg}</span>
        </div>

        {videos.length === 0 ? (
          <div className="placeholder"><div className="mark">∅</div><div className="big">{t("emptyBig")}</div><div className="sub">{t("emptySub")}</div></div>
        ) : (
          <div className="list">
            {videos.map((item) => (
              <FileRow key={item.filename} item={item} lang={lang}
                onTranscribe={transcribe} onDelete={del}
                onOpen={(job, file) => { setPreview({ job, file }); setModal("preview"); }} />
            ))}
          </div>
        )}
      </main>

      {modal === "preview" && preview && <PreviewModal job={preview.job} file={preview.file} lang={lang} onClose={() => setModal(null)} />}
      {modal === "logs" && <LogsModal lang={lang} onClose={() => setModal(null)} />}
      {modal === "telegram" && <TelegramModal lang={lang} onClose={() => setModal(null)} />}
    </>
  );
}

function langOptions(config, uiLang) {
  const list = LANGS.slice();
  const current = config?.language;
  if (current && !list.some(l => l.code === current)) list.push({ code: current, name: current });
  return list.map(l => (
    <option key={l.code} value={l.code}>{l.code === "auto" ? T[uiLang].langAuto : (l.name || l.code)}</option>
  ));
}

function StatusCell({ job, lang }) {
  const t = (k) => T[lang][k];
  if (!job) return <span className="tag none">{t("st_none")}</span>;
  const s = job.status;
  if (s === "processing") {
    // Model download/load is a system concern (see banner + log), not the
    // file's transcription progress — show a neutral "preparing" here.
    if (MODEL_STAGES.has(job.stage)) return <span className="tag preparing"><span className="spin" />{t("preparing")}</span>;
    const p = Math.round(job.progress || 0);
    const phase = T[lang].stages[job.stage] || t("st_processing");
    return (
      <div className="prog">
        <div className="prog-cap"><span className="prog-phase">{phase}</span><span className="prog-pct">{p}%</span></div>
        <div className="scrubber"><div className="scrubber-fill" style={{ inlineSize: `${p}%` }} /></div>
      </div>
    );
  }
  if (s === "queued") return <span className="tag queued"><span className="spin" />{t("st_queued")}</span>;
  if (s === "done") return <span className="tag done">{t("st_done")}</span>;
  if (s === "failed") return (<><span className="tag failed">{t("st_failed")}</span>{job.error && <div className="err-line">{job.error}</div>}</>);
  return <span className="tag none">{t("st_none")}</span>;
}

function FileRow({ item, lang, onTranscribe, onDelete, onOpen }) {
  const t = (k) => T[lang][k];
  const job = item.job;
  const done = job && job.status === "done";
  const failed = job && job.status === "failed";
  const busy = job && (job.status === "queued" || job.status === "processing");
  const actionLabel = done ? t("again") : failed ? t("retry") : t("transcribe");

  return (
    <div className={`row ${done ? "clickable" : ""}`} onClick={done ? (e) => { if (!e.target.closest("a,button")) onOpen(job.id, item.filename); } : undefined}>
      <div className="cell-file">
        <div className="file-icon"><Film /></div>
        <div className="file-meta">
          <div className="file-name">{item.filename}</div>
          {done && (job.duration || job.speakers) && (
            <div className="file-sub" title={t("procTime")}>
              {job.duration ? <span className="chip-m"><Clock />{formatDur(job.duration)}</span> : null}
              {job.duration && job.speakers ? <span className="dotsep">·</span> : null}
              {job.speakers ? <span className="chip-m"><Users />{T[lang].speakers(job.speakers)}</span> : null}
            </div>
          )}
        </div>
      </div>
      <div className="cell-status"><StatusCell job={job} lang={lang} /></div>
      <div className="cell-actions">
        {done && <button className="act" onClick={() => onOpen(job.id, item.filename)}><Eye /><span>{t("preview")}</span></button>}
        {done && <a className="act ghost" href={`/api/jobs/${job.id}/srt`} download>{t("downloadSrt")}</a>}
        {done && <a className="act ghost" href={`/api/jobs/${job.id}/txt`} download>{t("downloadTxt")}</a>}
        <button className="act primary" disabled={busy} onClick={() => onTranscribe(item.filename)}>{actionLabel}</button>
        <button className="act icon danger" disabled={busy} onClick={() => onDelete(item.filename)} title={t("deleteLabel")} aria-label={t("deleteLabel")}><Trash /></button>
      </div>
    </div>
  );
}
