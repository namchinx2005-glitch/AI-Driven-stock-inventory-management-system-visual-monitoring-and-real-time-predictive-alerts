import React, { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend
} from 'recharts';

// Claymorphism chart palette: soft, saturated pastels
const COLORS = ['#6C5CE7', '#4FD1A5', '#FFB48A', '#7CC4FF', '#FF8FA3', '#FFD66B'];
const GRID = '#D9DCF3';
const TICK = { fontSize: 12, fill: '#656989', fontWeight: 600 };
const TOOLTIP_STYLE = {
  background: '#F5F6FF',
  border: 'none',
  borderRadius: 16,
  boxShadow: '6px 6px 16px rgba(122, 128, 184, 0.35), -4px -4px 12px rgba(255, 255, 255, 0.9)',
  fontSize: 12,
  fontWeight: 700,
  color: '#2B2D4A',
};

export default function Analytics({ user, onBack, canGoBack }) {
  const [mostPurchased, setMostPurchased] = useState([]);
  const [salesByCategory, setSalesByCategory] = useState([]);
  const [dailyRevenue, setDailyRevenue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(30);

  useEffect(() => {
    fetchAnalytics();
  }, [timeRange]);

  const fetchAnalytics = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      
      const [purchasedRes, categoryRes, revenueRes] = await Promise.all([
        fetch(`/api/analytics/most-purchased?days=${timeRange}&limit=10`, {
          headers: { 'Authorization': `Bearer ${token}` }
        }),
        fetch(`/api/analytics/sales-by-category?days=${timeRange}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        }),
        fetch(`/api/analytics/daily-revenue?days=${timeRange}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        })
      ]);

      const purchasedData = await purchasedRes.json();
      const categoryData = await categoryRes.json();
      const revenueData = await revenueRes.json();

      setMostPurchased(purchasedData);
      setSalesByCategory(categoryData);
      setDailyRevenue(revenueData);
    } catch (err) {
      console.error('Failed to fetch analytics:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading">Loading analytics...</div>;
  }

  return (
    <div className="analytics-container">
      <div className="analytics-header">
        <div className="header-left">
          {canGoBack && (
            <button className="back-button" onClick={onBack}>
              ← Back
            </button>
          )}
          <h2>Sales Analytics</h2>
          <span className="user-badge">{user.full_name} ({user.role})</span>
        </div>
        <div className="header-right">
          <div className="time-range-selector">
            <label>Time Range:</label>
            <select value={timeRange} onChange={(e) => setTimeRange(parseInt(e.target.value))}>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>
        </div>
      </div>

      <div className="analytics-grid">
        {/* Most Purchased Products */}
        <div className="analytics-card">
          <h3>Most Purchased Products</h3>
          {mostPurchased.length === 0 ? (
            <div className="no-data">No data available</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={mostPurchased}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" angle={-45} textAnchor="end" height={100} tick={TICK} tickLine={false} axisLine={{ stroke: GRID }} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(108, 92, 231, 0.08)' }} />
                <Bar dataKey="total_sold" fill="#6C5CE7" radius={[12, 12, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Sales by Category */}
        <div className="analytics-card">
          <h3>Sales by Category</h3>
          {salesByCategory.length === 0 ? (
            <div className="no-data">No data available</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={salesByCategory}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ category, percent }) => `${category} ${(percent * 100).toFixed(0)}%`}
                  outerRadius={80}
                  fill="#6C5CE7"
                  dataKey="total_sold"
                  stroke="#F5F6FF"
                  strokeWidth={4}
                >
                  {salesByCategory.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 12, fontWeight: 700, color: '#656989' }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Daily Revenue */}
        <div className="analytics-card full-width">
          <h3>Daily Revenue</h3>
          {dailyRevenue.length === 0 ? (
            <div className="no-data">No data available</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dailyRevenue}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={TICK} tickLine={false} axisLine={{ stroke: GRID }} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: 'rgba(79, 209, 165, 0.1)' }}
                  formatter={(value) => [`$${value.toFixed(2)}`, 'Revenue']}
                />
                <Bar dataKey="revenue" fill="#4FD1A5" radius={[12, 12, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Top Products Table */}
        <div className="analytics-card full-width">
          <h3>Top Products Details</h3>
          {mostPurchased.length === 0 ? (
            <div className="no-data">No data available</div>
          ) : (
            <table className="analytics-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Total Sold</th>
                  <th>Transactions</th>
                  <th>Avg per Transaction</th>
                </tr>
              </thead>
              <tbody>
                {mostPurchased.map((item, index) => (
                  <tr key={item.product_id}>
                    <td>
                      <span className="rank-badge">{index + 1}</span>
                      {item.name}
                    </td>
                    <td>{item.total_sold}</td>
                    <td>{item.transaction_count}</td>
                    <td>{(item.total_sold / item.transaction_count).toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}