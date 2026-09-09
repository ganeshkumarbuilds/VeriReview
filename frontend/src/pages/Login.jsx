import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";


export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [error, setError] = useState("");

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (error) setError("");
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!formData.email.trim() || !formData.password.trim()) {
      setError("Please enter your email and password.");
      return;
    }
    login(formData.email.trim());
    navigate("/dashboard");
  };

  return (
    <div className="vr-page">
      <main className="vr-auth-page">
        <div className="vr-auth-card">
          <div style={{ display: "flex", justifyContent: "center", marginBottom: "22px" }}>
            <div className="vr-brand-mark" style={{ width: "52px", height: "52px", borderRadius: "15px", fontWeight: 800, fontSize: "20px" }}>
              VR
            </div>
          </div>

          <div style={{ textAlign: "center", marginBottom: "28px" }}>
            <div className="vr-section-label" style={{ justifyContent: "center", marginBottom: "10px" }}>
              Welcome back
            </div>
            <h1 style={{ margin: "0 0 10px", color: "#f8fafc", fontSize: "30px", letterSpacing: "-.025em" }}>
              Sign in to VeriReview
            </h1>
            <p style={{ margin: 0, color: "#64748b", fontSize: "14px", lineHeight: 1.6 }}>
              Access your agent workspace, reviews and history.
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="vr-input-group">
              <label htmlFor="email" className="vr-input-label">Email address</label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                value={formData.email}
                onChange={handleChange}
                className="vr-input"
                placeholder="you@example.com"
              />
            </div>

            <div className="vr-input-group">
              <label htmlFor="password" className="vr-input-label">Password</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={formData.password}
                onChange={handleChange}
                className="vr-input"
                placeholder="Your password"
              />
            </div>

            {error && (
              <div
                role="alert"
                style={{
                  marginBottom: "16px",
                  padding: "11px 13px",
                  borderRadius: "10px",
                  border: "1px solid rgba(248,113,113,.2)",
                  background: "rgba(248,113,113,.07)",
                  color: "#fca5a5",
                  fontSize: "12px",
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              className="vr-button vr-button-primary"
              style={{ width: "100%", justifyContent: "center", marginTop: "4px" }}
            >
              Sign in
            </button>
          </form>

          <div
            style={{
              marginTop: "22px",
              paddingTop: "20px",
              borderTop: "1px solid rgba(255,255,255,.06)",
              textAlign: "center",
              color: "#64748b",
              fontSize: "13px",
            }}
          >
            New to VeriReview?{" "}
            <Link to="/register" style={{ color: "#a5b4fc", fontWeight: 600, textDecoration: "none" }}>
              Create an account
            </Link>
          </div>

          <div style={{ marginTop: "16px", textAlign: "center" }}>
            <Link to="/" style={{ color: "#475569", fontSize: "12px" }}>
              ← Back to home
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
