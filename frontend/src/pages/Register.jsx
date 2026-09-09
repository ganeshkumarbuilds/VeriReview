import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";




export default function Register() {
  const navigate = useNavigate();
  const { register } = useAuth();

  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const [error, setError] = useState("");

  const handleChange = (event) => {
    const { name, value } = event.target;

    setFormData((previous) => ({
      ...previous,
      [name]: value,
    }));

    if (error) {
      setError("");
    }
  };

  const handleSubmit = (event) => {
    event.preventDefault();

    if (
      !formData.name.trim() ||
      !formData.email.trim() ||
      !formData.password.trim() ||
      !formData.confirmPassword.trim()
    ) {
      setError("Please complete all fields.");
      return;
    }

    if (formData.password.length < 6) {
      setError("Password must contain at least 6 characters.");
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    /*
     * Local demo auth (AuthContext + localStorage).
     * Backend user accounts can replace this later.
     */
    register(formData.name.trim(), formData.email.trim());
    navigate("/dashboard");
  };

  return (
    <div className="vr-page">
      <main
        className="vr-auth-page"
        style={{
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Background glow */}
        <div
          style={{
            position: "absolute",
            width: "520px",
            height: "520px",
            top: "-240px",
            left: "50%",
            transform: "translateX(-50%)",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(99,102,241,.14), transparent 68%)",
            filter: "blur(25px)",
            pointerEvents: "none",
          }}
        />

        <div
          style={{
            position: "absolute",
            width: "360px",
            height: "360px",
            bottom: "-180px",
            right: "-120px",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(139,92,246,.09), transparent 70%)",
            filter: "blur(25px)",
            pointerEvents: "none",
          }}
        />

        <div
          className="vr-auth-card"
          style={{
            maxWidth: "480px",
          }}
        >
          {/* Logo */}
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              marginBottom: "22px",
            }}
          >
            <div
              className="vr-brand-mark"
              style={{
                width: "52px",
                height: "52px",
                borderRadius: "15px",
                fontWeight: 800,
                fontSize: "20px",
              }}
            >
              VR
            </div>
          </div>

          {/* Heading */}
          <div
            style={{
              textAlign: "center",
              marginBottom: "28px",
            }}
          >
            <div
              className="vr-section-label"
              style={{
                justifyContent: "center",
                marginBottom: "10px",
              }}
            >
              
              Join VeriReview
            </div>

            <h1
              style={{
                margin: "0 0 10px",
                color: "#f8fafc",
                fontSize: "30px",
                lineHeight: 1.2,
                letterSpacing: "-.025em",
              }}
            >
              Create your workspace
            </h1>

            <p
              style={{
                margin: 0,
                color: "#64748b",
                fontSize: "14px",
                lineHeight: 1.6,
              }}
            >
              Build software with an AI engineering team that
              verifies its own work.
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit}>
            <div className="vr-input-group">
              <label
                htmlFor="name"
                className="vr-input-label"
              >
                Full name
              </label>

              <input
                id="name"
                name="name"
                type="text"
                autoComplete="name"
                value={formData.name}
                onChange={handleChange}
                className="vr-input"
                placeholder="Your name"
              />
            </div>

            <div className="vr-input-group">
              <label
                htmlFor="email"
                className="vr-input-label"
              >
                Email address
              </label>

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
              <label
                htmlFor="password"
                className="vr-input-label"
              >
                Password
              </label>

              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                value={formData.password}
                onChange={handleChange}
                className="vr-input"
                placeholder="At least 6 characters"
              />
            </div>

            <div className="vr-input-group">
              <label
                htmlFor="confirmPassword"
                className="vr-input-label"
              >
                Confirm password
              </label>

              <input
                id="confirmPassword"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                value={formData.confirmPassword}
                onChange={handleChange}
                className="vr-input"
                placeholder="Repeat your password"
              />
            </div>

            {error && (
              <div
                role="alert"
                style={{
                  marginBottom: "16px",
                  padding: "11px 13px",
                  borderRadius: "10px",
                  border:
                    "1px solid rgba(248,113,113,.2)",
                  background:
                    "rgba(248,113,113,.07)",
                  color: "#fca5a5",
                  fontSize: "12px",
                  lineHeight: 1.5,
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              className="vr-button vr-button-primary"
              style={{
                width: "100%",
                justifyContent: "center",
                marginTop: "4px",
              }}
            >
              Create workspace
              
            </button>
          </form>

          {/* Benefits */}
          <div
            style={{
              display: "grid",
              gap: "9px",
              marginTop: "22px",
              padding: "15px",
              borderRadius: "12px",
              background: "rgba(255,255,255,.025)",
              border:
                "1px solid rgba(255,255,255,.055)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "9px",
                color: "#94a3b8",
                fontSize: "12px",
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  width: "18px",
                  height: "18px",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: "50%",
                  background: "rgba(99,102,241,.12)",
                  color: "#818cf8",
                }}
              >
                
              </span>
              Autonomous software engineering workflows
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "9px",
                color: "#94a3b8",
                fontSize: "12px",
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  width: "18px",
                  height: "18px",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: "50%",
                  background: "rgba(99,102,241,.12)",
                  color: "#818cf8",
                }}
              >
                
              </span>
              Continuous verification and code review
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "9px",
                color: "#94a3b8",
                fontSize: "12px",
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  width: "18px",
                  height: "18px",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: "50%",
                  background: "rgba(99,102,241,.12)",
                  color: "#818cf8",
                }}
              >
                
              </span>
              AI-assisted fixing and re-verification
            </div>
          </div>

          {/* Login */}
          <div
            style={{
              marginTop: "22px",
              paddingTop: "20px",
              borderTop:
                "1px solid rgba(255,255,255,.06)",
              textAlign: "center",
              color: "#64748b",
              fontSize: "13px",
            }}
          >
            Already have an account?{" "}
            <Link
              to="/login"
              style={{
                color: "#a5b4fc",
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Sign in
            </Link>
          </div>

          {/* Security note */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "7px",
              marginTop: "20px",
              color: "#475569",
              fontSize: "11px",
            }}
          >
            
            Your engineering workspace stays protected
          </div>
        </div>
      </main>
    </div>
  );
}