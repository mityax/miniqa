/**
 * api.js — WebSocket connection, message dispatch, and toast service.
 *
 * The WebSocket is the only realtime channel.  All state mutations that
 * originate from the backend flow through handleMessage().
 */

import {state} from './state.js';

// -- Toast ---------------------------------------------------------------------

let _toastSeq = 0;

/** Display a transient notification. */
export function toast(msg, kind = 'info', duration) {
  duration ??= Math.min(
      15_000,
      Math.max(
          msg.length * 25 * (kind === 'error' ? 2 : 1),
          1000,
      )
  );
  const id = ++_toastSeq;
  state.toasts.push({ id, msg, kind });
  setTimeout(() => {
    const idx = state.toasts.findIndex(t => t.id === id);
    if (idx !== -1) state.toasts.splice(idx, 1);
  }, duration);
}

// -- WebSocket -----------------------------------------------------------------

let _ws = null;

/** Send a typed message to the backend. No-op when not connected. */
export function send(type, payload = {}) {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type, payload }));
  }
}

export function initWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws`);

  _ws.onopen    = () => { state.connected = true; };
  _ws.onclose   = () => {
    state.connected = false;
    setTimeout(() => { if (!state._tabConflict) initWs(); }, 2000);
  };
  _ws.onmessage = (e) => {
    try { handleMessage(JSON.parse(e.data)); } catch {}
  };
}

// -- Message handlers ----------------------------------------------------------

function handleMessage({ type, payload }) {
  switch (type) {

    case 'tab_conflict':
      state._tabConflict = true;
      break;

    case 'state':
      Object.assign(state.pipeline, payload.pipeline);
      Object.assign(state.edit,     payload.edit);
      state.novnc_port = payload.novnc_port;
      break;

    case 'tests':
      state.tests = payload;
      break;

    case 'test_status': {
      const { stem, status, result, current_step } = payload;
      state.pipeline.statuses[stem]      = status;
      state.pipeline.results[stem]       = result;
      state.pipeline.current_steps[stem] = current_step;
      break;
    }

    case 'pipeline_done':
      state.pipeline.running = false;
      if (Object.values(state.pipeline.results).every(r => r.success)) {
        toast("All test succeeded.", "success");
      }
      break;

    case 'edit_worker_update':
      Object.assign(state.edit, {
        worker_status:   payload.status,
        worker_message:  payload.message === null
          ? null
          : (payload.message ?? payload.result?.message ?? state.edit.worker_message),
        worker_progress: payload.progress ?? null,
        current_step:    typeof payload.current_step !== 'undefined'
          ? payload.current_step
          : state.edit.current_step,
        step_results:    payload.result?.step_results ?? state.edit.step_results,
      });

      if (payload.result) _emit('run_result', payload.result);

      // Auto-open popover on first failed step when run completes
      if (payload.status === 'ready' && !state.edit._popoverAutoOpened && state.edit.step_results?.length) {
        const failedIdx = state.edit.step_results.findIndex(r => r.success === false);
        if (failedIdx >= 0) {
          state.edit._popoverAutoOpened = true;
          setTimeout(() => _emit('open_popover', failedIdx), 50);
        }
      }

      // Auto-run after snapshot preparation finishes
      if (payload.status === 'ready' && state._runAfterPrepare) {
        state._runAfterPrepare = false;
        send('run_test', { stem: state.edit.test_stem, yaml: state.edit.yaml });
      }
      break;

    case 'saved':
      state.edit.has_unsaved = false;
      toast('Saved', 'success');
      break;

    case 'screenshot_created':
      toast(`Screenshot saved: ${payload.name}`, 'success');
      _emit('insert_or_copy', payload.name);
      _emit('refresh_refs');
      break;

    case 'screenshots_updated':
    case 'reference_replaced':
      _emit('refresh_refs');
      if (type === 'reference_replaced') toast('Reference screenshot replaced', 'success');
      break;

    case 'error':
      toast(payload.message, 'error');
      break;
  }
}

// -- Cross-component event bus -------------------------------------------------

const _listeners = {};

function _emit(event, detail) {
  (_listeners[event] || []).forEach(fn => fn(detail));
}

export function onApiEvent(event, fn) {
  if (!_listeners[event]) _listeners[event] = [];
  _listeners[event].push(fn);
  return () => { _listeners[event] = _listeners[event].filter(f => f !== fn); };
}
