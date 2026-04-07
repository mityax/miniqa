/**
 * state.js — Central reactive store
 *
 * All components import this module and read/write directly.
 * Third-party objects (Ace, RFB) are stored in plain module-level
 * variables to avoid Vue's Proxy wrapping breaking them.
 */

import {reactive} from 'vue';

// -- Non-reactive singletons (heavy objects that must not be proxied) ---------

let _aceEditor = null;
let _rfb       = null;

export const editorRef = {
  get()      { return _aceEditor; },
  set(e)     { _aceEditor = e;    },
  clear()    { _aceEditor = null; },
};

export const rfbRef = {
  get()      { return _rfb;   },
  set(r)     { _rfb = r;      },
  clear()    { _rfb = null;   },
};

// -- Reactive state ------------------------------------------------------------

export const state = reactive({
  // Connection
  connected:       false,
  _tabConflict:    false,
  _runAfterPrepare: false,

  // Test data
  tests:  [],          // Array<{ stem, filename, yaml }>
  schema: null,        // JSON schema object from /api/schema

  // Pipeline state (mirrors backend)
  pipeline: {
    running:        false,
    statuses:       {},   // stem → status string
    current_steps:  {},   // stem → step index
    test_start_time:{},   // stem → unix timestamp (seconds)
    results:        {},   // stem → result object
  },

  // Edit-view state (mirrors backend edit-worker state)
  edit: {
    test_stem:            null,
    yaml:                 '',
    has_unsaved:          false,
    worker_status:        'stopped',
    worker_message:       null,
    worker_progress:      null,  // [done, total] or null
    current_step:         null,
    step_results:         [],
    _popoverAutoOpened:   false,
  },

  novnc_port: 6080,

  // UI-only
  selectedStems:       [],   // Array<stem> (Set semantics, de-duped on add)
  currentView:         'pipeline',
  rfbReconnectAttempts: 0,

  // Step popover (edit view sidebar)
  stepPopover: {
    visible: false,
    stepIdx: null,
    sr:      null,     // step result object
    top:     0,        // px, relative to #edit-layout
    left:    34,       // px
  },

  // -- Modal / overlay service state ----------------------------------------

  prompt: {
    visible:      false,
    title:        '',
    description:  '',
    defaultValue: '',
    _resolve:     null,   // Promise resolver — not reactive-safe but never watched
  },

  lightbox: {
    visible: false,
    src:     '',
  },

  diff: {
    visible:       false,
    refPath:       '',
    actualPath:    '',
    refName:       '',
    regions:       null,
    ignoreRegions: null,
  },

  schemaError: {
    visible:       false,
    errors:        [],
    _onSaveAnyway: null,
  },

  // Toast queue
  toasts: [],  // Array<{ id, msg, kind }>

  // Theme — kept in state so both views stay in sync
  theme: localStorage.getItem('theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
});
