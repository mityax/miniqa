/**
 * vnc.js — noVNC RFB connection lifecycle and VNC overlay interaction tools.
 *
 * The RFB instance lives outside Vue's reactive system (stored in rfbRef)
 * so Vue's Proxy wrapper never touches the noVNC object graph.
 */

import {rfbRef, state} from './state.js';
import {insertOrCopy} from './editor.js';
import {toast} from './api.js';
import RFB from 'novnc/core/rfb.js';


// -- Connection ----------------------------------------------------------------

export async function startVnc(screenEl) {
  if (rfbRef.get()) return;

  try {
    const wsUrl  = `ws://${location.hostname}:${state.novnc_port}`;
    const rfb    = new RFB(screenEl, wsUrl);

    rfb.viewOnly      = true;
    rfb.resizeSession = false;
    rfb.scaleViewport = true;

    rfb.addEventListener('connect', () => { state.rfbReconnectAttempts = 0; });
    rfb.addEventListener('disconnect', () => {
      rfbRef.clear();
      if (state.rfbReconnectAttempts < 3) {
        state.rfbReconnectAttempts++;
        setTimeout(() => startVnc(screenEl), 500);
      }
    });

    rfbRef.set(rfb);
  } catch (e) {
    console.warn('[VNC] Failed to connect:', e);
  }
}

export function stopVnc() {
  const rfb = rfbRef.get();
  if (!rfb) return;
  try { rfb.disconnect(); } catch {}
  rfbRef.clear();
  state.rfbReconnectAttempts = 0;
}

// -- Overlay — coordinate & colour picking -------------------------------------

/**
 * Wire mouse events on `overlayEl` (a transparent div covering the VNC canvas).
 * Supports four interaction modes:
 *   Click         → insert "%x %y" position percentage
 *   Shift+Click   → insert hex colour at that pixel
 *   Drag          → insert "%x %y %w %h" region percentage
 *   Shift+Drag    → insert dominant hex colour of the dragged region
 *
 * Returns a cleanup function.
 */
export function initVncOverlay(overlayEl) {
  let dragState   = null;
  let selectionEl = null;

  function removeSelection() {
    if (selectionEl) { selectionEl.remove(); selectionEl = null; }
  }

  function getCanvas() {
    return overlayEl.closest('#vnc-container')?.querySelector('#vnc-screen canvas') ?? null;
  }

  const onMousedown = (e) => {
    e.preventDefault();
    const canvas = getCanvas();
    if (!canvas) return;
    dragState = {
      startX:     e.clientX,
      startY:     e.clientY,
      shiftKey:   e.shiftKey,
      canvasRect: canvas.getBoundingClientRect(),
    };
  };

  const onMousemove = (e) => {
    if (!dragState) return;
    const dx = Math.abs(e.clientX - dragState.startX);
    const dy = Math.abs(e.clientY - dragState.startY);
    if (dx < 4 && dy < 4) return;

    removeSelection();
    const oRect = overlayEl.getBoundingClientRect();
    const x1 = Math.min(dragState.startX, e.clientX) - oRect.left;
    const y1 = Math.min(dragState.startY, e.clientY) - oRect.top;
    const w  = Math.abs(e.clientX - dragState.startX);
    const h  = Math.abs(e.clientY - dragState.startY);

    selectionEl           = document.createElement('div');
    selectionEl.className = dragState.shiftKey ? 'vnc-selection-color' : 'vnc-selection-rect';
    selectionEl.style.cssText = `left:${x1}px;top:${y1}px;width:${w}px;height:${h}px`;
    overlayEl.appendChild(selectionEl);
  };

  const onMouseup = async (e) => {
    if (!dragState) return;
    removeSelection();

    const dx     = Math.abs(e.clientX - dragState.startX);
    const dy     = Math.abs(e.clientY - dragState.startY);
    const isDrag = dx > 6 || dy > 6;

    const { startX, startY, shiftKey, canvasRect } = dragState;
    dragState = null;

    const canvas = getCanvas();
    if (!canvas) return;

    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const toPct = (px, total) => (px / total) * 100;

    if (isDrag) {
      const x1pct = toPct(Math.min(startX, e.clientX) - canvasRect.left, canvasRect.width);
      const y1pct = toPct(Math.min(startY, e.clientY) - canvasRect.top,  canvasRect.height);
      const wpct  = toPct(Math.abs(e.clientX - startX), canvasRect.width);
      const hpct  = toPct(Math.abs(e.clientY - startY), canvasRect.height);

      const cx = clamp(x1pct, 0, 100);
      const cy = clamp(y1pct, 0, 100);
      const cw = clamp(wpct, 0, 100 - cx);
      const ch = clamp(hpct, 0, 100 - cy);

      if (shiftKey) {
        try {
          const scaleX = canvas.width  / canvasRect.width;
          const scaleY = canvas.height / canvasRect.height;
          const px1 = Math.round((Math.min(startX, e.clientX) - canvasRect.left) * scaleX);
          const py1 = Math.round((Math.min(startY, e.clientY) - canvasRect.top)  * scaleY);
          const pw  = Math.max(1, Math.round(Math.abs(e.clientX - startX) * scaleX));
          const ph  = Math.max(1, Math.round(Math.abs(e.clientY - startY) * scaleY));
          const ctx = canvas.getContext('2d');
          insertOrCopy(getDominantColor(ctx.getImageData(px1, py1, pw, ph)));
        } catch (err) {
          toast('Could not read canvas pixels (cross-origin?)', 'error');
          console.error(err);
        }
      } else {
        insertOrCopy(`${cx.toFixed(1)}% ${cy.toFixed(1)}% ${cw.toFixed(1)}% ${ch.toFixed(1)}%`);
      }
    } else {
      const x = toPct(e.clientX - canvasRect.left, canvasRect.width);
      const y = toPct(e.clientY - canvasRect.top,  canvasRect.height);

      if (shiftKey) {
        try {
          const ctx = canvas.getContext('2d');
          const px  = Math.round((e.clientX - canvasRect.left) * (canvas.width  / canvasRect.width));
          const py  = Math.round((e.clientY - canvasRect.top)  * (canvas.height / canvasRect.height));
          const d   = ctx.getImageData(px, py, 1, 1).data;
          insertOrCopy(`#${[d[0], d[1], d[2]].map(v => v.toString(16).padStart(2, '0')).join('')}`);
        } catch {
          toast('Could not read pixel (cross-origin canvas?)', 'error');
        }
      } else {
        insertOrCopy(`${x.toFixed(1)}% ${y.toFixed(1)}%`);
      }
    }
  };

  const onMouseleave = () => {
    if (dragState) { dragState = null; removeSelection(); }
  };

  const onContextmenu = (e) => e.preventDefault();

  overlayEl.addEventListener('mousedown',   onMousedown);
  overlayEl.addEventListener('mousemove',   onMousemove);
  overlayEl.addEventListener('mouseup',     onMouseup);
  overlayEl.addEventListener('mouseleave',  onMouseleave);
  overlayEl.addEventListener('contextmenu', onContextmenu);

  // Return cleanup
  return () => {
    overlayEl.removeEventListener('mousedown',   onMousedown);
    overlayEl.removeEventListener('mousemove',   onMousemove);
    overlayEl.removeEventListener('mouseup',     onMouseup);
    overlayEl.removeEventListener('mouseleave',  onMouseleave);
    overlayEl.removeEventListener('contextmenu', onContextmenu);
  };
}

// -- Dominant colour (k-means, k=3) -------------------------------------------

function getDominantColor(imageData, quantizeBits = 6) {
  const pixels = imageData.data ?? imageData; // Uint8ClampedArray, RGBA layout

  const shift   = 8 - quantizeBits;
  const levels  = 1 << quantizeBits;           // 64 buckets per channel
  const counts  = new Uint32Array(levels ** 3); // replaces np.bincount

  // Quantize + pack each pixel into one bucket index
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i]     >> shift;
    const g = pixels[i + 1] >> shift;
    const b = pixels[i + 2] >> shift;
    counts[(r << (quantizeBits * 2)) | (g << quantizeBits) | b]++;
  }

  // argmax  (np.argmax equivalent)
  let domPacked = 0;
  for (let i = 1; i < counts.length; i++) {
    if (counts[i] > counts[domPacked]) domPacked = i;
  }

  // Unpack and map each bucket back to its 8-bit midpoint
  const maskCh = levels - 1;
  const mid    = (1 << shift) >> 1; // integer division: same as in python

  const dom = [
    (((domPacked >> (quantizeBits * 2)) & maskCh) << shift) | mid, // R
    (((domPacked >>  quantizeBits)      & maskCh) << shift) | mid, // G
    (( domPacked                        & maskCh) << shift) | mid, // B
  ];

  return `#${dom.map(v => v.toString(16).padStart(2, '0')).join('')}`;
}
