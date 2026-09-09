import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="vr-footer">
      <div className="vr-container vr-footer-inner">
        <Link
          to="/"
          className="vr-brand"
          style={{ textDecoration: "none" }}
        >
          <div className="vr-brand-text">
            <div
              className="vr-brand-name"
              style={{ fontSize: "17px" }}
            >
              Veri<span>Review</span>
            </div>

            <div className="vr-brand-subtitle">
              AI SOFTWARE ENGINEERING
            </div>
          </div>
        </Link>

        <div className="vr-footer-text">
          © {new Date().getFullYear()}{" "}
          <span className="vr-footer-brand">
            VeriReview
          </span>
          . AI Software Engineering Platform.
        </div>
      </div>
    </footer>
  );
}