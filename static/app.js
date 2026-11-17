const { useEffect, useState } = React;
const h = React.createElement;

function Icon({ name, size = 18 }) {
  const paths = {
    spark: "M12 2l1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7L12 2z",
    grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    sliders: "M4 6h16M4 12h16M4 18h16M8 4v4M16 10v4M10 16v4",
    check: "M5 12l4 4L19 6",
    cube: "M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zm0 0v9m8-4.5l-8 4.5m-8-4.5l8 4.5",
  };
  return h("svg", { className: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true }, h("path", { d: paths[name] || paths.spark }));
}

function Plan2D({ layout, plot }) {
  const width = 720;
  const height = 520;
  const scale = Math.min((width - 56) / plot.width_m, (height - 56) / plot.length_m);
  const project = ([x, y]) => [28 + x * scale, height - 28 - y * scale];
  return h("div", { className: "plan-frame" },
    h("svg", { className: "plan", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "2D floor plan" },
      h("defs", null, h("pattern", { id: "grid-pattern", width: 20, height: 20, patternUnits: "userSpaceOnUse" }, h("path", { d: "M 20 0 L 0 0 0 20", fill: "none", stroke: "#dbe6f2", strokeWidth: 0.7 }))),
      h("rect", { x: 0, y: 0, width, height, fill: "url(#grid-pattern)" }),
      h("rect", { x: 28, y: height - 28 - plot.length_m * scale, width: plot.width_m * scale, height: plot.length_m * scale, fill: "#fff", stroke: "#19324d", strokeWidth: 3, rx: 2 }),
      layout.rooms.map(room => {
        const points = room.polygon.map(project).map(point => point.join(",")).join(" ");
        const centroid = room.polygon.slice(0, -1).reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0]).map(value => value / (room.polygon.length - 1));
        const label = project(centroid);
        return h("g", { key: room.id },
          h("polygon", { points, fill: room.color, stroke: "#fff", strokeWidth: 2 }),
          h("text", { x: label[0], y: label[1] - 4, className: "room-label" }, room.id.replaceAll("_", " ")),
          h("text", { x: label[0], y: label[1] + 11, className: "room-area" }, `${room.area} m²`)
        );
      }),
      h("text", { x: width / 2, y: height - 8, className: "dimension-label" }, `${plot.width_ft} ft wide`),
      h("text", { x: 10, y: height / 2, className: "dimension-label", transform: `rotate(-90 10 ${height / 2})` }, `${plot.length_ft} ft deep`)
    )
  );
}

function Model3D({ layout, darkMode }) {
  const ref = React.useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    Plotly.newPlot(ref.current, layout.meshes.map(mesh => ({ ...mesh, type: "mesh3d", opacity: 0.78, hoverinfo: "name" })), {
      margin: { l: 0, r: 0, t: 12, b: 0 },
      paper_bgcolor: "rgba(0,0,0,0)",
      scene: { aspectmode: "data", bgcolor: darkMode ? "#182435" : "#f7fafc", xaxis: { title: "m", gridcolor: darkMode ? "#34465d" : "#dbe6f2", color: darkMode ? "#b8c5d6" : "#19324d" }, yaxis: { title: "m", gridcolor: darkMode ? "#34465d" : "#dbe6f2", color: darkMode ? "#b8c5d6" : "#19324d" }, zaxis: { title: "m", gridcolor: darkMode ? "#34465d" : "#dbe6f2", color: darkMode ? "#b8c5d6" : "#19324d" } },
      showlegend: false,
    }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] });
    return () => { if (ref.current) Plotly.purge(ref.current); };
  }, [layout, darkMode]);
  return h("div", { ref, className: "model" });
}

function Report({ report }) {
  return h("div", { className: "report-wrap" },
    h("table", { className: "report" },
      h("thead", null, h("tr", null, ["Constraint", "Status", "Type", "Explanation"].map(item => h("th", { key: item }, item)))),
      h("tbody", null, report.map(item => h("tr", { key: item.constraint_id },
        h("td", { className: "constraint-name" }, item.constraint_id.replaceAll("_", " ")),
        h("td", null, h("span", { className: `status ${item.passed ? "status-pass" : "status-fail"}` }, h(Icon, { name: item.passed ? "check" : "spark", size: 13 }), item.passed ? "Pass" : "Fail")),
        h("td", null, h("span", { className: "type-tag" }, item.hard ? "hard" : "soft")),
        h("td", { className: "explanation" }, item.explanation)
      )))
    )
  );
}

function Metric({ label, value, accent }) {
  return h("div", { className: "metric", style: { "--metric-accent": accent } },
    h("span", { className: "metric-label" }, label.replaceAll("_", " ")),
    h("strong", null, typeof value === "number" ? value.toFixed(3) : value)
  );
}

function App() {
  const [form, setForm] = useState({ plot_w_ft: 30, plot_l_ft: 50, bhk: 3, priority: "space", seed: 42, candidates: 60 });
  const [data, setData] = useState(null);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [darkMode, setDarkMode] = useState(false);
  const update = event => setForm({ ...form, [event.target.name]: event.target.value });
  const generate = async event => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, plot_w_ft: Number(form.plot_w_ft), plot_l_ft: Number(form.plot_l_ft), bhk: Number(form.bhk), seed: Number(form.seed), candidates: Number(form.candidates) }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Generation failed");
      setData(payload);
      setActive(0);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setLoading(false);
    }
  };
  const layout = data?.layouts?.[active];
  return h("main", { className: `app ${darkMode ? "dark-mode" : ""}` },
    h("div", { className: "shell" },
      h("header", { className: "header" },
        h("div", { className: "brand-row" }, h("div", { className: "brand-mark" }, h(Icon, { name: "spark", size: 21 })), h("span", { className: "eyebrow" }, "Spatial design studio")),
        h("div", { className: "header-copy" }, h("h1", null, "Interior Layout"), h("p", { className: "subtitle" }, "Generate considered floor plans from a few simple dimensions.")),
        h("div", { className: "header-actions" }, h("button", { type: "button", className: "theme-toggle", onClick: () => setDarkMode(!darkMode), "aria-label": darkMode ? "Switch to light mode" : "Switch to dark mode" }, h("span", { className: "theme-icon" }, darkMode ? "☀" : "☾"), darkMode ? "Light mode" : "Dark mode"), h("div", { className: "engine-chip" }, h("span", { className: "live-dot" }), "Deterministic engine"))
      ),
      h("div", { className: "workspace" },
        h("form", { className: "panel controls", onSubmit: generate },
          h("div", { className: "panel-heading" }, h("div", { className: "heading-icon" }, h(Icon, { name: "sliders" })), h("div", null, h("h2", null, "Design brief"), h("p", null, "Set your site parameters"))),
          h("div", { className: "form-section" },
            h("div", { className: "section-label" }, "Plot dimensions"),
            h("div", { className: "field-grid" }, [["plot_w_ft", "Width", "ft"], ["plot_l_ft", "Length", "ft"]].map(([name, label, unit]) => h("label", { className: "field", key: name }, h("span", null, label), h("div", { className: "input-wrap" }, h("input", { name, type: "number", value: form[name], min: 1, onChange: update }), h("em", null, unit)))))
          ),
          h("div", { className: "form-section" },
            h("div", { className: "section-label" }, "Home profile"),
            h("label", { className: "field" }, h("span", null, "Configuration"), h("select", { name: "bhk", value: form.bhk, onChange: update }, h("option", { value: 2 }, "2 BHK"), h("option", { value: 3 }, "3 BHK"))),
            h("div", { className: "section-label priority-title" }, "Design priority"),
            h("div", { className: "priority-grid" }, [["light", "Light", "Bright perimeter rooms"], ["space", "Space", "Balanced usable area"], ["privacy", "Privacy", "Separate bedroom zone"]].map(([value, label, detail]) => h("label", { className: `priority-card ${form.priority === value ? "selected" : ""}`, key: value }, h("input", { type: "radio", name: "priority", value, checked: form.priority === value, onChange: update }), h("span", null, h("strong", null, label), h("small", null, detail)))))
          ),
          h("div", { className: "form-section compact-fields" }, h("label", { className: "field" }, h("span", null, "Seed"), h("input", { name: "seed", type: "number", value: form.seed, onChange: update })), h("label", { className: "field" }, h("span", null, "Candidates"), h("input", { name: "candidates", type: "number", value: form.candidates, min: 1, max: 500, onChange: update }))),
          h("button", { className: "generate-button", disabled: loading }, h(Icon, { name: "spark", size: 17 }), loading ? "Generating layouts..." : "Generate layouts")
        ),
        h("section", { className: "content" },
          error && h("div", { className: "error" }, h(Icon, { name: "spark" }), error),
          !data && !error && h("div", { className: "empty card" }, h("div", { className: "empty-icon" }, h(Icon, { name: "grid", size: 30 })), h("h2", null, "Your plan starts here"), h("p", null, "Enter your plot details and generate a set of layouts tailored to your brief.")),
          data && h(React.Fragment, null,
            h("div", { className: "summary" }, h("div", { className: "summary-card" }, h("span", null, "Candidates explored"), h("strong", null, data.candidate_count)), h("div", { className: "summary-card" }, h("span", null, "Valid layouts"), h("strong", null, data.valid_count)), h("div", { className: "summary-card summary-note" }, h("span", null, "Planning units"), h("strong", null, "metres"), h("small", null, `${data.plot.width_ft} × ${data.plot.length_ft} ft site`))),
            h("div", { className: "tabs-bar" }, h("div", { className: "tabs-label" }, h(Icon, { name: "grid", size: 16 }), "Generated concepts"), h("div", { className: "tabs" }, data.layouts.map((item, index) => h("button", { type: "button", className: `tab ${index === active ? "active" : ""}`, onClick: () => setActive(index), key: item.seed }, h("span", null, `Option ${String(index + 1).padStart(2, "0")}`), h("small", null, `${item.score}/100`))))),
            layout && h("div", { className: "card result-card" },
              h("div", { className: "result-heading" }, h("div", null, h("div", { className: "eyebrow blue" }, `Concept ${String(active + 1).padStart(2, "0")}`), h("h2", null, "A balanced spatial arrangement"), h("p", { className: "muted" }, `Seed ${layout.seed} · ranked by ${form.priority} priority`)), h("div", { className: "score-ring" }, h("strong", null, layout.score), h("span", null, "/ 100"))),
              h("div", { className: "breakdown" }, Object.entries(layout.score_breakdown).map(([key, value], index) => h(Metric, { key, label: key, value, accent: ["#6b8afd", "#8b7cf6", "#34bfa3", "#f0a35b", "#df7696"][index] }))),
              h("div", { className: "visual-grid" }, h("div", { className: "visual-card" }, h("div", { className: "visual-heading" }, h("div", null, h("h3", null, "Floor plan"), h("p", null, "Rooms, proportions and circulation")), h("span", { className: "view-tag" }, "2D")), h(Plan2D, { layout, plot: data.plot })), h("div", { className: "visual-card" }, h("div", { className: "visual-heading" }, h("div", null, h("h3", null, "Spatial massing"), h("p", null, "Orbit to inspect room volumes")), h("span", { className: "view-tag" }, h(Icon, { name: "cube", size: 13 }), "3D")), h(Model3D, { layout, darkMode }))),
              h("div", { className: "report-heading" }, h("div", null, h("h3", null, "Validation report"), h("p", null, "Every generated concept is checked against the prototype constraints.")), h("span", { className: "verified" }, h(Icon, { name: "check", size: 14 }), "Checked")),
              h(Report, { report: layout.report })
            )
          )
        )
      )
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
