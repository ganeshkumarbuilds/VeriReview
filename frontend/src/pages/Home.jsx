import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";



const WORKFLOW = [
  { n: "01", title: "Plan", desc: "Turn your idea into a precise, buildable product spec with features and user flows." },
  { n: "02", title: "Architect", desc: "Design modules, REST APIs, pages, data model and system boundaries." },
  { n: "03", title: "Build", desc: "Coding Agent generates Spring Boot backend + React frontend from the plan." },
  { n: "04", title: "Test", desc: "Testing Agent generates cases and runs automated structural checks." },
  { n: "05", title: "Verify", desc: "Verified Agent checks the build against your original requirements." },
  { n: "06", title: "Review", desc: "Review Agent scans every file for bugs, security and quality issues." },
  { n: "07", title: "Complete", desc: "PASS → docs + Dockerfile + export. FAIL → Coding Agent fixes, then re-test." },
];

const FEATURES = [
  { title: "Autonomous pipeline", desc: "One task drives Plan → Architect → Build → Test → Verify → Review without manual handoffs." },
  { title: "Requirements verification", desc: "Every build is checked against the task you wrote, not just whether the code compiles." },
  { title: "Deep code review", desc: "Security, error handling, performance and maintainability findings with file locations." },
  { title: "Self-correcting loop", desc: "FAIL routes back to the Coding Agent for fixes, then TEST → VERIFY → REVIEW again (max 2 revisions)." },
  { title: "Full project export", desc: "Get README, Dockerfile, backend Java files and React UI packed as a ZIP." },
  { title: "Run history", desc: "Dashboard, history and stats track every project, finding count and revision." },
];

const STACK = [
  { title: "Frontend", items: ["React 18 + Vite", "React Router", "Tailwind-style VR design system", "WebSocket live agent feed"] },
  { title: "Backend", items: ["FastAPI + WebSocket", "LangGraph agent workflow", "PostgreSQL + SQLAlchemy", "ChromaDB Spring/OWASP knowledge"] },
  { title: "AI", items: ["OpenRouter free models", "Planner / Builder / Tester", "Verifier + Reviewer", "Automatic fallback between models"] },
];

export default function Home() {
  const { user } = useAuth();

  return (
    <div className="vr-page">
      <main>
        {/* HERO */}
        <section className="vr-hero">
          <div className="vr-container">
            <div className="vr-hero-content">
              <div className="vr-eyebrow">
                <span className="vr-eyebrow-dot" />
                VeriReview — Agentic AI Software Engineering
              </div>

              <h1 className="vr-hero-title">
                Describe your software.
                <span className="vr-gradient-text">VeriReview builds &amp; verifies it.</span>
              </h1>

              <p className="vr-hero-description">
                VeriReview is a full-stack AI engineering platform. You write one task in plain
                language — autonomous agents plan it, architect it, build a Spring Boot backend
                and React frontend, test it, verify it against your requirements, review every
                file, fix failures, and package the result for export.
              </p>

              <div className="vr-hero-actions">
                {user ? (
                  <Link to="/dashboard" className="vr-button vr-button-primary">
                    Open workspace
                    
                  </Link>
                ) : (
                  <>
                    <Link to="/register" className="vr-button vr-button-primary">
                      Get started free
                      
                    </Link>
                    <Link to="/login" className="vr-button vr-button-secondary">
                      Sign in
                    </Link>
                  </>
                )}
              </div>

              {!user && (
                <p style={{ marginTop: "18px", color: "#64748b", fontSize: "13px" }}>
                  No setup needed to explore — create an account to start your first agent run.
                </p>
              )}
            </div>
          </div>
        </section>

        {/* WHAT IS */}
        <section className="vr-section">
          <div className="vr-container">
            <div className="vr-section-header">
              <div className="vr-section-label">What is VeriReview?</div>
              <h2 className="vr-section-title">More than code generation</h2>
              <p className="vr-section-description">
                Traditional AI tools stop after writing code. VeriReview wraps generation in an
                engineering control loop: tests must pass, requirements must be met, and review
                findings must be resolved before a project is marked complete.
              </p>
            </div>

            <div className="vr-agent-grid">
              {FEATURES.map((f, i) => (
                <div key={f.title} className="vr-card vr-card-hover">
                  <div className="vr-section-label">0{i + 1}</div>
                  <h3 className="vr-agent-title" style={{ fontSize: "18px" }}>{f.title}</h3>
                  <p className="vr-agent-description">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* WORKFLOW */}
        <section className="vr-section" id="how-it-works">
          <div className="vr-container">
            <div className="vr-section-header">
              <div className="vr-section-label">How it works</div>
              <h2 className="vr-section-title">From task to verified software</h2>
              <p className="vr-section-description">
                USER TASK → PLAN → ARCHITECT → BUILD → TEST → VERIFY → REVIEW →
                PASS / FAIL. On FAIL the Coding Agent applies fixes and the project goes
                through TEST → VERIFY → REVIEW again.
              </p>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
                gap: "12px",
              }}
            >
              {WORKFLOW.map((s) => (
                <div key={s.n} className="vr-card">
                  <div className="vr-section-label">{s.n}</div>
                  <h3 style={{ margin: "8px 0", color: "#f8fafc", fontSize: "16px" }}>{s.title}</h3>
                  <p style={{ margin: 0, color: "#94a3b8", fontSize: "12px", lineHeight: 1.65 }}>{s.desc}</p>
                </div>
              ))}
            </div>

            <div className="vr-card" style={{ marginTop: "16px" }}>
              <div className="vr-section-label">PASS / FAIL gate</div>
              <p style={{ color: "#94a3b8", fontSize: "13px", lineHeight: 1.7, margin: "8px 0 0" }}>
                PASS requires tests green, requirements met, and no high-severity review findings.
                Otherwise the run loops back to the Coding Agent with the test report, verification
                report, and confirmed findings attached — up to 2 revisions.
              </p>
            </div>
          </div>
        </section>

        {/* STACK */}
        <section className="vr-section">
          <div className="vr-container">
            <div className="vr-section-header">
              <div className="vr-section-label">Under the hood</div>
              <h2 className="vr-section-title">Complete project stack</h2>
            </div>
            <div className="vr-agent-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", display: "grid" }}>
              {STACK.map((s) => (
                <div key={s.title} className="vr-card">
                  <div className="vr-section-label">{s.title}</div>
                  <ul style={{ margin: "12px 0 0", paddingLeft: "18px", color: "#94a3b8", fontSize: "13px", lineHeight: 1.8 }}>
                    {s.items.map((i) => (
                      <li key={i}>{i}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* GET STARTED */}
        <section className="vr-section">
          <div className="vr-container">
            <div className="vr-card" style={{ textAlign: "center", padding: "48px 28px" }}>
              <div className="vr-section-label" style={{ justifyContent: "center" }}>Get started</div>
              <h2 className="vr-section-title" style={{ fontSize: "clamp(26px, 4vw, 40px)" }}>
                Create an account to use VeriReview
              </h2>
              <p className="vr-section-description" style={{ marginLeft: "auto", marginRight: "auto" }}>
                1. Register → 2. Sign in → 3. Describe your task in the workspace and watch
                agents build, test, verify and review it.
              </p>
              <div className="vr-hero-actions" style={{ justifyContent: "center" }}>
                {user ? (
                  <Link to="/dashboard" className="vr-button vr-button-primary">
                    Go to workspace 
                  </Link>
                ) : (
                  <>
                    <Link to="/register" className="vr-button vr-button-primary">
                      Create account 
                    </Link>
                    <Link to="/login" className="vr-button vr-button-secondary">
                      I already have an account
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
