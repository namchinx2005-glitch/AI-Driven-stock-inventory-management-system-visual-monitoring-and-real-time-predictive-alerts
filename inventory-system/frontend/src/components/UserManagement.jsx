import React, { useEffect, useState } from 'react';

const ROLES = ['admin', 'manager', 'sales', 'accountant'];

export default function UserManagement({ user, onBack, canGoBack }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ username: '', full_name: '', password: '', role: 'sales' });
  const [message, setMessage] = useState('');
  const token = localStorage.getItem('token');
  const availableRoles = user.role === 'admin' ? ROLES : ROLES.filter(role => role !== 'admin');
  const load = async () => {
    try {
      const response = await fetch('/api/users', { headers: { Authorization: `Bearer ${token}` } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to load users');
      setUsers(Array.isArray(data) ? data : []);
    } catch (error) { setUsers([]); setMessage(error.message); }
  };
  useEffect(() => { load(); }, []);

  const add = async e => {
    e.preventDefault(); setMessage('');
    const response = await fetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify(form) });
    const data = await response.json();
    if (!response.ok) return setMessage(data.error || 'Could not add user');
    setForm({ username: '', full_name: '', password: '', role: 'sales' }); setMessage('User added.'); load();
  };
  const changeRole = async (id, role) => {
    const response = await fetch(`/api/users/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ role }) });
    if (response.ok) load(); else setMessage((await response.json()).error || 'Could not update role');
  };

  return <div className="inventory-container">
    <div className="inventory-header"><div className="header-left">{canGoBack && <button className="back-button" onClick={onBack}>← Back</button>}<h2>Team & permissions</h2><span className="user-badge">{user.full_name}</span></div></div>
    <section className="manual-receipt"><h3>Add team member</h3><form onSubmit={add}>
      <input required placeholder="Full name" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} />
      <input required placeholder="Username" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
      <input required type="password" placeholder="Temporary password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
      <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>{availableRoles.map(role => <option key={role}>{role}</option>)}</select>
      <button className="save-button">Add user</button>
    </form>{message && <p>{message}</p>}</section>
    <div className="inventory-table-container"><table className="inventory-table"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Active</th></tr></thead><tbody>
      {users.map(member => <tr key={member.id}><td>{member.full_name}</td><td>{member.username}</td><td><select value={member.role} onChange={e => changeRole(member.id, e.target.value)}>{(member.role === 'admin' && user.role !== 'admin' ? ['admin', ...availableRoles] : availableRoles).map(role => <option key={role}>{role}</option>)}</select></td><td>{member.is_active ? 'Yes' : 'No'}</td></tr>)}
    </tbody></table></div>
  </div>;
}
