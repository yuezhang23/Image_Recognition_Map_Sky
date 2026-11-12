// Floating result panel on the checked page. Injected by the service worker; safe to inject more than once.
(() => {
  if (window.__podShowPanel) return;
  const CHECKS = { r1_label: "R1 Label", r2_placement: "R2 Placement", r3_address: "R3 Address",
                   r4_scenario: "R4 Scenario", r5_prohibited: "R5 Prohibited" };
  const COLORS = { PASS: "#1a7f37", FAIL: "#cf222e", REVIEW: "#9a6700", "N/A": "#6e7781" };

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;top:16px;right:16px;z-index:2147483647;";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
    .box{width:340px;max-height:80vh;overflow:auto;background:#fff;color:#1f2328;border:1px solid #d0d7de;
         border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.18);font:13px/1.45 system-ui,sans-serif;padding:12px 14px}
    .head{display:flex;justify-content:space-between;align-items:center;gap:8px}
    .verdict{font-weight:700;font-size:15px}
    button{border:0;background:none;font-size:18px;cursor:pointer;color:#6e7781;line-height:1}
    .muted{color:#6e7781;font-size:12px;word-break:break-all}
    .row{display:flex;gap:8px;margin-top:6px;align-items:flex-start}
    .badge{flex:none;min-width:52px;text-align:center;border-radius:4px;color:#fff;font-size:11px;font-weight:600;padding:1px 4px}
    .err{color:#cf222e;white-space:pre-wrap}
  </style><div class="box"></div>`;
  const box = root.querySelector(".box");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  window.__podShowPanel = (s) => {
    if (!host.isConnected) document.documentElement.appendChild(host);
    let body;
    if (s.status === "running") body = `<div class="verdict">Checking…</div><div class="muted">${esc(s.step)}</div>`;
    else if (s.status === "error") body = `<div class="verdict" style="color:${COLORS.FAIL}">Error</div><div class="err">${esc(s.error)}</div>`;
    else {
      body = `<div class="verdict" style="color:${COLORS[s.verdict]}">${esc(s.verdict)}</div>` +
        Object.entries(CHECKS).map(([k, name]) => {
          const c = (s.checks || {})[k] || { status: "REVIEW", reason: "" };
          return `<div class="row"><span class="badge" style="background:${COLORS[c.status]}">${esc(c.status)}</span>` +
                 `<div><b>${name}</b><div class="muted">${esc(c.reason)}</div></div></div>`;
        }).join("") +
        `<div class="muted" style="margin-top:8px">${esc(s.vendor)} / ${esc(s.model)} · ${s.photos.length} photos</div>`;
    }
    box.innerHTML = `<div class="head"><span><b>POD check</b> <span class="muted">${esc(s.trackingId)}</span></span>` +
      `<button title="Close">×</button></div><div class="muted">${esc(s.address)}</div><div style="margin-top:8px">${body}</div>`;
    box.querySelector("button").onclick = () => host.remove();
  };
})();
