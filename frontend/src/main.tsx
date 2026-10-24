import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/vazirmatn/arabic-400.css";
import "@fontsource/vazirmatn/latin-400.css";
import "@fontsource/vazirmatn/arabic-500.css";
import "@fontsource/vazirmatn/latin-500.css";
import "@fontsource/vazirmatn/arabic-600.css";
import "@fontsource/vazirmatn/latin-600.css";
import "@fontsource/vazirmatn/arabic-700.css";
import "@fontsource/vazirmatn/latin-700.css";
import { App } from "./App";
import { NetworkStatus } from "./components";
import { initializePlatform } from "./platform";
import "./style.css";

class AppBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <main className="auth-loading">
          <section className="panel respond-panel">
            <h1>نمایش صفحه کامل نشد</h1>
            <p role="alert">
              صفحه را دوباره بارگذاری کنید. نتیجهٔ نوبت‌ها و درخواست‌های ثبت‌شده
              در سامانه حفظ می‌شود.
            </p>
            <button
              className="button primary"
              onClick={() => location.reload()}
            >
              بارگذاری دوباره
            </button>
          </section>
        </main>
      );
    return this.props.children;
  }
}

const root = ReactDOM.createRoot(document.getElementById("root")!);
root.render(
  <main className="auth-loading" role="status" aria-live="polite">
    در حال آماده‌سازی هم‌آوا…
  </main>,
);
void initializePlatform().finally(() =>
  root.render(
    <React.StrictMode>
      <AppBoundary>
        <NetworkStatus />
        <App />
      </AppBoundary>
    </React.StrictMode>,
  ),
);
