// All content for the training sheet. Edit here; render.js builds the page from it.
window.PLAN = {
  eyebrow: "BIKE · RUN · STRENGTH",
  title: "12-Week Training Plan",

  // Session types: name + colour token (see styles.css)
  types: {
    sprint: { label: "Sprint class", color: "var(--sprint)" },
    strength: { label: "Strength", color: "var(--strength)" },
    run: { label: "Easy run", color: "var(--run)" },
    ride: { label: "Long ride", color: "var(--ride)" },
  },

  efforts: { easy: 1, medium: 2, hard: 3 },

  // Phase strip across the 12 weeks. `kind`: block | deload | retest
  phases: [
    { name: "BASE", weeks: "Wk 1–3", span: 3, kind: "block", bg: "var(--phase-base)" },
    { name: "Deload", weeks: "Wk 4", span: 1, kind: "deload" },
    { name: "BUILD", weeks: "Wk 5–7", span: 3, kind: "block", bg: "var(--phase-build)" },
    { name: "Deload", weeks: "Wk 8", span: 1, kind: "deload" },
    { name: "PEAK", weeks: "Wk 9–11", span: 3, kind: "block", bg: "var(--phase-peak)" },
    { name: "Retest", weeks: "Wk 12", span: 1, kind: "retest" },
  ],

  week: [
    { day: "MON", type: "run", title: "Easy run", detail: "30-35 min, easy pace", effort: "easy" },
    { day: "TUE", type: "sprint", title: "Les Mills Sprint", detail: "Hard day", effort: "hard" },
    { day: "WED", type: "strength", title: "Strength A", detail: "Upper body + trunk", effort: "medium" },
    { day: "THU", type: "sprint", title: "Les Mills Sprint", detail: "Hard day", effort: "hard" },
    { day: "FRI", type: "run", title: "Easy run + strides", detail: "30 min, 4 short strides", effort: "easy" },
    { day: "SAT", type: "strength", title: "Strength B", detail: "Lower body + glutes", effort: "medium" },
    { day: "SUN", type: "ride", title: "Long easy ride", detail: "60-90 min", effort: "easy" },
  ],

  // Strength sessions. Each exercise: name, optional qualifier, rest, wk1–4 and wk5–11 prescription.
  strength: [
    {
      day: "WEDNESDAY",
      title: "Strength A",
      focus: ["Upper body", "and trunk"],
      exercises: [
        { name: "Bent-over bar row", rest: "75 s rest", early: "3×10-12", late: "4×8-10 · 1 s pause at chest" },
        { name: "Bench press", note: "flat step bench", rest: "75 s rest", early: "3×10-12", late: "4×8-10 · 3 s lowering" },
        { name: "Standing overhead press", rest: "75 s rest", early: "3×10", late: "3×8-10" },
        { name: "Good morning", note: "light", rest: "60 s rest", early: "2×12", late: "3×10 · 3 s lowering" },
        { name: "Bar curl + triceps extension", note: "superset", rest: "60 s rest", early: "2×12", late: "3×10-12" },
        { name: "Plank, side plank, dead bug", rest: "45 s rest", early: "3×30-45 s, 2×25 s/side, 2×8/side", late: "3×45-60 s, 3×35 s/side, 3×10/side" },
      ],
      footer: "Keep good mornings light: Thursday is a Sprint.",
    },
    {
      day: "SATURDAY",
      title: "Strength B",
      focus: ["Lower body", "and glutes"],
      exercises: [
        { name: "Back squat", rest: "90 s rest", early: "3×12", late: "4×10-12 · 3 s lowering, 1 s pause at bottom" },
        { name: "Bulgarian split squat", note: "rear foot on step", rest: "90 s rest", early: "3×8-10 each leg", late: "3×8-10 each leg · 3 s lowering, add load first" },
        { name: "Hip thrust", note: "shoulders on step bench", rest: "75 s rest", early: "3×12", late: "4×10-12 · 2 s squeeze at top; single-leg when easy" },
        { name: "Single-leg Romanian deadlift", rest: "75 s rest", early: "3×8 each leg", late: "3×10 each leg · two-leg version if balance limits" },
        { name: "Slow step-downs", note: "off the step bench", rest: "60 s rest", early: "3×8 each leg", late: "3×10 each leg · 3 s lowering" },
        { name: "Calf raises", note: "step edge", rest: "45 s rest", early: "3×15", late: "3×10-12 single-leg · 1 s pause at top" },
      ],
      footer: "Short on time? Keep the step-downs and calf raises.",
    },
  ],

  notes: [
    { title: "Sprint class", days: "TUE · THU", type: "sprint", items: [
      "Your two hard bike days.",
      "Class intervals carry all the bike intensity: no extra threshold rides.",
      "Feeling flat? Cut run quality first.",
    ] },
    { title: "Easy runs", days: "MON · FRI", type: "run", items: [
      "Mon: 30-35 min, easy pace.",
      "Fri: 30 min + 4 short strides.",
      "From wk 5: add a 15-20 min tempo block to Fri.",
      "Wk 9-11: Fri = 5×1000 m at 5k effort.",
    ] },
    { title: "Long ride", days: "SUN", type: "ride", items: [
      "60-90 min easy: heart rate 141-158 bpm.",
      "Follows Saturday's legs, so keep it easy.",
      "From wk 5, alternate with a long run (6-10 km).",
    ] },
  ],
};
