import React, { useState, useEffect } from 'react';

export default function InventoryManagement({ user, onBack, canGoBack }) {
  const [products, setProducts] = useState([]);
  const [stock, setStock] = useState([]);
  const [editingProduct, setEditingProduct] = useState(null);
  const [editValues, setEditValues] = useState({});
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [notice, setNotice] = useState('');
  const [receipt, setReceipt] = useState({ product_id: '', quantity: 1, note: '' });
  const [newProduct, setNewProduct] = useState({
    product_id: '',
    name: '',
    description: '',
    price: '',
    category: '',
    sku: '',
    barcode: '',
    initial_stock: 0
  });

  useEffect(() => {
    fetchProducts();
    fetchStock();
  }, []);

  const fetchProducts = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/products', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error('Could not load products');
      const data = await response.json();
      setProducts(data);
    } catch (err) {
      console.error('Failed to fetch products:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStock = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/stock', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error('Could not load stock');
      const data = await response.json();
      setStock(data);
    } catch (err) {
      console.error('Failed to fetch stock:', err);
    }
  };

  const handleEdit = (productId) => {
    const product = products.find(p => p.product_id === productId);
    const stockItem = stock.find(s => s.product_id === productId);
    setEditingProduct(productId);
    setEditValues({
      ...product,
      current_stock: stockItem?.current_stock || 0
    });
  };

  const handleSave = async () => {
    try {
      const token = localStorage.getItem('token');
      
      const productResponse = await fetch(`/api/products/${editingProduct}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: editValues.name,
          description: editValues.description,
          price: parseFloat(editValues.price),
          category: editValues.category,
          sku: editValues.sku,
          barcode: editValues.barcode
        })
      });
      const productResult = await productResponse.json();
      if (!productResponse.ok) throw new Error(productResult.error || 'Could not save product');

      await fetchProducts();
      if (Number(editValues.current_stock) !== Number(getProductStock(editingProduct))) {
        const response = await fetch(`/api/inventory/${editingProduct}/count`, {
          method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ count: Number(editValues.current_stock), note: 'Inventory count correction' })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save stock count');
      }
      await fetchStock();
      setNotice('Product and stock count saved.');
      setEditingProduct(null);
      setEditValues({});
    } catch (err) {
      console.error('Failed to save product:', err);
      alert('Failed to save product');
    }
  };

  const receiveStock = async (productId = receipt.product_id, quantity = receipt.quantity, note = receipt.note) => {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/inventory/receive', {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, quantity: Number(quantity), note, source: 'manual' })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Failed to receive stock');
    await fetchStock();
    return result;
  };

  const handleManualReceipt = async () => {
    try { await receiveStock(); setReceipt({ product_id: '', quantity: 1, note: '' }); }
    catch (err) { alert(err.message); }
  };

  const handleCancel = () => {
    setEditingProduct(null);
    setEditValues({});
  };

  const handleAddProduct = async () => {
    try {
      const token = localStorage.getItem('token');
      
      const response = await fetch('/api/products', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(newProduct)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not add product');

      await fetchProducts();
      await fetchStock();
      setNotice(`${newProduct.name} was added to inventory.`);
      setShowAddModal(false);
      setNewProduct({
        product_id: '',
        name: '',
        description: '',
        price: '',
        category: '',
        sku: '',
        barcode: '', initial_stock: 0
      });
    } catch (err) {
      console.error('Failed to add product:', err);
      alert('Failed to add product');
    }
  };

  const filteredProducts = products.filter(p => 
    p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.product_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (p.sku && p.sku.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const getProductStock = (productId) => {
    return stock.find(s => s.product_id === productId)?.current_stock || 0;
  };

  const getProductStatus = (productId) => {
    const stockItem = stock.find(s => s.product_id === productId);
    if (!stockItem) return 'unknown';
    return stockItem.status;
  };

  return (
    <div className="inventory-container">
      <div className="inventory-header">
        <div className="header-left">
          {canGoBack && (
            <button className="back-button" onClick={onBack}>
              ← Back
            </button>
          )}
          <h2>Inventory Management</h2>
          <span className="user-badge">{user.full_name} ({user.role})</span>
        </div>
        <div className="header-right">
          <input
            type="text"
            placeholder="Search products..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="search-input"
          />
          {(user.role === 'manager' || user.role === 'admin') && (
            <button 
              className="add-product-button"
              onClick={() => setShowAddModal(true)}
            >
              + Add Product
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="loading">Loading inventory...</div>
      ) : (
        <div className="inventory-table-container">
          <table className="inventory-table">
            <thead>
              <tr>
                <th>Product ID</th>
                <th>Name</th>
                <th>SKU</th>
                <th>Category</th>
                <th>Price</th>
                <th>Current Stock</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredProducts.map((product) => (
                <tr key={product.product_id} className={editingProduct === product.product_id ? 'editing' : ''}>
                  {editingProduct === product.product_id ? (
                    <>
                      <td>
                        <input
                          type="text"
                          value={editValues.product_id}
                          onChange={(e) => setEditValues({...editValues, product_id: e.target.value})}
                          disabled
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editValues.name}
                          onChange={(e) => setEditValues({...editValues, name: e.target.value})}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editValues.sku || ''}
                          onChange={(e) => setEditValues({...editValues, sku: e.target.value})}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editValues.category || ''}
                          onChange={(e) => setEditValues({...editValues, category: e.target.value})}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          step="0.01"
                          value={editValues.price}
                          onChange={(e) => setEditValues({...editValues, price: e.target.value})}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={editValues.current_stock}
                          onChange={(e) => setEditValues({...editValues, current_stock: parseInt(e.target.value)})}
                        />
                      </td>
                      <td>
                        <span className={`status-badge ${getProductStatus(product.product_id)}`}>
                          {getProductStatus(product.product_id)}
                        </span>
                      </td>
                      <td>
                        <button className="save-button" onClick={handleSave}>Save</button>
                        <button className="cancel-button" onClick={handleCancel}>Cancel</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{product.product_id}</td>
                      <td>{product.name}</td>
                      <td>{product.sku || '-'}</td>
                      <td>{product.category || '-'}</td>
                      <td>${parseFloat(product.price).toFixed(2)}</td>
                      <td>
                        <span className={`stock-count ${getProductStatus(product.product_id)}`}>
                          {getProductStock(product.product_id)}
                        </span>
                      </td>
                      <td>
                        <span className={`status-badge ${getProductStatus(product.product_id)}`}>
                          {getProductStatus(product.product_id)}
                        </span>
                      </td>
                      <td>{(user.role === 'admin' || user.role === 'manager') && <button 
                        className="edit-button"
                        onClick={() => handleEdit(product.product_id)}
                      >
                        Edit
                      </button>}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          
          {filteredProducts.length === 0 && (
            <div className="no-results">
              <div className="no-data-icon">📦</div>
              <div>No products found</div>
              <div className="no-data-subtext">
                {searchTerm ? 'Try a different search term' : 'Add products to get started'}
              </div>
            </div>
          )}
        </div>
      )}
      {notice && <div className="success-message">{notice}</div>}

      {(user.role === 'admin' || user.role === 'manager' || user.role === 'sales' || user.role === 'sales_person') && (
        <section className="manual-receipt">
          <h3>Manual stock receipt</h3>
          <p>Use this if the camera cannot identify the item.</p>
          <select value={receipt.product_id} onChange={e => setReceipt({ ...receipt, product_id: e.target.value })}>
            <option value="">Choose product</option>{products.map(p => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}
          </select>
          <input type="number" min="1" value={receipt.quantity} onChange={e => setReceipt({ ...receipt, quantity: e.target.value })} />
          <input placeholder="Receipt note (optional)" value={receipt.note} onChange={e => setReceipt({ ...receipt, note: e.target.value })} />
          <button className="save-button" disabled={!receipt.product_id} onClick={handleManualReceipt}>Add stock</button>
        </section>
      )}

      {showAddModal && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h3>Add New Product</h3>
              <button className="close-button" onClick={() => setShowAddModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Product ID *</label>
                <input
                  type="text"
                  value={newProduct.product_id}
                  onChange={(e) => setNewProduct({...newProduct, product_id: e.target.value})}
                  placeholder="e.g., sugar_2kg"
                />
              </div>
              <div className="form-group">
                <label>Name *</label>
                <input
                  type="text"
                  value={newProduct.name}
                  onChange={(e) => setNewProduct({...newProduct, name: e.target.value})}
                  placeholder="Product name"
                />
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea
                  value={newProduct.description}
                  onChange={(e) => setNewProduct({...newProduct, description: e.target.value})}
                  placeholder="Product description"
                  rows="3"
                />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Price *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={newProduct.price}
                    onChange={(e) => setNewProduct({...newProduct, price: e.target.value})}
                    placeholder="0.00"
                  />
                </div>
                <div className="form-group">
                  <label>Category</label>
                  <input
                    type="text"
                    value={newProduct.category}
                    onChange={(e) => setNewProduct({...newProduct, category: e.target.value})}
                    placeholder="e.g., Pantry"
                  />
                </div>
              </div>
              <div className="form-group">
                <label>Opening stock</label>
                <input type="number" min="0" value={newProduct.initial_stock} onChange={(e) => setNewProduct({...newProduct, initial_stock: e.target.value})} />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>SKU</label>
                  <input
                    type="text"
                    value={newProduct.sku}
                    onChange={(e) => setNewProduct({...newProduct, sku: e.target.value})}
                    placeholder="e.g., SUG-002KG"
                  />
                </div>
                <div className="form-group">
                  <label>Barcode</label>
                  <input
                    type="text"
                    value={newProduct.barcode}
                    onChange={(e) => setNewProduct({...newProduct, barcode: e.target.value})}
                    placeholder="e.g., 1234567890123"
                  />
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="cancel-button" onClick={() => setShowAddModal(false)}>Cancel</button>
              <button className="save-button" onClick={handleAddProduct}>Add Product</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
