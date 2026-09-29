import React, { useEffect, useState, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import Login from "./components/Login";
import POS from "./components/POS";
import Analytics from "./components/Analytics";
import CameraMonitor from "./components/CameraMonitor";
import InventoryManagement from "./components/InventoryManagement";
import UserManagement from "./components/UserManagement";

const POLL_MS = 5000; // matches config.DASHBOARD_POLL_SECONDS

async function getJSON(path, token = null) {
  const headers = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  const res = await fetch(path, { headers });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function timeAgo(iso) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso + "Z")) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [stock, setStock] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [burnSeries, setBurnSeries] = useState([]);
  const [forecast, setForecast] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [connected, setConnected] = useState(true);
  const [activeView, setActiveView] = useState("home");
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [initError, setInitError] = useState(null);
  const [viewHistory, setViewHistory] = useState(["home"]);

  // Check for existing session on load
  useEffect(() => {
    console.log('App initializing...');
    try {
      const savedToken = localStorage.getItem('token');
      const savedUser = localStorage.getItem('user');
      console.log('Saved token:', savedToken ? 'exists' : 'none');
      console.log('Saved user:', savedUser ? 'exists' : 'none');
      
      if (savedToken && savedUser) {
        try {
          const parsedUser = JSON.parse(savedUser);
          console.log('Parsed user:', parsedUser);
          setToken(savedToken);
          setUser(parsedUser);
        } catch (parseError) {
          console.error('Error parsing user:', parseError);
          localStorage.removeItem('token');
          localStorage.removeItem('user');
        }
      }
      setInitialized(true);
      console.log('App initialized');
    } catch (error) {
      console.error('Error loading session:', error);
      setInitError('Failed to load session. Please clear your browser data.');
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      setInitialized(true);
    }
  }, []);

  const handleLogin = (userData) => {
    console.log('Login successful:', userData);
    setUser(userData);
    const savedToken = localStorage.getItem('token');
    console.log('Token saved:', savedToken ? 'yes' : 'no');
    setToken(savedToken);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setUser(null);
    setToken(null);
    setActiveView("home");
    setViewHistory(["home"]);
  };

  const handleViewChange = (newView) => {
    if (newView !== activeView) {
      setViewHistory([...viewHistory, newView]);
      setActiveView(newView);
    }
  };

  const handleBack = () => {
    if (viewHistory.length > 1) {
      const newHistory = [...viewHistory];
      newHistory.pop();
      const previousView = newHistory[newHistory.length - 1];
      setViewHistory(newHistory);
      setActiveView(previousView);
    }
  };

  // These hooks must always be called in the same order
  const refresh = useCallback(async () => {
    if (!token) return;
    console.log('Refreshing data...');
    try {
      const [stockData, alertData, suggestData] = await Promise.all([
        getJSON("/api/stock", token).catch(e => { console.error('Stock API error:', e); return []; }),
        getJSON("/api/alerts", token).catch(e => { console.error('Alerts API error:', e); return []; }),
        getJSON("/api/restock-suggestions", token).catch(e => { console.error('Suggestions API error:', e); return []; }),
      ]);
      console.log('Data refreshed:', { stockData: stockData.length, alertData: alertData.length, suggestData: suggestData.length });
      setStock(stockData);
      setAlerts(alertData);
      setSuggestions(suggestData);
      setLastUpdated(new Date());
      setConnected(true);
      // Use functional update to avoid dependency on selected
      setSelected(prevSelected => prevSelected || (stockData.length > 0 ? stockData[0].product_id : null));
    } catch (err) {
      console.error('Refresh error:', err);
      setConnected(false);
    }
  }, [token]);

  useEffect(() => {
    if (!user || !token) return;
    console.log('Setting up refresh interval');
    setLoading(true);
    refresh()
      .then(() => {
        console.log('Initial refresh completed');
        setLoading(false);
      })
      .catch(e => {
        console.error('Initial refresh failed:', e);
        setLoading(false);
      });
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh, user, token]);

  useEffect(() => {
    if (!selected || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const [series, cmp] = await Promise.all([
          getJSON(`/api/burn-rate/${selected}`, token).catch(e => { console.error('Burn rate API error:', e); return []; }),
          getJSON(`/api/forecast-comparison/${selected}`, token).catch(e => { console.error('Forecast API error:', e); return null; }),
        ]);
        if (!cancelled) {
          setBurnSeries(series);
          setForecast(cmp);
        }
      } catch (err) {
        console.error('Detail view error:', err);
      }
    })();
    return () => { cancelled = true; };
  }, [selected, token]);

  const selectedLabel = stock.find((s) => s.product_id === selected)?.label;

  // Conditional rendering after all hooks
  if (!initialized) {
    console.log('Showing loading state');
    return (
      <div className="loading-container">
        <div className="loading-spinner">Initializing...</div>
      </div>
    );
  }

  if (initError) {
    console.log('Showing error state:', initError);
    return (
      <div className="loading-container">
        <div className="error-message">{initError}</div>
        <button 
          className="login-button" 
          onClick={() => {
            localStorage.clear();
            window.location.reload();
          }}
          style={{ marginTop: '20px' }}
        >
          Clear Data and Reload
        </button>
      </div>
    );
  }

  if (!user) {
    console.log('Showing login form');
    return <Login onLogin={handleLogin} />;
  }

  console.log('Showing dashboard for user:', user.username);

  // Render different views based on activeView
  if (activeView === "pos") {
    console.log('Rendering POS view');
    return <POS user={user} onBack={handleBack} canGoBack={viewHistory.length > 1} />;
  }

  if (activeView === "analytics") {
    console.log('Rendering Analytics view');
    return <Analytics user={user} onBack={handleBack} canGoBack={viewHistory.length > 1} />;
  }

  if (activeView === "camera") {
    console.log('Rendering camera view');
    return <CameraMonitor user={user} onBack={handleBack} canGoBack={viewHistory.length > 1} />;
  }

  if (activeView === "inventory") {
    console.log('Rendering inventory management view');
    return <InventoryManagement user={user} onBack={handleBack} canGoBack={viewHistory.length > 1} />;
  }

  if (activeView === "team") {
    return <UserManagement user={user} onBack={handleBack} canGoBack={viewHistory.length > 1} />;
  }

  if (loading) {
    console.log('Rendering loading state');
    return (
      <div className="loading-container">
        <div className="loading-spinner">Loading dashboard...</div>
      </div>
    );
  }

  console.log('Rendering main dashboard');

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><span className="brand-icon">Q</span><span>LedgerLens</span></div>
        <div className="workspace-label">Operations</div>
        <nav className="nav-list">
          <button className={activeView === "home" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("home")}>Overview</button>
          <button className={activeView === "pos" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("pos")}>POS Terminal</button>
          <button className={activeView === "inventory" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("inventory")}>Inventory</button>
          <button className={activeView === "camera" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("camera")}>Camera Monitor</button>
          <button className={activeView === "analytics" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("analytics")}>Analytics</button>
          {(user.role === 'admin' || user.role === 'manager') && <button className={activeView === "team" ? "nav-item active" : "nav-item"} onClick={() => handleViewChange("team")}>Team & Permissions</button>}
        </nav>
        <div className="sidebar-foot">
          <div className="user-info">
            <span className="user-name">{user.full_name}</span>
            <span className="user-role">{user.role}</span>
          </div>
          <button className="logout-button" onClick={handleLogout}>Logout</button>
        </div>
      </aside>

      <main className="app">
        <header className="header">
          <div>
            <div className="eyebrow">Business overview</div>
            <h1>Good afternoon, {user.full_name.split(' ')[0]}</h1>
            <div className="sub">Your inventory and shelf intelligence at a glance.</div>
          </div>
          <div className="header-actions">
            <div className="status-pill">
              <span className={`status-dot ${connected ? "" : "stale"}`} />
              {connected ? `Updated ${lastUpdated ? timeAgo(lastUpdated.toISOString()) : "—"}` : "Connection lost — retrying"}
            </div>
          </div>
        </header>

        <section className="quick-kpis">
          <div className="kpi-card"><span>Total items</span><strong>{stock.reduce((sum, item) => sum + item.current_stock, 0)}</strong><small>Across monitored shelves</small></div>
          <div className="kpi-card"><span>Products tracked</span><strong>{stock.length}</strong><small>Live detection regions</small></div>
          <div className="kpi-card"><span>Reorder attention</span><strong className={stock.filter(item => item.status === "CRITICAL").length ? "danger-number" : ""}>{suggestions.length}</strong><small>{stock.filter(item => item.status === "CRITICAL").length ? "Critical items" : "No critical items"}</small></div>
          <div className="kpi-card"><span>Data sync</span><strong className="good-number">5s</strong><small>Automatic refresh</small></div>
        </section>

        <section className="shelf-grid">
          {stock.map((item) => (
            <div
              key={item.product_id}
              className={`shelf-card ${item.status} ${selected === item.product_id ? "selected" : ""}`}
              onClick={() => setSelected(item.product_id)}
            >
              <div className="label">{item.label}</div>
              <div>
                <span className="count">{item.current_stock}</span>
                <span className="count-unit">units on shelf</span>
              </div>
              <div className="meta">
                <span>{item.burn_rate_per_day ? `${item.burn_rate_per_day}/day` : "no sales yet"}</span>
                <span className={`badge ${item.status}`}>{item.status}</span>
              </div>
            </div>
          ))}
          {stock.length === 0 && <div className="empty-note">Waiting for the first detection cycle…</div>}
        </section>

        <section className="row">
          <div className="panel">
            <h2>{selectedLabel ? `${selectedLabel} — daily units sold` : "Burn rate"}</h2>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={burnSeries} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#D7D9CC" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#57604F" }} tickLine={false} axisLine={{ stroke: "#D7D9CC" }} />
                <YAxis tick={{ fontSize: 11, fill: "#57604F" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #D7D9CC" }} />
                <Line type="monotone" dataKey="units_sold" stroke="#2F6D4F" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>

            {forecast && (
              <div className="forecast-row">
                <div>
                  <div className="figure">{forecast.moving_average.burn_rate_per_day}/day</div>
                  <div className="figure-label">Moving average (7-day)</div>
                </div>
                <div>
                  <div className="figure">
                    {forecast.lstm.predicted_units_sold ?? "—"}
                    {forecast.lstm.predicted_units_sold != null && "/day"}
                  </div>
                  <div className="figure-label">
                    {forecast.lstm.note ? forecast.lstm.note : "LSTM (comparison model)"}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Recent alerts</h2>
            {alerts.length === 0 && <div className="empty-note">No alerts yet — all shelves healthy.</div>}
            <ul className="alert-list">
              {alerts.map((a) => (
                <li key={a.id} className={`alert-item ${a.level}`}>
                  <div className="msg">{a.message}</div>
                  <div className="time">{timeAgo(a.timestamp)}</div>
                  {a.level === "CRITICAL" && (
                    <div className="sms-tag">{a.sms_sent ? "SMS dispatched" : "SMS suppressed (cooldown)"}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="panel">
          <h2>Restock suggestions</h2>
          {suggestions.length === 0 ? (
            <div className="empty-note">Not enough sales history yet to suggest restocks.</div>
          ) : (
            <table className="restock">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Days remaining</th>
                  <th>Projected depletion</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {suggestions.map((s) => (
                  <tr key={s.product_id}>
                    <td>{s.label}</td>
                    <td>{s.days_remaining}</td>
                    <td>{s.depletion_date}</td>
                    <td>
                      <span className={`action-tag ${s.suggested_action === "Reorder soon" ? "soon" : "monitor"}`}>
                        {s.suggested_action}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
