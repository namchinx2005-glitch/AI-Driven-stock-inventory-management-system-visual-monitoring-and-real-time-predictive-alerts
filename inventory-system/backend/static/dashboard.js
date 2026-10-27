/* Plain JavaScript client for the server-rendered Jinja dashboard.
   The video nodes deliberately live outside view sections: switching pages
   never stops MediaStream tracks, so shelf monitoring remains continuous. */
(() => {
  const $ = (selector) => document.querySelector(selector);
  const pollMs = Number(document.body.dataset.pollMs || 5000);
  const detectionMs = Number(document.body.dataset.detectionMs || 2000);
  const serverCameraOwnsDevice = document.body.dataset.serverCamera === 'true';
  const applyTheme = (theme) => {
    const dark = theme === 'dark';
    document.body.classList.toggle('theme-dark', dark);
    $('#theme-toggle').setAttribute('aria-pressed', String(dark));
    $('#theme-toggle').setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
    $('#theme-toggle-text').textContent = dark ? 'Light' : 'Dark';
    $('#theme-toggle span:first-child').textContent = dark ? '☀' : '☾';
    localStorage.setItem('ledgerlens-theme', dark ? 'dark' : 'light');
  };
  applyTheme(localStorage.getItem('ledgerlens-theme') || 'light');
  let token = localStorage.getItem('token');
  let user = JSON.parse(localStorage.getItem('user') || 'null');
  let stock = [], products = [], cart = [], stream = null, scanBusy = false, lastAlertId = null, posCategory = 'All';

  const json = async (path, options = {}) => {
    const headers = {...(options.headers || {})};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path, {...options, headers});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `${path} failed (${response.status})`);
    return data;
  };
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message = (text) => { const el = $('#toast'); el.textContent = text; el.hidden = false; clearTimeout(el.timer); el.timer = setTimeout(() => el.hidden = true, 7000); };
  const money = n => `USD $${Number(n || 0).toFixed(2)}`;

  function showApp() {
    $('#login').hidden = true; $('#app').hidden = false;
    $('#current-user').textContent = `${user.full_name} (${user.role})`;
    document.querySelectorAll('[data-manager-only]').forEach(el => el.hidden = !['manager', 'admin'].includes(user.role));
    document.querySelectorAll('[data-manager-role]').forEach(el => el.hidden = user.role !== 'manager');
    if (user.role === 'manager') $('#new-user-form option[value="admin"]')?.remove();
    refresh(); loadProducts();
  }
  function setView(name) {
    document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === `${name}-view`));
    document.querySelectorAll('[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === name));
    $('#page-title').textContent = ({dashboard:'Just-in-Time Control',camera:'Camera monitor',inventory:'Inventory',pos:'Point of sale',analytics:'Analytics',users:'User management'})[name];
    $('#persistent-camera').style.display = stream && name !== 'camera' ? 'block' : 'none';
    if (stream && name !== 'camera') $('#mini-camera').play().catch(() => {});
    if (name === 'inventory') renderInventory();
    if (name === 'pos') renderPOS();
    if (name === 'analytics') renderAnalytics();
    if (name === 'users') renderUsers();
  }
  async function refresh() {
    if (!token) return;
    try {
      const [nextStock, alerts, suggestions, review] = await Promise.all([json('/api/stock'), json('/api/alerts'), json('/api/restock-suggestions'), json('/api/restock-review')]);
      stock = nextStock; renderDashboard(alerts, suggestions, review); renderInventory();
      if ($('#analytics-view').classList.contains('active')) renderAnalytics();
      $('#connection').textContent = `Live · refreshed ${new Date().toLocaleTimeString()}`;
      const newest = alerts[0];
      if (newest && newest.id !== lastAlertId) { if (lastAlertId !== null) message(`Inventory alert: ${newest.message}`); lastAlertId = newest.id; }
    } catch (err) { $('#connection').textContent = `Connection issue: ${err.message}`; }
  }
  function renderDashboard(alerts, suggestions, review) {
    $('#stat-products').textContent = stock.length;
    const actionItems = stock.filter(x => x.status !== 'HEALTHY');
    const cover = stock.map(x => Number(x.days_remaining)).filter(Number.isFinite).filter(x => x >= 0);
    const averageCover = cover.length ? Math.round(cover.reduce((sum, x) => sum + x, 0) / cover.length) : null;
    $('#stat-low').textContent = actionItems.length;
    $('#stat-cover').textContent = averageCover === null ? '—' : `${averageCover}d`;
    $('#last-refresh').textContent = new Date().toLocaleTimeString();
    $('#jit-queue-count').textContent = `${suggestions.length} queued`;
    $('#jit-review-state').textContent = review.reviewed ? 'Complete' : 'Due now';
    $('#jit-title').textContent = actionItems.length ? `${actionItems.length} item${actionItems.length === 1 ? '' : 's'} need a pull signal` : 'Inventory flow is on track';
    $('#jit-status').textContent = actionItems.length ? `Replenish only what is needed: ${actionItems.map(x => x.label).join(', ')} need attention.` : 'Stock levels and demand forecasts are aligned with the current replenishment plan.';
    $('#stock-table').innerHTML = stock.map(x => `<tr><td>${escape(x.label)}</td><td>${x.current_stock}</td><td>${Number(x.burn_rate_per_day || 0).toFixed(1)}</td><td>${escape(x.depletion_date || '—')}</td><td class="status ${x.status}">${x.status}</td></tr>`).join('') || '<tr><td colspan="5">No inventory records.</td></tr>';
    $('#suggestions').innerHTML = suggestions.map(x => { const seasonal = x.seasonal_validation || {}; const factor = seasonal.validated ? ` · seasonal factor ${Number(x.seasonal_multiplier).toFixed(2)} (validated)` : (seasonal.reason ? ` · ${escape(seasonal.reason)}` : ''); const urgent = /immediately|out of stock/i.test(x.suggested_action || ''); return `<div class="suggestion jit-suggestion"><span class="jit-priority ${urgent ? 'urgent' : ''}">${urgent ? 'Act now' : 'Plan'}</span><strong>${escape(x.label)}</strong><br><span class="muted">${escape(x.suggested_action)} · order ${x.suggested_quantity ?? 0} · target ${x.target_stock ?? 0} · ${Number(x.daily_burn_rate || 0).toFixed(1)}/day${factor}</span><br><small class="muted">${escape(x.data_quality || '')}</small></div>`; }).join('') || '<p class="jit-clear">No replenishment actions are needed right now.</p>';
    const manager = ['manager', 'admin'].includes(user.role); const reviewText = review.reviewed ? `Reviewed for week of ${escape(review.review_week)}${review.review?.reviewed_at ? ` · ${new Date(review.review.reviewed_at).toLocaleString()}` : ''}` : `Weekly review due for week of ${escape(review.review_week)}.`; $('#restock-review').innerHTML = `<strong>${reviewText}</strong><br><span class="muted">Review reorder quantities weekly; record deliveries and POS sales daily before approving orders.</span>${manager && !review.reviewed ? '<br><button id="mark-restock-reviewed" class="quiet">Mark this week reviewed</button>' : ''}`; $('#mark-restock-reviewed')?.addEventListener('click', markRestockReviewed);
    $('#alerts').innerHTML = alerts.map(x => `<div class="alert-row"><strong>${x.level}</strong> — ${escape(x.message)}<br><small class="muted">${escape(x.timestamp)}</small></div>`).join('') || 'No recent alerts.';
    const urgent = stock.filter(x => x.status === 'CRITICAL');
    const warning = stock.filter(x => x.status === 'WARNING');
    const banner = $('#alert-banner');
    const active = urgent.length ? urgent : warning;
    banner.hidden = !active.length;
    banner.classList.toggle('warning', !urgent.length && warning.length > 0);
    banner.textContent = urgent.length
      ? `Critical: ${urgent.map(x => x.label).join(', ')} is out of stock. Restock immediately.`
      : warning.length ? `Warning: ${warning.map(x => x.label).join(', ')} is running low.` : '';
  }
  async function markRestockReviewed() { try { await json('/api/restock-review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({notes:'Reviewed in dashboard'})}); message('Weekly restock review recorded.'); refresh(); } catch (err) { message(err.message); } }
  async function loadProducts() {
    try { products = await json('/api/products'); renderInventory(); renderPOS(); fillProductSelects(); } catch (err) { message(err.message); }
  }
  function fillProductSelects() {
    const options = products.map(p => `<option value="${escape(p.product_id)}">${escape(p.name)}</option>`).join('');
    $('#analytics-product').innerHTML = options;
  }
  function renderInventory() {
    const q = ($('#inventory-search').value || '').toLowerCase();
    const manager = user?.role === 'manager';
    const matches = products.filter(p => `${p.name} ${p.product_id} ${p.sku || ''}`.toLowerCase().includes(q));
    $('#inventory-table').innerHTML = matches.map(p => { const s = stock.find(x => x.product_id === p.product_id) || {}; return `<tr><td>${p.image_url ? `<img class="inventory-thumb" src="${escape(p.image_url)}" alt="">` : ''}${escape(p.name)}</td><td>${escape(p.sku || '—')}</td><td>${money(p.price)}</td><td>${s.current_stock ?? 0}</td><td class="status ${s.status || ''}">${escape(s.status || '—')}</td>${manager ? `<td><button class="delete-product" data-delete-product="${escape(p.product_id)}" type="button">Delete</button></td>` : ''}</tr>`; }).join('') || `<tr><td colspan="${manager ? 6 : 5}">No matching products.</td></tr>`;
    $('#inventory-table').querySelectorAll('[data-delete-product]').forEach(button => button.onclick = async () => {
      const product = products.find(item => item.product_id === button.dataset.deleteProduct);
      if (!product || !confirm(`Delete ${product.name}? This cannot be undone.`)) return;
      try {
        await json(`/api/products/${encodeURIComponent(product.product_id)}`, {method:'DELETE'});
        cart = cart.filter(item => item.product_id !== product.product_id);
        message(`${product.name} deleted.`);
        await loadProducts();
        await refresh();
      } catch (err) { message(err.message); }
    });
  }
  function renderPOS() {
    const query = ($('#pos-search').value || '').toLowerCase();
    const categories = ['All', ...new Set(products.map(p => p.category || 'Other'))];
    if (!categories.includes(posCategory)) posCategory = 'All';
    $('#pos-categories').innerHTML = categories.map(category => `<button class="pos-category ${category === posCategory ? 'active' : ''}" data-category="${escape(category)}"><span>${category === 'All' ? '▦' : '◌'}</span>${escape(category)}</button>`).join('');
    $('#pos-categories').querySelectorAll('[data-category]').forEach(el => el.onclick = () => { posCategory = el.dataset.category; renderPOS(); });
    const matches = products.filter(p => (posCategory === 'All' || (p.category || 'Other') === posCategory) && `${p.name} ${p.product_id} ${p.sku || ''} ${p.barcode || ''}`.toLowerCase().includes(query));
    $('#pos-products').innerHTML = matches.map((p, index) => { const item = stock.find(s => s.product_id === p.product_id); const available = item?.current_stock ?? 0; const visual = ['◒','◈','◇','◉','◌','◐'][index % 6]; return `<button class="product pos-product" data-product="${escape(p.product_id)}" ${available <= 0 ? 'disabled title="Out of stock"' : ''}>${p.image_url ? `<img class="product-visual product-photo" src="${escape(p.image_url)}" alt="">` : `<span class="product-visual visual-${index % 6}">${visual}</span>`}<span class="product-meta"><strong>${escape(p.name)}</strong><small>${escape(p.category || 'Inventory')}</small></span><span class="product-price">${money(p.price)}</span><small class="product-stock">${available > 0 ? `${available} available` : 'Out of stock'}</small></button>`; }).join('') || '<p class="pos-empty">No products match this search.</p>';
    $('#pos-products').querySelectorAll('[data-product]').forEach(el => el.onclick = () => addCart(products.find(p => p.product_id === el.dataset.product)));
    $('#cart').innerHTML = cart.length ? cart.map(item => `<div class="cart-row"><span class="cart-item-dot">${escape(item.name).slice(0,1)}</span><span class="cart-item-name">${escape(item.name)}<small>${money(item.price)} each</small></span><span class="cart-quantity"><button data-minus="${escape(item.product_id)}">−</button><b>${item.quantity}</b><button data-plus="${escape(item.product_id)}">+</button></span><strong>${money(item.price * item.quantity)}</strong></div>`).join('') : '<div class="cart-empty"><span>+</span><p>Your order is empty</p><small>Select products from the menu to start a sale.</small></div>';
    const total = cart.reduce((sum, x) => sum + x.price * x.quantity, 0); $('#cart-total').textContent = money(total); $('#cart-subtotal').textContent = money(total); $('#pos-item-count').textContent = `${cart.reduce((sum, x) => sum + x.quantity, 0)} items`;
    $('#cart').querySelectorAll('[data-plus]').forEach(el => el.onclick = () => changeCart(el.dataset.plus, 1));
    $('#cart').querySelectorAll('[data-minus]').forEach(el => el.onclick = () => changeCart(el.dataset.minus, -1));
  }
  const addCart = product => { const available = stock.find(x => x.product_id === product.product_id)?.current_stock ?? 0; if (available <= 0) return message(`${product.name} is out of stock and cannot be added to the cart.`); const item = cart.find(x => x.product_id === product.product_id); if (item && item.quantity >= available) return message(`Only ${available} unit(s) of ${product.name} are available.`); item ? item.quantity++ : cart.push({...product, quantity:1}); renderPOS(); };
  const changeCart = (id, delta) => { cart = cart.map(x => x.product_id === id ? {...x, quantity:x.quantity + delta} : x).filter(x => x.quantity > 0); renderPOS(); };
  async function checkout() {
    if (!cart.length) return message('Add a product to the cart first.');
    const paymentMethod = document.querySelector('input[name="payment-method"]:checked')?.value;
    if (!paymentMethod) return message('Choose Cash, EcoCash, or Debit card before completing the sale.');
    try { const total = cart.reduce((sum,x) => sum+x.price*x.quantity,0); const result = await json('/api/pos/transaction', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:cart.map(x=>({product_id:x.product_id,quantity:x.quantity,unit_price:x.price})),total_amount:total,payment_method:paymentMethod})}); cart=[]; document.querySelectorAll('input[name="payment-method"]').forEach(input => input.checked = false); renderPOS(); renderReceipt(result.receipt); message(`Sale completed · Receipt No. ${result.receipt.receipt_no}`); refresh(); } catch (err) { message(err.message); }
  }
  function renderReceipt(receipt) {
    const safeItems = (receipt.items || []).map(item => `<div class="receipt-line"><span>${escape(item.product_name)} × ${item.quantity}</span><span>${money(item.total_price)}</span></div>`).join('');
    const paymentLabel = {cash:'Cash', ecocash:'EcoCash', debit_card:'Debit card'}[receipt.payment_method] || receipt.payment_method;
    $('#receipt-content').innerHTML = `<p>Receipt No. ${escape(receipt.receipt_no)}<br>${escape(receipt.cashier)}<br>${new Date(receipt.timestamp).toLocaleString()}</p>${safeItems}<hr><div class="receipt-line"><strong>Total</strong><strong>${money(receipt.total_amount)}</strong></div><p class="muted">Payment: ${escape(paymentLabel)}</p>`;
    $('#receipt').hidden = false;
  }
  function printReceipt() {
    const receipt = $('#receipt-content').innerHTML;
    const logo = $('#receipt .receipt-logo').outerHTML;
    const popup = window.open('', 'ledgerlens-receipt', 'width=420,height=640');
    if (!popup) return message('Allow pop-ups to print the receipt.');
    popup.document.write(`<!doctype html><title>LedgerLens receipt</title><style>body{font:14px Arial;padding:24px;color:#17283d}.receipt-logo{display:flex;align-items:center;gap:10px;margin-bottom:18px;font-size:22px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;color:#fff;background:#5486cf;font-weight:800}.receipt-line{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #ddd}</style>${logo}${receipt}<p>Thank you for your purchase.</p>`);
    popup.document.close(); popup.focus(); popup.print();
  }
  function seasonalRecommendation(top) {
    const month = new Date().getMonth() + 1;
    const leaders = top.slice(0, 3).map(x => x.name).join(', ') || 'your highest-selling items';
    const drinks = products.filter(p => /drink|juice|water|beverage|soda/i.test(`${p.name} ${p.category || ''}`));
    const drinkNames = drinks.slice(0, 3).map(p => p.name).join(', ') || 'water, juice and other cold drinks';
    if (month >= 9 && month <= 11) return `Zimbabwe is in its hot season (roughly September to mid-November). Use the selected sales period to prioritise ${leaders}; consider increasing safety stock for ${drinkNames}. This is a planning suggestion, not a demand guarantee.`;
    if (month === 12 || month <= 3) return `Zimbabwe's main rainy season is generally mid-November to mid-March. Prioritise your selected-period leaders (${leaders}) and maintain a buffer for weather-related delivery delays. This is a planning suggestion, not a demand guarantee.`;
    return `Use the selected period's leaders (${leaders}) as your first reorder candidates. Compare this with supplier lead time and current stock before purchasing.`;
  }
  async function renderAnalytics() {
    if (!products.length) return;
    const today = new Date().toISOString().slice(0,10); const monthAgo = new Date(Date.now() - 29 * 86400000).toISOString().slice(0,10);
    if (!$('#analytics-from').value) $('#analytics-from').value = monthAgo;
    if (!$('#analytics-to').value) $('#analytics-to').value = today;
    try { const result = await json(`/api/analytics/sales-analysis?from=${encodeURIComponent($('#analytics-from').value)}&to=${encodeURIComponent($('#analytics-to').value)}`); const series = result.daily || []; const max = Math.max(1,...series.map(x=>x.revenue || 0)); $('#sales-trend').innerHTML = series.map(x=>`<div class="bar" title="${escape(x.day)}: ${money(x.revenue)}" style="height:${Math.max(8,(x.revenue || 0)/max*150)}px"><small>${escape(x.day.slice(5))}</small></div>`).join('') || 'No sales data yet.'; $('#sales-summary').innerHTML = `<p><strong>${money(result.total_revenue)}</strong> revenue · <strong>${result.total_units}</strong> units${result.best_day ? ` · Best sales day: <strong>${escape(result.best_day.day)}</strong> (${money(result.best_day.revenue)})` : ''}</p>`; $('#most-purchased').innerHTML = (result.top_products || []).map(x=>`<div class="alert-row"><strong>${escape(x.name)}</strong> — ${x.total_sold} units · ${money(x.revenue)}</div>`).join('') || 'No sales data yet.'; $('#season-suggestion').textContent = seasonalRecommendation(result.top_products || []); } catch(err) { message(err.message); }
  }
  async function renderUsers() { if (!['manager','admin'].includes(user.role)) return; try { const users = await json('/api/users'); $('#users-list').innerHTML = users.map(x=>`<div class="alert-row"><strong>${escape(x.full_name)}</strong> · ${escape(x.username)} <span class="muted">${escape(x.role)}</span>${x.id !== user.user_id && (user.role === 'admin' || x.role !== 'admin') ? `<button class="delete-user" data-user-id="${x.id}" data-name="${escape(x.full_name)}">Delete</button>` : ''}</div>`).join(''); $('#users-list').querySelectorAll('.delete-user').forEach(el => el.onclick = async () => { if (!confirm(`Delete ${el.dataset.name}? This cannot be undone.`)) return; try { await json(`/api/users/${el.dataset.userId}`, {method:'DELETE'}); message('User deleted.'); renderUsers(); } catch(err) { message(err.message); } }); } catch(err) { message(err.message); } }

  function drawDetections(detections, video, regions = {}, counts = {}) {
    const canvas = $('#detection-overlay');
    const rect = video.getBoundingClientRect();
    if (!video.videoWidth || !video.videoHeight || !rect.width || !rect.height) return;
    canvas.width = Math.round(rect.width);
    canvas.height = Math.round(rect.height);
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const scale = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
    const offsetX = (canvas.width - video.videoWidth * scale) / 2;
    const offsetY = (canvas.height - video.videoHeight * scale) / 2;
    const toCanvas = (x, y) => [x * scale + offsetX, y * scale + offsetY];
    const regionColors = ['#35df96', '#57b7ff', '#ffd166', '#ff8b6b', '#c69cff', '#66d9e8'];
    ctx.font = 'bold 13px sans-serif';
    Object.entries(regions).forEach(([productId, definition], index) => {
      const box = definition.box || definition;
      if (!Array.isArray(box) || box.length !== 4) return;
      const [x1, y1] = toCanvas(box[0] * video.videoWidth / 1280, box[1] * video.videoHeight / 720);
      const [x2, y2] = toCanvas(box[2] * video.videoWidth / 1280, box[3] * video.videoHeight / 720);
      const color = regionColors[index % regionColors.length];
      const name = productId.replace(/[-_]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
      const countEntry = Object.entries(counts).find(([id]) => id.replace(/[^a-z0-9]/gi, '').toLowerCase() === productId.replace(/[^a-z0-9]/gi, '').toLowerCase());
      const caption = `${name} · ${countEntry?.[1] ?? counts[productId] ?? 0}`;
      ctx.fillStyle = '#101820cc';
      ctx.fillRect(x1, y1, Math.max(100, ctx.measureText(caption).width + 12), 22);
      ctx.fillStyle = color;
      ctx.fillText(caption, x1 + 6, y1 + 16);
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    });
    ctx.font = 'bold 13px sans-serif';
    detections.forEach(detection => {
      const [x1, y1] = toCanvas(detection.box[0], detection.box[1]);
      const [x2, y2] = toCanvas(detection.box[2], detection.box[3]);
      const color = detection.source === 'coco' ? '#ffad45' : '#35df96';
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      const zone = detection.region_id ? ` · ${detection.region_id.replace(/[-_]+/g, ' ')}` : '';
      ctx.fillText(`${detection.label}${zone} ${Math.round(detection.confidence * 100)}%`, x1, Math.max(15, y1 - 5));
    });
  }
  async function scan() {
    const cameraViewActive = $('#camera-view').classList.contains('active');
    const video = cameraViewActive ? $('#camera-video') : $('#mini-camera');
    if (!stream || scanBusy || video.readyState < 2 || !video.videoWidth) return;
    scanBusy = true;
    try {
      const frame = document.createElement('canvas');
      frame.width = video.videoWidth;
      frame.height = video.videoHeight;
      frame.getContext('2d').drawImage(video, 0, 0);
      if (cameraViewActive) $('#camera-status').textContent = 'Scanning…';
      const result = await json('/api/camera/scan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({image: frame.toDataURL('image/jpeg', .85)})
      });
      if (cameraViewActive) {
        const detections = result.detections || [];
        const regions = result.shelf_regions || {};
        const counts = result.observed_counts || {};
        drawDetections(detections, video, regions, counts);
        $('#region-counts').innerHTML = Object.entries(regions).map(([productId]) => {
          const label = productId.replace(/[-_]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
          const countEntry = Object.entries(counts).find(([id]) => id.replace(/[^a-z0-9]/gi, '').toLowerCase() === productId.replace(/[^a-z0-9]/gi, '').toLowerCase());
          return `<div class="region-count"><strong>${escape(label)}</strong><span>${Number(countEntry?.[1] ?? counts[productId] ?? 0)} detected</span></div>`;
        }).join('') || 'No shelf partitions configured.';
        if (result.supported_classes) $('#camera-supported-classes').textContent = `Supported: ${result.supported_classes.join(', ')}`;
        $('#detections').innerHTML = detections.map(detection => `<div class="detection"><strong>${escape(detection.label)}</strong> · ${escape(detection.source)} · ${Math.round(detection.confidence * 100)}%</div>`).join('') || 'No objects detected in this frame.';
        $('#camera-notice').textContent = result.notice || 'Monitoring';
        $('#camera-status').textContent = Object.keys(result.inventory_updates || {}).length ? 'Inventory updated' : 'Live monitoring';
      }
      if (Object.keys(result.inventory_updates || {}).length) { message(result.notice); refresh(); }
    } catch (err) {
      if (cameraViewActive) {
        $('#camera-status').textContent = 'Scan failed';
        $('#camera-notice').textContent = err.message;
      }
    } finally { scanBusy = false; }
  }
  function stopCamera() { if(stream) stream.getTracks().forEach(track=>track.stop()); stream=null; $('#camera-video').srcObject=null; $('#mini-camera').srcObject=null; $('#camera-toggle').textContent='Open camera'; $('#camera-chip').textContent='Camera off'; $('#camera-chip').classList.add('off'); $('#persistent-camera').style.display='none'; $('#camera-placeholder').hidden=false; $('#camera-placeholder').textContent='Click Open camera to start the live shelf stream.'; $('#camera-status').textContent='Camera off'; $('#camera-notice').textContent='The camera is closed. Click Open camera when you are ready to resume monitoring.'; $('#detections').textContent='No detections yet.'; const canvas=$('#detection-overlay'); canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height); }
  async function toggleCamera() { if(serverCameraOwnsDevice) return message('The backend camera worker is enabled. Disable START_CAMERA_WORKER_ON_BOOT to use on-demand site streaming.'); if(stream) { stopCamera(); return; } try { if(!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access is unavailable. Open this site on localhost or through HTTPS and check browser permissions.'); stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false}); $('#camera-video').srcObject=stream; $('#mini-camera').srcObject=stream; await $('#camera-video').play(); $('#mini-camera').play().catch(()=>{}); $('#camera-placeholder').hidden=true; $('#camera-toggle').textContent='Close camera'; $('#camera-chip').textContent='Camera live'; $('#camera-chip').classList.remove('off'); $('#mini-camera-label').textContent='Camera is live'; $('#camera-status').textContent='Live monitoring'; $('#camera-notice').textContent='Live video and shelf detection remain active as you navigate between modules.'; scan(); } catch(err) { if(stream) stopCamera(); $('#camera-status').textContent='Camera unavailable'; $('#camera-notice').textContent=err.name === 'NotAllowedError' ? 'Allow camera permission in your browser and try again.' : err.message; } }

  $('#login-form').onsubmit = async event => { event.preventDefault(); const form=new FormData(event.target); try { const result=await json('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.get('username'),password:form.get('password')})}); token=result.token;user=result.user;localStorage.setItem('token',token);localStorage.setItem('user',JSON.stringify(user));showApp(); } catch(err) { const el=$('#login-error');el.textContent=err.message;el.hidden=false; } };
  $('#logout').onclick=()=>{if(stream) stopCamera();localStorage.removeItem('token');localStorage.removeItem('user');token=null;user=null;$('#app').hidden=true;$('#login').hidden=false;};
  $('#theme-toggle').onclick=()=>applyTheme(document.body.classList.contains('theme-dark') ? 'light' : 'dark');
  document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>setView(el.dataset.view)); $('#camera-toggle').textContent='Open camera'; $('#camera-toggle').onclick=toggleCamera; $('#camera-close-mini').onclick=stopCamera; $('#inventory-search').oninput=renderInventory; $('#inventory-refresh').onclick=()=>{loadProducts();refresh();}; $('#pos-search').oninput=renderPOS; $('#checkout').onclick=checkout; $('#print-receipt').onclick=printReceipt; $('#analytics-product').onchange=renderAnalytics; $('#analytics-run').onclick=renderAnalytics;
  $('#product-image').onchange=event=>{const file=event.target.files[0], preview=$('#product-image-preview'); if(!file){preview.hidden=true;preview.removeAttribute('src');return;} preview.src=URL.createObjectURL(file);preview.hidden=false;};
  $('#add-product-form').onsubmit=async event=>{event.preventDefault();if(user?.role!=='manager')return message('Only the manager can add products.');const form=new FormData(event.target);const name=String(form.get('name')||'').trim();form.set('product_id',name.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,''));form.delete('image');const image=$('#product-image').files[0];if(image)form.set('image',image);try{const response=await fetch('/api/products',{method:'POST',headers:{Authorization:`Bearer ${token}`},body:form});const result=await response.json().catch(()=>({}));if(!response.ok)throw new Error(result.error||'Could not add product');message('Product added with zero stock. Open the camera to count shelf items.');event.target.reset();$('#product-image-preview').hidden=true;await loadProducts();await refresh();}catch(err){message(err.message);}};
  $('#new-user-form').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{const result=await json('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(form))});message(result.message);event.target.reset();renderUsers();}catch(err){message(err.message);}};
  if(serverCameraOwnsDevice) { $('#camera-toggle').hidden=true; $('#camera-video').hidden=true; $('#camera-placeholder').textContent='The backend camera worker is monitoring the shelf. Live video is not streamed to this page.'; $('#camera-status').textContent='Backend camera worker active'; $('#camera-notice').textContent=`Shelf counts are processed every ${detectionMs / 1000} seconds. Current stock and alerts update on the dashboard.`; $('#camera-mode-note').textContent=`The backend shelf camera scans every ${detectionMs / 1000} seconds. Counts and alerts refresh here; browser camera access is disabled to prevent device contention.`; $('#camera-chip').textContent='Camera worker active'; $('#camera-chip').classList.remove('off'); } else { $('#camera-mode-note').textContent='Open the camera to stream and monitor the shelf. It stays live as you move between modules until you close it.'; }
  setInterval(refresh,pollMs); setInterval(scan,detectionMs); if(token && user) showApp();
})();
