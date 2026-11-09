(function () {
  const plan = window.PLAN;

  // Tiny element helper: h("div", { class: "x" }, child, "text", ...)
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null) continue;
      if (k === "style") {
        for (const [prop, val] of Object.entries(v)) {
          if (val == null) continue;
          if (prop.startsWith("--")) el.style.setProperty(prop, val);
          else el.style[prop] = val;
        }
      }
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(c));
    }
    return el;
  }

  function dots(level, color, cls, label) {
    return h(
      "span",
      { class: cls, style: { "--dot": color }, role: label ? "img" : null, "aria-label": label },
      [1, 2, 3].map((i) => h("span", { class: i <= level ? "dot is-on" : "dot" }))
    );
  }

  // Header
  document.getElementById("eyebrow").textContent = plan.eyebrow;
  document.getElementById("title").textContent = plan.title;

  document.getElementById("legend-types").append(
    ...Object.values(plan.types).map((t) =>
      h("span", { class: "legend-item" }, h("span", { class: "swatch", style: { background: t.color } }), t.label)
    )
  );
  document.getElementById("legend-effort").append(
    h("strong", null, "Effort"),
    ...Object.entries(plan.efforts).map(([name, lvl]) =>
      h("span", { class: "legend-item" }, dots(lvl, "#fff", "dots dots--sm"), name)
    )
  );

  // Phase strip
  document.getElementById("phases").append(
    ...plan.phases.map((p) =>
      h(
        "div",
        { class: `phase phase--${p.kind}`, style: { gridColumn: `span ${p.span}`, background: p.bg } },
        h("span", { class: "phase-name" }, p.name),
        h("span", null, p.weeks)
      )
    )
  );

  // Week grid
  document.getElementById("week").append(
    ...plan.week.map((d) => {
      const color = plan.types[d.type].color;
      return h(
        "article",
        { class: "day" },
        h("h3", { class: "day-head", style: { background: color } }, d.day),
        h(
          "div",
          { class: "day-body" },
          h("div", { class: "day-title" }, d.title),
          h("div", { class: "day-detail" }, d.detail),
          dots(plan.efforts[d.effort], color, "dots dots--day", `Effort: ${d.effort}`)
        )
      );
    })
  );

  // Strength sessions
  document.getElementById("strength").append(
    ...plan.strength.map((s) =>
      h(
        "section",
        { class: "card session" },
        h(
          "header",
          { class: "session-head" },
          h("div", null, h("div", { class: "eyebrow-sm" }, s.day), h("h2", { class: "display display--md" }, s.title)),
          h("div", { class: "session-focus" }, s.focus[0], h("div", null, s.focus[1]))
        ),
        h("div", { class: "cols cols--head" }, h("span", null, "WK 1–4"), h("span", null, "WK 5–11")),
        h(
          "ol",
          { class: "exercises" },
          s.exercises.map((e, i) =>
            h(
              "li",
              { class: "exercise" },
              h(
                "div",
                { class: "exercise-row" },
                h("span", { class: "num", "aria-hidden": "true" }, String(i + 1)),
                h("span", { class: "exercise-name" }, e.name, e.note && h("span", { class: "exercise-note" }, ` · ${e.note}`)),
                h("span", { class: "rest" }, e.rest)
              ),
              h("div", { class: "cols cols--sets" }, h("span", null, e.early), h("span", null, e.late))
            )
          )
        ),
        h("footer", { class: "session-foot" }, s.footer)
      )
    )
  );

  // Notes
  document.getElementById("notes").append(
    ...plan.notes.map((n) =>
      h(
        "section",
        { class: "card note" },
        h(
          "div",
          { class: "note-head" },
          h("h2", { class: "display display--sm" }, n.title),
          h("span", { class: "pill", style: { background: plan.types[n.type].color } }, n.days)
        ),
        h("ul", null, n.items.map((it) => h("li", null, it)))
      )
    )
  );

  // Scale the fixed-size A4 sheet down to fit narrow screens (screen only).
  const sheet = document.querySelector(".sheet");
  const stage = document.querySelector(".stage");
  function fit() {
    const avail = stage.clientWidth - 32;
    const s = Math.min(1, avail / 794);
    sheet.style.setProperty("--scale", s);
    stage.style.height = s < 1 ? `${1123 * s + 32}px` : "";
  }
  window.addEventListener("resize", fit);
  fit();
})();
