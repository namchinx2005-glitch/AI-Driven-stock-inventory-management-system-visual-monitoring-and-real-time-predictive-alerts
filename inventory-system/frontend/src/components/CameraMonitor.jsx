import React, { useState, useEffect, useRef } from 'react';

export default function CameraMonitor({ user, onBack, canGoBack }) {
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const [detectionStatus, setDetectionStatus] = useState('Ready');
  const [detections, setDetections] = useState([]);
  const [scanNotice, setScanNotice] = useState('');
  const [products, setProducts] = useState([]);
  const [receipt, setReceipt] = useState({ product_id: 'salt_1kg', quantity: 1 });
  const [receiving, setReceiving] = useState(false);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const overlayRef = useRef(null);
  const scanBusyRef = useRef(false);

  const drawDetections = (items, width, height) => {
    const canvas = overlayRef.current;
    if (!canvas || !width || !height) return;
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, width, height);
    ctx.lineWidth = Math.max(2, width / 320);
    ctx.font = `${Math.max(14, width / 55)}px sans-serif`;
    items.forEach(item => {
      if (!item.box) return;
      const [x1, y1, x2, y2] = item.box;
      const label = `${item.label} ${Math.round(item.confidence * 100)}%`;
      ctx.strokeStyle = '#32e68a'; ctx.fillStyle = '#32e68a';
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      const textWidth = ctx.measureText(label).width + 10;
      ctx.fillRect(x1, Math.max(0, y1 - 25), textWidth, 24);
      ctx.fillStyle = '#102030'; ctx.fillText(label, x1 + 5, Math.max(18, y1 - 7));
    });
  };

  const toggleCamera = async () => {
    if (cameraOn) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setCameraOn(false);
      setDetectionStatus('Ready');
      return;
    }
    
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Camera access needs a modern browser served from localhost or HTTPS. Open this app at http://localhost:5173, not a network IP.');
      }
      setDetectionStatus('Connecting...');
      // Do not demand a fixed resolution: many integrated laptop cameras reject it.
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
      streamRef.current = stream;
      setCameraError('');
      setCameraOn(true);
      setDetectionStatus('Connecting...');
    } catch (error) {
      const explanations = {
        NotAllowedError: 'Camera permission was denied. Use the browser lock icon beside the address bar to allow Camera, then try again.',
        NotFoundError: 'No camera was found. Check that the laptop webcam is connected and enabled.',
        NotReadableError: 'The camera is busy in another app (such as Zoom/Teams). Close that app and try again.',
      };
      setCameraError(explanations[error.name] || error.message || "Camera could not be opened");
      setDetectionStatus('Error');
    }
  };

  // The video element is rendered only after cameraOn becomes true. Attach the
  // stream after that render; attaching it in toggleCamera happens too early.
  useEffect(() => {
    if (!cameraOn || !videoRef.current || !streamRef.current) return undefined;

    const video = videoRef.current;
    video.srcObject = streamRef.current;
    const startPlayback = async () => {
      try {
        await video.play();
        setDetectionStatus('Live');
      } catch (error) {
        setCameraError(`Camera preview could not start: ${error.message}`);
        setDetectionStatus('Error');
      }
    };
    video.addEventListener('loadedmetadata', startPlayback, { once: true });
    startPlayback();

    return () => {
      video.removeEventListener('loadedmetadata', startPlayback);
      video.srcObject = null;
    };
  }, [cameraOn]);

  const captureFrame = async () => {
    if (!cameraOn || !videoRef.current || scanBusyRef.current) return;
    
    try {
      scanBusyRef.current = true;
      const video = videoRef.current;
      if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth || !video.videoHeight) {
        setDetectionStatus('Waiting for camera frame…');
        return;
      }
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Could not prepare the webcam frame');
      ctx.drawImage(video, 0, 0);
      
      setDetectionStatus('Scanning…');
      const image = canvas.toDataURL('image/jpeg', 0.85);
      const response = await fetch('/api/camera/scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({ image })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Detection failed');
      setDetections(result.detections || []);
      drawDetections(result.detections || [], video.videoWidth, video.videoHeight);
      setScanNotice(result.notice || `${result.detections?.length || 0} COCO objects detected`);
      setDetectionStatus(Object.keys(result.inventory_updates || {}).length ? 'Inventory updated' : 'Monitoring');
    } catch (error) {
      setCameraError(error.message || 'Could not scan this frame');
      setDetectionStatus('Scan failed');
    } finally {
      scanBusyRef.current = false;
    }
  };

  useEffect(() => {
    fetch('/api/products').then(r => r.ok ? r.json() : []).then(setProducts).catch(() => {});
  }, []);

  // The visible monitor scans one browser frame every two seconds after Start.
  useEffect(() => {
    if (!cameraOn) return undefined;
    const firstScan = window.setTimeout(captureFrame, 700);
    const id = window.setInterval(captureFrame, 2000);
    return () => { window.clearTimeout(firstScan); window.clearInterval(id); };
  }, [cameraOn]);

  const receiveDetectedStock = async () => {
    setReceiving(true); setCameraError('');
    try {
      const response = await fetch('/api/inventory/receive', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({ ...receipt, quantity: Number(receipt.quantity), source: 'camera', note: 'Webcam receipt confirmed by operator' })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not receive stock');
      setScanNotice(`Received successfully. On hand: ${result.current_stock}`);
    } catch (error) { setCameraError(error.message); } finally { setReceiving(false); }
  };

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <div className="camera-monitor-container">
      <div className="camera-header">
        <div className="header-left">
          {canGoBack && (
            <button className="back-button" onClick={onBack}>
              ← Back
            </button>
          )}
          <h2>Shelf Camera Monitor</h2>
          <span className="user-badge">{user.full_name} ({user.role})</span>
        </div>
        <div className="header-right">
          <span className={`status-badge ${cameraOn ? 'live' : 'ready'}`}>
            {detectionStatus}
          </span>
          <button 
            className={`camera-toggle ${cameraOn ? 'stop' : 'start'}`}
            onClick={toggleCamera}
          >
            {cameraOn ? 'Stop Camera' : 'Start Camera'}
          </button>
        </div>
      </div>

      {cameraError && <div className="error-message">{cameraError}</div>}

      <div className="camera-layout">
        <div className="camera-feed">
          <div className="camera-frame">
            {cameraOn ? (
              <><video ref={videoRef} autoPlay muted playsInline />
              <canvas ref={overlayRef} className="detection-overlay" aria-label="YOLO detection overlay" /></>
            ) : (
              <div className="camera-placeholder">
                <div className="placeholder-icon">📷</div>
                <div className="placeholder-text">
                  Start camera to monitor shelf activity
                </div>
                <div className="placeholder-subtext">
                  Scan items arriving at the store using YOLO26n / COCO
                </div>
              </div>
            )}
          </div>
          
          {cameraOn && (
            <div className="camera-controls">
              <button className="capture-button" onClick={captureFrame}>
                Capture Frame for Detection
              </button>
            </div>
          )}
          <div className="camera-controls">
            <strong>Confirm stock receipt</strong>
            <select value={receipt.product_id} onChange={e => setReceipt({ ...receipt, product_id: e.target.value })}>
              {products.map(product => <option key={product.product_id} value={product.product_id}>{product.name}</option>)}
            </select>
            <input type="number" min="1" value={receipt.quantity} onChange={e => setReceipt({ ...receipt, quantity: e.target.value })} />
            <button className="capture-button" disabled={receiving} onClick={receiveDetectedStock}>{receiving ? 'Saving…' : 'Add confirmed stock'}</button>
          </div>
        </div>

        <div className="detection-panel">
          <h3>Current Detections</h3>
          {detections.length === 0 ? (
            <div className="no-detections">
              <div className="no-data-icon">🔍</div>
              <div>No detections yet</div>
              <div className="no-data-subtext">
                Start camera; detection boxes will update every 2 seconds
              </div>
            </div>
          ) : (
            <div className="detection-list">
              {detections.map((detection, index) => (
                <div key={index} className="detection-item">
                  <div className="detection-info">
                    <div className="detection-product">{detection.label}</div>
                    <div className="detection-count">{Math.round(detection.confidence * 100)}% confidence</div>
                  </div>
                  <div className={`detection-status ${detection.status}`}>
                    {detection.status}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="detection-info">
            {scanNotice && <p>{scanNotice}</p>}
            <h4>How it works:</h4>
            <ul>
              <li>Use the laptop camera to scan a receiving item.</li>
              <li>YOLO26n returns standard COCO classes from the frame.</li>
              <li>Confirm the product and quantity to add an auditable receipt.</li>
              <li>Salt is not a COCO class, so select Salt and confirm manually until custom training is added.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
