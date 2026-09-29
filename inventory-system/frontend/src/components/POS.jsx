import React, { useState, useEffect } from 'react';

export default function POS({ user, onBack, canGoBack }) {
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [receipt, setReceipt] = useState(null);

  useEffect(() => {
    fetchProducts();
  }, []);

  const fetchProducts = async () => {
    try {
      const response = await fetch('/api/products');
      const data = await response.json();
      setProducts(data);
    } catch (err) {
      setError('Failed to load products');
    } finally {
      setLoading(false);
    }
  };

  const addToCart = (product) => {
    const existingItem = cart.find(item => item.product_id === product.product_id);
    if (existingItem) {
      setCart(cart.map(item =>
        item.product_id === product.product_id
          ? { ...item, quantity: item.quantity + 1 }
          : item
      ));
    } else {
      setCart([...cart, { ...product, quantity: 1 }]);
    }
  };

  const removeFromCart = (product_id) => {
    setCart(cart.filter(item => item.product_id !== product_id));
  };

  const updateQuantity = (product_id, quantity) => {
    if (quantity <= 0) {
      removeFromCart(product_id);
    } else {
      setCart(cart.map(item =>
        item.product_id === product_id
          ? { ...item, quantity }
          : item
      ));
    }
  };

  const calculateTotal = () => {
    return cart.reduce((sum, item) => sum + (item.price * item.quantity), 0).toFixed(2);
  };

  const handleCheckout = async () => {
    if (cart.length === 0) {
      setError('Cart is empty');
      return;
    }

    setProcessing(true);
    setError('');
    setSuccess('');

    try {
      const token = localStorage.getItem('token');
      const items = cart.map(item => ({
        product_id: item.product_id,
        quantity: item.quantity,
        unit_price: item.price
      }));

      const response = await fetch('/api/pos/transaction', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          items,
          total_amount: calculateTotal(),
          payment_method: 'cash'
        }),
      });

      const data = await response.json();

      if (response.ok) {
        setSuccess(`Transaction completed! ID: ${data.transaction_id}`);
        setReceipt({ ...data.receipt, transaction_id: data.transaction_id });
        setCart([]);
      } else {
        setError(data.error || 'Transaction failed');
      }
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setProcessing(false);
    }
  };

  const printReceipt = () => {
    if (!receipt) return;
    const lines = receipt.items.map(item => `<tr><td>${item.product_name}</td><td>${item.quantity} × $${Number(item.unit_price).toFixed(2)}</td><td>$${Number(item.total_price).toFixed(2)}</td></tr>`).join('');
    const popup = window.open('', 'receipt', 'width=420,height=640');
    if (!popup) return setError('Allow pop-ups to print the receipt.');
    popup.document.write(`<html><head><title>Receipt</title><style>body{font:14px Arial;padding:24px;color:#17283d}h1{font-size:22px;margin:0}table{width:100%;border-collapse:collapse;margin:18px 0}td{padding:7px 0;border-bottom:1px solid #ddd}.total{font-size:18px;font-weight:bold;text-align:right}</style></head><body><h1>${receipt.system_name}</h1><p>Receipt: ${receipt.transaction_id}<br/>Sales person: ${receipt.cashier}<br/>${new Date(receipt.timestamp).toLocaleString()}</p><table>${lines}</table><p class="total">Total: $${Number(receipt.total_amount).toFixed(2)}</p><p>Payment: ${receipt.payment_method}</p><p>Thank you for your purchase.</p></body></html>`);
    popup.document.close(); popup.focus(); popup.print();
  };

  if (loading) {
    return <div className="loading">Loading POS system...</div>;
  }

  return (
    <div className="pos-container">
      <div className="pos-header">
        <div className="header-left">
          {canGoBack && (
            <button className="back-button" onClick={onBack}>
              ← Back
            </button>
          )}
          <h2>Point of Sale</h2>
          <span className="user-badge">{user.full_name} ({user.role})</span>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}
      {success && <div className="success-message">{success}</div>}

      {receipt && <section className="receipt-preview">
        <h3>{receipt.system_name}</h3><p>Receipt #{receipt.transaction_id}</p>
        <p><strong>Sales person:</strong> {receipt.cashier}<br/>{new Date(receipt.timestamp).toLocaleString()}</p>
        {receipt.items.map(item => <div className="receipt-line" key={item.id}><span>{item.product_name} × {item.quantity}</span><span>${Number(item.total_price).toFixed(2)}</span></div>)}
        <div className="receipt-total">Total: ${Number(receipt.total_amount).toFixed(2)}</div>
        <button className="checkout-button" onClick={printReceipt}>Print receipt</button>
        <button className="cancel-button" onClick={() => setReceipt(null)}>Close preview</button>
      </section>}

      <div className="pos-layout">
        <div className="products-grid">
          <h3>Products</h3>
          <div className="products-list">
            {products.map(product => (
              <div key={product.product_id} className="product-card" onClick={() => addToCart(product)}>
                <div className="product-name">{product.name}</div>
                <div className="product-price">${product.price.toFixed(2)}</div>
                <div className="product-sku">{product.sku}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="cart-panel">
          <h3>Shopping Cart</h3>
          {cart.length === 0 ? (
            <div className="empty-cart">Cart is empty</div>
          ) : (
            <>
              <div className="cart-items">
                {cart.map(item => (
                  <div key={item.product_id} className="cart-item">
                    <div className="item-info">
                      <div className="item-name">{item.name}</div>
                      <div className="item-price">${item.price.toFixed(2)}</div>
                    </div>
                    <div className="item-controls">
                      <button onClick={() => updateQuantity(item.product_id, item.quantity - 1)}>-</button>
                      <span>{item.quantity}</span>
                      <button onClick={() => updateQuantity(item.product_id, item.quantity + 1)}>+</button>
                      <button className="remove-btn" onClick={() => removeFromCart(item.product_id)}>×</button>
                    </div>
                    <div className="item-total">${(item.price * item.quantity).toFixed(2)}</div>
                  </div>
                ))}
              </div>
              
              <div className="cart-summary">
                <div className="total-row">
                  <span>Total:</span>
                  <span className="total-amount">${calculateTotal()}</span>
                </div>
                <button 
                  className="checkout-button"
                  onClick={handleCheckout}
                  disabled={processing}
                >
                  {processing ? 'Processing...' : 'Complete Sale'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
