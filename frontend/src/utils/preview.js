export function sanitizeForPreview(code) {
  const lines = (code || "").split("\n");
  const out = [];
  for (const line of lines) {
    const stripped = line.trim();
    if (/^import\s+.*\s+from\s+/.test(stripped)) continue;
    if (/^import\{/.test(stripped.replace(/\s/g, ""))) continue;
    if (stripped.startsWith("export default")) {
      out.push(stripped.replace("export default", ""));
      continue;
    }
    if (stripped.startsWith("export ")) {
      out.push(line.replace("export ", ""));
      continue;
    }
    out.push(line);
  }
  let cleaned = out.join("\n").trim();
  if (!/function\s+App|const\s+App|class\s+App/.test(cleaned)) {
    const snippet = cleaned.slice(0, 2000).replace(/`/g, "'");
    cleaned = `function App() {\n  return (<div style={{padding:24}}><pre>${snippet}</pre></div>);\n}`;
  }
  return cleaned;
}

const PREVIEW_MOCK_JS = `window.__VR_PREVIEW__ = (function() {
  function ph(seed) {
    var s = String(seed || "VR").slice(0, 16);
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>"
      + "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
      + "<stop offset='0' stop-color='#c7d2fe'/><stop offset='1' stop-color='#818cf8'/>"
      + "</linearGradient></defs>"
      + "<rect width='400' height='300' fill='url(#g)'/>"
      + "<text x='200' y='155' font-size='22' text-anchor='middle' fill='#312e81'>" + s + "</text></svg>";
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }
  function products() {
    var names = ["Aurora Headphones", "Nimbus Sneakers", "Vertex Watch", "Lumen Lamp", "Orbit Backpack", "Pulse Speaker"];
    var cats = ["Electronics", "Fashion", "Wearables", "Home", "Travel", "Audio"];
    var prices = [49.99, 89.99, 199.99, 39.99, 59.99, 129.99];
    var ratings = [4.8, 4.6, 4.9, 4.5, 4.7, 4.8];
    return names.map(function(n, i) {
      return { id: i + 1, name: n, title: n, price: prices[i], image: ph(n.split(" ")[0]),
        description: "Top-rated " + n.toLowerCase() + " with free shipping and easy returns.",
        category: cats[i], rating: ratings[i], stock: [12, 5, 8, 20, 15, 7][i] };
    });
  }
  function books() {
    var data = [["The Silent API", "Ada Lovelace"], ["Refactoring Reality", "Martin Fowler"], ["Clean Previews", "Grace Hopper"], ["Domain Patterns", "Eric Evans"]];
    return data.map(function(b, i) {
      return { id: i + 1, title: b[0], name: b[0], author: b[1], price: [19.99, 29.99, 24.99, 34.99][i],
        cover: ph("Book"), image: ph("Book"), description: "A must-read for every software shelf.", category: "Books", rating: 4.7 };
    });
  }
  function users() {
    var data = [["Aarav Sharma", "Admin"], ["Sofia Reyes", "Customer"], ["Liam Carter", "Seller"], ["Mia Khan", "Support"]];
    return data.map(function(u, i) {
      return { id: i + 1, name: u[0], username: u[0].toLowerCase().replace(/ /g, "."), email: u[0].toLowerCase().replace(/ /g, ".") + "@example.com",
        role: u[1], avatar: ph(u[0].split(" ")[0]), image: ph(u[0].split(" ")[0]) };
    });
  }
  function todos() {
    var data = ["Design the home page", "Wire up product listings", "Add cart checkout", "Write API docs"];
    return data.map(function(t, i) {
      return { id: i + 1, title: t, name: t, completed: i < 2, status: i < 2 ? "done" : "open" };
    });
  }
  function orders() {
    return [101, 102, 103].map(function(n, i) {
      return { id: n, total: [59.98, 129.99, 24.99][i], status: ["delivered", "shipped", "processing"][i],
        product: ["Aurora Headphones", "Vertex Watch", "Lumen Lamp"][i], name: "Order #" + n, date: "2026-09-0" + (i + 1) };
    });
  }
  function generic() {
    return [1, 2, 3, 4].map(function(i) {
      return { id: i, name: "Item " + i, title: "Item " + i, description: "Sample record " + i + " for preview.",
        image: ph("Item " + i), status: "active", price: i * 10 + 9.99 };
    });
  }
  function pick(u) {
    u = String(u || "").toLowerCase();
    if (u.indexOf("product") >= 0 || u.indexOf("shop") >= 0 || u.indexOf("store") >= 0 || u.indexOf("cart") >= 0 || u.indexOf("categor") >= 0) return products();
    if (u.indexOf("book") >= 0) return books();
    if (u.indexOf("user") >= 0 || u.indexOf("employee") >= 0 || u.indexOf("customer") >= 0 || u.indexOf("member") >= 0) return users();
    if (u.indexOf("todo") >= 0 || u.indexOf("task") >= 0) return todos();
    if (u.indexOf("order") >= 0) return orders();
    return generic();
  }
  function envelope(items) {
    var arr = items.slice();
    var keys = ["products", "items", "data", "results", "content", "books", "users", "orders", "todos", "tasks"];
    for (var i = 0; i < keys.length; i++) arr[keys[i]] = arr;
    return arr;
  }
  var origFetch = window.fetch;
  window.fetch = function(url, opts) {
    try {
      var raw = (url && url.url) || url || "";
      var u = String(raw);
      var low = u.toLowerCase();
      var method = ((opts && opts.method) || "GET").toUpperCase();
      var isApi = low.indexOf("/api/") >= 0 || u.charAt(0) === "/" || low.indexOf("localhost") >= 0
        || low.indexOf(":8080") >= 0 || low.indexOf(":8000") >= 0 || low.indexOf(":5000") >= 0 || low.indexOf(":3000") >= 0;
      if (isApi) {
        if (method === "POST" || method === "PUT" || method === "PATCH") {
          var created = { id: Date.now(), ok: true };
          try { created = Object.assign({ id: Date.now() }, JSON.parse(opts.body || "{}")); } catch (e) {}
          return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve(created); }, text: function() { return Promise.resolve(JSON.stringify(created)); } });
        }
        if (method === "DELETE") {
          return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve({ ok: true }); }, text: function() { return Promise.resolve("{}"); } });
        }
        var items = envelope(pick(u));
        return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve(items); }, text: function() { return Promise.resolve(JSON.stringify(items.slice())); } });
      }
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };
  document.addEventListener("error", function(e) {
    var t = e.target;
    if (t && t.tagName === "IMG" && !t.__vrFixed) { t.__vrFixed = true; t.src = ph(t.alt || "image"); }
  }, true);
  window.addEventListener("error", function(e) {
    var box = document.getElementById("preview-error");
    if (box) { box.style.display = "block"; box.textContent = "Preview error: " + (e.message || e.error); }
  });
})();`;

export function buildPreviewHtml(frontendCode, taskTitle) {
  const appBody = sanitizeForPreview(frontendCode || "// No frontend generated").replace(/<\/script>/g, "<\\/script>");
  const safeTitle = String(taskTitle || "VeriReview Preview").replace(/</g, "&lt;").replace(/>/g, "&gt;").slice(0, 120);
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>${safeTitle} - Preview</title>
<style>
  body { margin: 0; font-family: Inter, system-ui, sans-serif; background: #f8fafc; color: #0f172a; }
  #preview-note { background: #4f46e5; color: #fff; font-size: 12px; padding: 8px 14px; }
  #root { padding: 24px; max-width: 1100px; margin: 0 auto; min-height: 200px; }
  #preview-loading { color: #64748b; font-size: 13px; padding: 24px 0; }
  #preview-error { display: none; margin: 16px; padding: 12px; background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; border-radius: 8px; font-size: 13px; white-space: pre-wrap; }
  #root img { max-width: 100%; }
</style>
</head>
<body>
<div id="preview-note">VeriReview UI preview - backend API calls are mocked with realistic sample data.</div>
<div id="preview-error"></div>
<div id="root"><div id="preview-loading">Loading preview…</div></div>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script>
${PREVIEW_MOCK_JS}
</script>
<script type="text/babel" data-presets="react">
const { useState, useEffect, useRef, useMemo } = React;
${appBody}
try {
  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(React.createElement(typeof App !== "undefined" ? App : function() { return React.createElement("div", null, "No App component found"); }));
} catch (err) {
  document.getElementById("preview-error").style.display = "block";
  document.getElementById("preview-error").textContent = "Preview error: " + err.message;
}
</script>
</body>
</html>`;
}
