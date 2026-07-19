import React, { useEffect, useRef, useState } from "react";
import { api, post } from "./api.js";
import { T } from "./i18n.js";
import { X } from "./icons.jsx";

function useEscape(onClose) {
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose]);
}

// ---------- Transcript preview ----------
export function PreviewModal({ job, file, lang, onClose }) {
  const t = (k) => T[lang][k];
  const [view, setView] = useState("txt");
  const [text, setText] = useState(null);
  const [meta, setMeta] = useState("");
  const [copied, setCopied] = useState(false);
  useEscape(onClose);

  useEffect(() => {
    let alive = true;
    setText(null); setMeta("");
    fetch(`/api/jobs/${job}/${view}`).then(r => r.text()).then(txt => {
      if (!alive) return;
      setText(txt);
      if (!txt.trim()) { setMeta(""); return; }
      if (view === "srt") setMeta(T[lang].segCount((txt.match(/-->/g) || []).length));
      else setMeta(T[lang].segCount(txt.split("\n").filter(l => l.trim()).length));
    }).catch(() => alive && setText(""));
    return () => { alive = false; };
  }, [job, view, lang]);

  function copy() {
    navigator.clipboard.writeText(text || "").then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1400);
    }).catch(() => {});
  }

  function renderBody() {
    if (text === null) return <div className="modal-loading">{t("pvLoading")}</div>;
    if (!text.trim()) return <div className="modal-body empty-note">{t("pvEmpty")}</div>;
    if (view === "srt") {
      return <div className="modal-body srt">{text.split("\n").map((line, i) => {
        if (/^\d+$/.test(line.trim())) return <div key={i}><span className="cue-idx">{line}</span></div>;
        if (line.includes("-->")) return <div key={i}><span className="cue-time">{line}</span></div>;
        return <div key={i}>{line}</div>;
      })}</div>;
    }
    return <div className="modal-body">{text}</div>;
  }

  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <div className="mtitle grow"><div className="name">{file}</div><div className="meta">{meta}</div></div>
          <div className="seg">
            <button className={view === "txt" ? "active" : ""} onClick={() => setView("txt")}>{t("viewText")}</button>
            <button className={view === "srt" ? "active" : ""} onClick={() => setView("srt")}>{t("viewSrt")}</button>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X /></button>
        </div>
        {renderBody()}
        <div className="modal-foot">
          <button className="mini" onClick={copy}>{copied ? t("copied") : t("copy")}</button>
          <div className="grow" />
          <a className="mini" href={`/api/jobs/${job}/srt`} download>{t("downloadSrt")}</a>
          <a className="mini solid" href={`/api/jobs/${job}/txt`} download>{t("downloadTxt")}</a>
        </div>
      </div>
    </div>
  );
}

// ---------- System log ----------
export function LogsModal({ lang, onClose }) {
  const t = (k) => T[lang][k];
  const [source, setSource] = useState("all");
  const [logs, setLogs] = useState([]);
  const bodyRef = useRef(null);
  useEscape(onClose);

  useEffect(() => {
    let alive = true;
    const load = () => api(`/api/logs?source=${source}&limit=200`).then(({ logs }) => {
      if (!alive) return;
      setLogs(logs);
      requestAnimationFrame(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; });
    }).catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => { alive = false; clearInterval(id); };
  }, [source]);

  const fmt = (ts) => { const d = new Date(ts * 1000); const p = (n) => String(n).padStart(2, "0"); return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };

  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <div className="mtitle grow"><div className="name">{t("logsTitle")}</div><div className="meta">{logs.length ? T[lang].segCount(logs.length) : ""}</div></div>
          <div className="seg">
            {[["all", t("logsAll")], ["worker", "worker"], ["api", "api"], ["bot", "bot"]].map(([s, label]) => (
              <button key={s} className={source === s ? "active" : ""} onClick={() => setSource(s)}>{label}</button>
            ))}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X /></button>
        </div>
        <div className="modal-body srt logs-body" ref={bodyRef}>
          {logs.length === 0
            ? <div className="modal-loading">{t("logsEmpty")}</div>
            : logs.slice().reverse().map((l, i) => (
              <div key={i} className={`log-line ${l.level}`}>
                <span className="lt">{fmt(l.ts)}</span>
                <span className={`ls ${l.source}`}>{l.source}</span>
                <span className="lm">{l.message}</span>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

// ---------- Telegram settings ----------
export function TelegramModal({ lang, onClose }) {
  const t = (k) => T[lang][k];
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ bot_token: "", api_id: "", api_hash: "", allowed_ids: "", enabled: false });
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  useEscape(onClose);

  useEffect(() => {
    let alive = true;
    const badge = () => api("/api/settings/telegram").then(d => alive && setData(d)).catch(() => {});
    api("/api/settings/telegram").then(d => {
      if (!alive) return;
      setData(d);
      setForm({ bot_token: "", api_id: d.api_id || "", api_hash: "", allowed_ids: d.allowed_ids || "", enabled: !!d.enabled });
    }).catch(e => setMsg(e.message));
    const id = setInterval(badge, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  async function save() {
    setSaving(true); setMsg("");
    try {
      const d = await post("/api/settings/telegram", form);
      setData(d);
      setForm(f => ({ ...f, bot_token: "", api_hash: "" }));
      setMsg(t("tgSaved"));
    } catch (e) { setMsg(t("err") + ": " + e.message); }
    finally { setSaving(false); }
  }

  function badge() {
    if (!data) return null;
    const s = data.status || "not_configured";
    const label = (T[lang].tgConn && T[lang].tgConn[s]) || s;
    let extra = "";
    if (s === "connected") {
      if (data.bot_username) extra = ` @${data.bot_username}`;
      const cap = data.mode === "local" ? "2GB" : data.mode === "cloud" ? "20MB" : "";
      if (cap) extra += ` · ${lang === "he" ? "עד " : "up to "}${cap}`;
    }
    if (s === "error" && data.last_error) extra = ` · ${data.last_error}`;
    return <span className={`conn ${s}`}><i />{label}{extra}</span>;
  }

  const guide = T[lang].tgGuide || [];
  const tokPh = data && data.has_token ? t("tgLeaveBlank") : "123456:ABC-DEF…";
  const hashPh = data && data.has_api_hash ? t("tgLeaveBlank") : "0123456789abcdef…";

  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <div className="mtitle grow"><div className="name">{t("tgTitle")}</div><div className="meta">{badge()}</div></div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X /></button>
        </div>
        <div className="modal-body" style={{ whiteSpace: "normal" }}>
          <div className="tg-note">{t("tgIntro")}</div>
          <div className="tg-steps">
            {guide.map((step, i) => (
              <div className="tg-step" key={i}>
                <div className="tg-step-num">{i + 1}</div>
                <div className="tg-step-body">
                  <div className="tg-step-head">
                    <span className="tg-step-title">{step.title}</span>
                    <span className="tg-fills">{t("tgFills")} <b>{step.fills}</b></span>
                  </div>
                  {step.note && <div className="tg-step-note">{step.note}</div>}
                  <ol className="tg-substeps">{step.items.map((it, j) => <li key={j}>{it}</li>)}</ol>
                  <a className="mini" href={step.link} target="_blank" rel="noopener">↗ {t("tgOpen")} {step.linkText}</a>
                </div>
              </div>
            ))}
          </div>
          <div className="tg-final">{t("tgFinal")}</div>
          <div className="tg-form">
            <label className="fld"><span>{t("tgToken")}</span>
              <input type="password" autoComplete="off" placeholder={tokPh} value={form.bot_token} onChange={e => setForm({ ...form, bot_token: e.target.value })} />
            </label>
            <div className="fld-row">
              <label className="fld"><span>{t("tgApiId")}</span>
                <input type="text" inputMode="numeric" autoComplete="off" placeholder="1234567" value={form.api_id} onChange={e => setForm({ ...form, api_id: e.target.value })} />
              </label>
              <label className="fld"><span>{t("tgApiHash")}</span>
                <input type="password" autoComplete="off" placeholder={hashPh} value={form.api_hash} onChange={e => setForm({ ...form, api_hash: e.target.value })} />
              </label>
            </div>
            <small className="fld-hint fld-optional">{t("tgApiOptional")}</small>
            <label className="fld"><span>{t("tgAllowed")}</span>
              <input type="text" autoComplete="off" placeholder="123456789, 987654321" value={form.allowed_ids} onChange={e => setForm({ ...form, allowed_ids: e.target.value })} />
              <small className="fld-hint">{t("tgAllowedHint")}</small>
            </label>
            <label className="tg-toggle">
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} />
              <span>{t("tgEnable")}</span>
            </label>
          </div>
        </div>
        <div className="modal-foot">
          <span className="status-msg">{msg}</span>
          <div className="grow" />
          <button className="mini solid" onClick={save} disabled={saving}>{t("tgSave")}</button>
        </div>
      </div>
    </div>
  );
}
