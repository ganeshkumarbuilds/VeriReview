import { useEffect, useState } from "react";
import { checkBackendHealth } from "./services/api";

function App() {
  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [backendService, setBackendService] = useState("");

  useEffect(() => {
    async function verifyBackend() {
      try {
        const result = await checkBackendHealth();

        setBackendStatus(result.status);
        setBackendService(result.service);
      } catch {
        setBackendStatus("Disconnected");
        setBackendService("Unable to connect to backend");
      }
    }

    verifyBackend();
  }, []);

  const isConnected = backendStatus === "healthy";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <section className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-10 shadow-sm">

        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600 text-xl font-bold text-white">
            V
          </div>

          <span className="text-xl font-semibold text-slate-900">
            VeriReview
          </span>
        </div>

        <div className="mb-4 inline-flex rounded-full bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
          Development Environment
        </div>

        <h1 className="mb-3 text-3xl font-bold tracking-tight text-slate-900">
          Backend Connection
        </h1>

        <p className="mb-7 text-slate-500">
          Checking communication between the React frontend
          and FastAPI backend.
        </p>

        <div
          className={`rounded-xl border p-5 ${
            isConnected
              ? "border-emerald-200 bg-emerald-50"
              : backendStatus === "Checking..."
                ? "border-blue-200 bg-blue-50"
                : "border-red-200 bg-red-50"
          }`}
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-slate-800">
              Backend Status
            </span>

            <span
              className={`text-sm font-semibold ${
                isConnected
                  ? "text-emerald-700"
                  : backendStatus === "Checking..."
                    ? "text-blue-700"
                    : "text-red-700"
              }`}
            >
              {backendStatus.toUpperCase()}
            </span>
          </div>

          <p className="text-sm text-slate-600">
            {backendService || "Waiting for backend response..."}
          </p>
        </div>

        <div className="mt-6 text-sm text-slate-400">
          Python · FastAPI · React · TypeScript
        </div>

      </section>
    </main>
  );
}

export default App;