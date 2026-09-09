import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <header className="vr-navbar">
      <div className="vr-container vr-navbar-inner">
        <Link to="/" className="vr-brand" style={{ textDecoration: "none" }}>
          <div className="vr-brand-text">
            <div className="vr-brand-name">
              Veri<span>Review</span>
            </div>
            <div className="vr-brand-subtitle">AI SOFTWARE ENGINEERING</div>
          </div>
        </Link>

        <nav className="vr-nav-actions">
          {user ? (
            <>
              <Link to="/dashboard" className="vr-nav-link">
                Workspace
              </Link>
              <Link to="/review" className="vr-nav-link">
                Review
              </Link>
              <Link to="/history" className="vr-nav-link">
                History
              </Link>
              <span style={{ color: "#64748b", fontSize: "13px" }}>
                {user.name || user.email}
              </span>
              <button
                type="button"
                onClick={handleLogout}
                className="vr-button vr-button-secondary"
                style={{ minHeight: "40px", padding: "0 16px" }}
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="vr-nav-link">
                Sign in
              </Link>
              <Link to="/register" className="vr-button vr-button-primary">
                Get started
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
